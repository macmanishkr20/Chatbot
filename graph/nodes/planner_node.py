"""
Planner node — classifies query complexity and decomposes multi-function
queries into per-function sub-queries for parallel execution.

Design decisions:
  - Uses direct OpenAI async client (NOT LangChain AzureChatOpenAI) to prevent
    token leakage into the SSE messages stream.
  - Fast-path: if only 1 function found, skips LLM call entirely.
  - Fail-open: on any error, treats query as simple and proceeds normally.
"""
from __future__ import annotations

import json
import logging

from config import MAX_SUB_QUERIES, PLANNER_MAX_TOKENS, PLANNER_TEMPERATURE
from graph.state import RAGState
from prompts.planner import PLANNER_SYSTEM_PROMPT, planner_user_template
from services.openai_client import (
    create_async_client,
    get_llm_model,
    retry_with_llm_backoff,
)
from services.telemetry import get_tracer_span

logger = logging.getLogger(__name__)


@retry_with_llm_backoff()
async def _call_planner_llm(messages: list[dict], llm_model: str) -> dict:
    """Call the LLM for query decomposition with structured JSON output."""
    client = create_async_client(llm_model=llm_model)
    response = await client.chat.completions.create(
        messages=messages,
        model=llm_model,
        temperature=PLANNER_TEMPERATURE,
        max_tokens=PLANNER_MAX_TOKENS,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


async def planner_node(state: RAGState) -> dict:
    """Classify query complexity; decompose into sub-queries if complex.

    Fast-path: single function → no LLM call, immediate pass-through.
    """
    with get_tracer_span("planner_node"):
        functions_found = state.get("functions_found", [])
        rewritten_query = state.get("rewritten_query") or {}
        query_text = rewritten_query.get("query", "")

        # Deduplicate function names (handles case/whitespace variations from search index)
        seen = set()
        deduped_functions = []
        for fn in functions_found:
            normalized = fn.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                deduped_functions.append(normalized)
        functions_found = deduped_functions

        # ── Fast-path: rewrite_node already decomposed the query ──
        # When query decomposition (Fix #1) produces sub_queries before search,
        # honour them directly — they represent the user's explicit multi-hop intent.
        existing_sub_queries = state.get("sub_queries")
        if existing_sub_queries and len(existing_sub_queries) > 1:
            logger.info(
                "planner: using pre-decomposed sub_queries (%d) from rewrite_node",
                len(existing_sub_queries),
            )
            return {
                "plan_type": "complex",
                "sub_queries": existing_sub_queries,
            }

        # ── Fast-path: single function or missing data → simple ──
        if len(functions_found) <= 1 or not query_text:
            sub_queries = [{"function": functions_found[0], "query": query_text}] if functions_found else []
            return {
                "plan_type": "simple",
                "sub_queries": sub_queries,
            }

        # ── Multiple functions: call LLM for decomposition ──
        try:
            llm_model = get_llm_model("planner")
            user_msg = planner_user_template(query_text, functions_found)
            messages = [
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ]
            result = await _call_planner_llm(messages, llm_model)

            complexity = result.get("complexity", "complex")
            sub_queries = result.get("sub_queries", [])

            # Validate sub_queries structure
            valid_subs = []
            for sq in sub_queries:
                fn = sq.get("function", "").strip()
                q = sq.get("query", "").strip()
                if fn and q and fn in functions_found:
                    valid_subs.append({"function": fn, "query": q})

            # Fallback: if LLM returned nothing valid, create one sub-query per function
            if not valid_subs:
                valid_subs = [{"function": fn, "query": query_text} for fn in functions_found]
                complexity = "complex"

            # Ensure ALL functions_found are represented in sub_queries.
            # search_node already determined these functions have comparable scores
            # (no clear winner), so the planner should not drop any of them.
            covered_fns = {sq["function"] for sq in valid_subs}
            for fn in functions_found:
                if fn not in covered_fns:
                    valid_subs.append({"function": fn, "query": query_text})
                    complexity = "complex"

            # Cap sub-queries to prevent API throttling from too many parallel searches.
            # Keep one sub-query per unique function, prioritising the LLM-decomposed
            # ones (they appear first in valid_subs) over the catch-all fallbacks.
            if len(valid_subs) > MAX_SUB_QUERIES:
                logger.info(
                    "planner: capping sub_queries from %d to %d",
                    len(valid_subs), MAX_SUB_QUERIES,
                )
                # Deduplicate: keep the first (most specific) sub-query per function
                seen_fns: set[str] = set()
                deduped: list[dict] = []
                for sq in valid_subs:
                    if sq["function"] not in seen_fns:
                        seen_fns.add(sq["function"])
                        deduped.append(sq)
                valid_subs = deduped[:MAX_SUB_QUERIES]

            logger.info(
                "planner: complexity=%s sub_queries=%d functions=%s",
                complexity, len(valid_subs), [sq["function"] for sq in valid_subs],
            )

            return {
                "plan_type": complexity,
                "sub_queries": valid_subs,
            }

        except Exception as exc:
            # Fail-open: treat as complex with original query for all functions
            logger.warning("planner: LLM call failed, falling back: %s", exc, exc_info=True)
            fallback_subs = [{"function": fn, "query": query_text} for fn in functions_found]
            return {
                "plan_type": "complex",
                "sub_queries": fallback_subs,
            }
