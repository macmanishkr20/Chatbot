"""
Retrieval grader node (CRAG — Corrective RAG).

Evaluates whether search-retrieved documents are relevant to the user's query
BEFORE generation begins.  If relevance is below the configured threshold, the
node reformulates the query, re-embeds, re-searches, and re-grades — all
internally (no graph cycle).  Maximum retry count is configurable.

Design decisions:
  - Uses the direct OpenAI async client (NOT LangChain AzureChatOpenAI) so that
    no tokens leak into the SSE ``messages`` stream mode.
  - Always returns ``grader_passed=True`` eventually (fail-open) — the grader
    is a quality improvement, never a hard gate that drops user queries.
  - Self-contained retry avoids graph topology cycles and loop detection.
"""
from __future__ import annotations

import asyncio
import json
import logging

from config import (
    AZURE_OPENAI_EMBED_API_KEY,
    AZURE_OPENAI_EMBED_ENDPOINT,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
    AZURE_OPENAI_CHAT_API_VERSION,
    GRADER_MAX_RETRIES,
    GRADER_MAX_TOKENS,
    GRADER_RELEVANCE_THRESHOLD,
    GRADER_TEMPERATURE,
    TOP_K,
)
from graph.state import RAGState
from graph.nodes.search_node import _strip_internal_fields
from prompts.grader import (
    GRADER_SYSTEM_PROMPT,
    GRADER_REFORMULATE_PROMPT,
    grader_user_template,
    grader_reformulate_template,
)
from services.openai_client import (
    create_async_client,
    create_sync_client,
    get_embedding_model,
    get_llm_model,
    retry_with_embedding_backoff,
    retry_with_llm_backoff,
)
from services.search_client import SearchService
from services.telemetry import get_tracer_span

logger = logging.getLogger(__name__)


# ── Private helpers ───────────────────────────────────────────────────────────


