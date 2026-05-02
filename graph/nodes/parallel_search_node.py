"""
Parallel search node — executes function searches concurrently via asyncio.gather().

Replaces the sequential multi_function_search_node with true parallelism.
Each function's search runs independently; results are collected and passed
to synthesize_node for merging.

Design decisions:
  - Uses asyncio.gather(return_exceptions=True) so one timeout/failure
    doesn't block others.
  - Real-time status via asyncio.Queue (same pattern as old multi_function_search).
  - NOT in _STREAMABLE_NODES — status goes through updates mode only.
  - Does NOT call _generate_response for validation (unlike old sequential node).
    The grader_node downstream handles relevance checking.
  - Timeout per function is configurable via PARALLEL_SEARCH_TIMEOUT.
"""
from __future__ import annotations

import asyncio
import logging

from langchain_core.runnables import RunnableConfig

from config import PARALLEL_SEARCH_TIMEOUT, TOP_K
from graph.state import RAGState
from graph.nodes.search_node import _strip_internal_fields
from prompts._functions import CHIP_TO_SEARCH
from services.search_client import SearchService
from services.telemetry import get_tracer_span

logger = logging.getLogger(__name__)


def _build_function_filter(
    fn: str, base_filter: str | None, content_type: str,
) -> str:
    """Build an OData filter scoped to a single function and content type."""
    search_fn = CHIP_TO_SEARCH.get(fn, fn)
    fn_clause = f"function eq '{search_fn}'"
    ct_clause = f"content_type eq '{content_type}'"

    if base_filter:
        return f"({base_filter}) and ({fn_clause}) and ({ct_clause})"
    return f"({fn_clause}) and ({ct_clause})"


async def _search_single_function(
    fn: str,
    sub_query: str,
    rewritten_query: dict,
    embedded_query: list,
    base_filter: str | None,
    fallback_chain: list[str],
    search_service: SearchService,
) -> dict:
    """Search a single function with content-type fallback. Returns result dict."""
    # Override query text with the sub-query from planner
    query_override = {**rewritten_query, "query": sub_query}

    for ct in fallback_chain:
        odata_filter = _build_function_filter(fn, base_filter, ct)
        results = await search_service.unified_search(
            query_override, embedded_query, odata_filter=odata_filter,
        )
        if results:
            curated = _strip_internal_fields(results[:TOP_K])
            return {"function": fn, "events": curated, "query": sub_query}

    return {"function": fn, "events": [], "query": sub_query}


async def parallel_search_node(state: RAGState, config: RunnableConfig) -> dict:
    """Execute all function searches in parallel via asyncio.gather().

    Emits real-time status messages via asyncio.Queue for progressive UX.
    """
    with get_tracer_span("parallel_search_node"):
        sub_queries = state.get("sub_queries") or []
        rewritten_query = state.get("rewritten_query") or {}
        embedded_query = state.get("embedded_query")

        if not sub_queries or not rewritten_query or not embedded_query:
            return {
                "parallel_results": [],
                "error_info": {
                    "error_code": "NO_QUERY",
                    "text": "Missing query or function data for parallel search.",
                },
            }

        base_filter = rewritten_query.get("filter") or None
        requested_ct = (state.get("content_type") or "qa_pair").strip() or "qa_pair"
        fallback_chain = [requested_ct]
        if requested_ct == "qa_pair":
            fallback_chain.append("document")

        search_service = SearchService()
        timeout_sec = PARALLEL_SEARCH_TIMEOUT / 1000.0  # Convert ms to seconds

        # ── Real-time status delivery via asyncio.Queue ──
        queue: asyncio.Queue | None = config.get("configurable", {}).get("_deep_search_queue")
        status_log: list[str] = []

        def emit_status(msg: str) -> None:
            status_log.append(msg)
            if queue is not None:
                queue.put_nowait(msg)

        fn_names = ", ".join(sq["function"] for sq in sub_queries)
        if len(sub_queries) == 1:
            emit_status(
                f"Searching in **{fn_names}** for the most relevant answer."
            )
        else:
            emit_status(
                f"This query spans multiple functions ({fn_names}). "
                "Searching all in parallel for comprehensive results."
            )

        # ── Launch parallel searches ──
        tasks = []
        for sq in sub_queries:
            fn = sq["function"]
            sub_query = sq.get("query", rewritten_query.get("query", ""))
            emit_status(f"Searching in **{fn}**...")

            task = asyncio.wait_for(
                _search_single_function(
                    fn=fn,
                    sub_query=sub_query,
                    rewritten_query=rewritten_query,
                    embedded_query=embedded_query,
                    base_filter=base_filter,
                    fallback_chain=fallback_chain,
                    search_service=search_service,
                ),
                timeout=timeout_sec,
            )
            tasks.append(task)

        # Execute all searches concurrently
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # ── Process results ──
        parallel_results: list[dict] = []
        for i, result in enumerate(raw_results):
            fn = sub_queries[i]["function"]
            if isinstance(result, Exception):
                logger.warning(
                    "parallel_search: %s failed: %s", fn, result, exc_info=True,
                )
                emit_status(f"Search timed out or failed for **{fn}**.")
                parallel_results.append({"function": fn, "events": [], "query": sub_queries[i].get("query", "")})
            else:
                events = result.get("events", [])
                if events:
                    emit_status(f"Found {len(events)} result(s) in **{fn}**.")
                else:
                    emit_status(f"No results found in **{fn}**.")
                parallel_results.append(result)

        successful = [pr for pr in parallel_results if pr.get("events")]
        logger.info(
            "parallel_search: %d/%d functions returned results",
            len(successful), len(parallel_results),
        )

        if len(successful) > 1:
            emit_status("Combining results from all functions...")

        return {
            "parallel_results": parallel_results,
            "multi_search_status": status_log,
        }
