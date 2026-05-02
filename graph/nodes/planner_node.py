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

from config import PLANNER_MAX_TOKENS, PLANNER_TEMPERATURE
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