@retry_with_llm_backoff()
async def _call_grader_llm(messages: list[dict], llm_model: str) -> dict:
    """Call the LLM for grading/reformulation with structured JSON output."""
    client = create_async_client(llm_model=llm_model)
    response = await client.chat.completions.create(
        messages=messages,
        model=llm_model,
        temperature=GRADER_TEMPERATURE,
        max_tokens=GRADER_MAX_TOKENS,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


async def _grade_relevance(query: str, events: list, llm_model: str) -> tuple[float, str]:
    """Grade how relevant the retrieved documents are to the query.

    Returns (score, reasoning).  On any failure, returns (1.0, "grading failed")
    to fail-open.
    """
    try:
        user_msg = grader_user_template(query, events)
        messages = [
            {"role": "system", "content": GRADER_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]
        result = await _call_grader_llm(messages, llm_model)
        score = float(result.get("score", 1.0))
        reasoning = result.get("reasoning", "")
        return score, reasoning
    except Exception as exc:
        logger.warning("grader: relevance grading failed: %s", exc, exc_info=True)
        return 1.0, "grading failed — proceeding with current results"


async def _reformulate_query(query: str, events: list, llm_model: str) -> str:
    """Reformulate the query to improve retrieval on retry."""
    try:
        # Summarise what the irrelevant docs were about (for steering away)
        topics = set()
        for doc in events[:3]:
            fn = (doc.get("function") or "").strip()
            if fn:
                topics.add(fn)
            content_preview = (doc.get("content") or "")[:100].strip()
            if content_preview:
                topics.add(content_preview[:50])
        events_summary = "; ".join(list(topics)[:3]) if topics else "unrelated content"

        user_msg = grader_reformulate_template(query, events_summary)
        messages = [
            {"role": "system", "content": GRADER_REFORMULATE_PROMPT},
            {"role": "user", "content": user_msg},
        ]
        result = await _call_grader_llm(messages, llm_model)
        reformulated = result.get("query", "").strip()
        return reformulated if reformulated else query
    except Exception as exc:
        logger.warning("grader: reformulation failed: %s", exc, exc_info=True)
        return query


@retry_with_embedding_backoff()
def _generate_embeddings(text: str, client, embedding_model: str) -> list:
    """Generate embeddings (sync, run via asyncio.to_thread)."""
    return client.embeddings.create(input=[text], model=embedding_model).data[0].embedding


async def _embed_query(query: str) -> list | None:
    """Generate vector embeddings for a query string."""
    try:
        embedding_model = get_embedding_model("grader_embed")
        client = create_sync_client(
            azure_endpoint=AZURE_OPENAI_EMBED_ENDPOINT,
            azure_key=AZURE_OPENAI_EMBED_API_KEY,
            llm_model=embedding_model,
        )
        return await asyncio.to_thread(
            _generate_embeddings, query, client, embedding_model=embedding_model
        )
    except Exception as exc:
        logger.warning("grader: embedding failed: %s", exc, exc_info=True)
        return None


async def _re_search(
    query: str,
    filter_expr: str | None,
    embedded: list,
    state: RAGState,
) -> list:
    """Re-run search with a reformulated query.

    On retry, we intentionally DROP any function-specific filter from the
    original query.  This allows the grader to discover results in other
    functions when the initial function selection was wrong.
    """
    try:
        # Strip function-specific clauses from the filter so re-search is broader.
        # Function filters look like: function eq 'XYZ' or search.in(function, ...)
        broadened_filter = _strip_function_filter(filter_expr)

        rewritten = {"query": query, "filter": broadened_filter}

        # Build content-type fallback chain (same logic as search_node)
        requested_ct = (state.get("content_type") or "qa_pair").strip() or "qa_pair"
        fallback_chain = [requested_ct]
        if requested_ct == "qa_pair":
            fallback_chain.append("document")

        search_service = SearchService()
        for ct in fallback_chain:
            ct_filter = f"content_type eq '{ct}'"
            odata_filter = f"({broadened_filter}) and ({ct_filter})" if broadened_filter else ct_filter
            results = await search_service.unified_search(
                rewritten, embedded, odata_filter=odata_filter
            )
            if results:
                return _strip_internal_fields(results[:TOP_K])

        return []
    except Exception as exc:
        logger.warning("grader: re-search failed: %s", exc, exc_info=True)
        return []


def _strip_function_filter(filter_expr: str | None) -> str | None:
    """Remove function-specific OData filter clauses to broaden re-search.

    Handles patterns like:
      - function eq 'TME'
      - (function eq 'TME') and (...)
      - search.in(function, 'TME,BMC', ',')
      - (...) and (function eq 'TME' or function eq 'BMC')
    """
    if not filter_expr:
        return None

    import re

    # Remove search.in(function, ...) clauses
    cleaned = re.sub(r"search\.in\(function,\s*'[^']*',\s*','\)", "", filter_expr)
    # Remove function eq '...' clauses
    cleaned = re.sub(r"function\s+eq\s+'[^']*'", "", cleaned)
    # Clean up leftover logical operators and parentheses
    cleaned = re.sub(r"\(\s*\)", "", cleaned)  # empty parens
    cleaned = re.sub(r"\s+and\s+and\s+", " and ", cleaned)  # double and
    cleaned = re.sub(r"^\s*and\s+", "", cleaned)  # leading and
    cleaned = re.sub(r"\s+and\s*$", "", cleaned)  # trailing and
    cleaned = re.sub(r"^\s*or\s+", "", cleaned)   # leading or
    cleaned = re.sub(r"\s+or\s*$", "", cleaned)   # trailing or
    cleaned = re.sub(r"\(\s*and\s*\)", "", cleaned)
    cleaned = re.sub(r"\(\s*or\s*\)", "", cleaned)
    cleaned = cleaned.strip()

    # If nothing meaningful remains, return None
    if not cleaned or cleaned in ("()", "( )", "and", "or"):
        return None

    return cleaned


# ── Main node ─────────────────────────────────────────────────────────────────


async def grader_node(state: RAGState) -> dict:
    """Evaluate retrieval relevance; reformulate and retry if below threshold.

    Always returns grader_passed=True eventually (fail-open).
    """
    with get_tracer_span("grader_node"):
        events = state.get("events", [])
        retry_count = state.get("grader_retry_count", 0)
        rewritten_query = state.get("rewritten_query") or {}
        query_text = rewritten_query.get("query", "")

        # ── Skip grading: nothing to grade ──
        if not events or not query_text:
            return {"grader_passed": True, "grader_score": None, "grader_retry_count": 0}

        if state.get("error_info"):
            return {"grader_passed": True, "grader_score": None, "grader_retry_count": 0}

        llm_model = get_llm_model("grader")

        # ── Grade relevance ──
        score, reasoning = await _grade_relevance(query_text, events, llm_model)

        logger.info(
            "grader: score=%.2f threshold=%.2f passed=%s retry=%d query=%s",
            score, GRADER_RELEVANCE_THRESHOLD, score >= GRADER_RELEVANCE_THRESHOLD,
            retry_count, query_text[:100],
        )

        if score >= GRADER_RELEVANCE_THRESHOLD:
            return {
                "grader_passed": True,
                "grader_score": score,
                "grader_retry_count": retry_count,
            }

        # ── Below threshold — check if retry is allowed ──
        if retry_count >= GRADER_MAX_RETRIES:
            logger.info("grader: max retries reached, proceeding with current results")
            return {
                "grader_passed": True,
                "grader_score": score,
                "grader_retry_count": retry_count,
            }

        # ── Reformulate → re-embed → re-search → re-grade ──
        reformulated = await _reformulate_query(query_text, events, llm_model)
        logger.info("grader: reformulated query: %s", reformulated[:100])

        new_embedded = await _embed_query(reformulated)
        if not new_embedded:
            # Embedding failed — proceed with current results
            return {
                "grader_passed": True,
                "grader_score": score,
                "grader_retry_count": retry_count + 1,
            }

        filter_expr = rewritten_query.get("filter")
        new_events = await _re_search(reformulated, filter_expr, new_embedded, state)

        if not new_events:
            # Re-search found nothing — keep original
            logger.info("grader: re-search returned no results, keeping original")
            return {
                "grader_passed": True,
                "grader_score": score,
                "grader_retry_count": retry_count + 1,
            }

        # ── Re-grade the new results ──
        new_score, new_reasoning = await _grade_relevance(reformulated, new_events, llm_model)
        logger.info("grader: retry score=%.2f query=%s", new_score, reformulated[:100])

        # Pick the better set of results
        if new_score > score:
            return {
                "grader_passed": True,
                "grader_score": new_score,
                "grader_retry_count": retry_count + 1,
                "events": new_events,
                "rewritten_query": {**rewritten_query, "query": reformulated},
                "embedded_query": new_embedded,
            }

        # New results aren't better — keep original
        return {
            "grader_passed": True,
            "grader_score": score,
            "grader_retry_count": retry_count + 1,
        }
