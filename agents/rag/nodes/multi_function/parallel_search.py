"""
Parallel search node — executes function searches concurrently via asyncio.gather().

Each function's search runs independently using SearchService.search_with_retry();
results are collected and passed to synthesize_node for merging.

Design decisions:
  - Uses asyncio.gather(return_exceptions=True) so one timeout/failure
    doesn't block others.
  - Real-time status via asyncio.Queue for progressive UX.
  - NOT in _STREAMABLE_NODES — status goes through updates mode only.
  - Delegates retry/fallback to SearchService.search_with_retry(skip_last_resort=True)
    to preserve function scoping.
  - Timeout per function is configurable via PARALLEL_SEARCH_TIMEOUT.
"""
from __future__ import annotations

import asyncio
import logging

from langchain_core.runnables import RunnableConfig

from core.config import MAX_PARALLEL_SEARCHES, PARALLEL_SEARCH_TIMEOUT, TOP_K
from agents.rag.state import RAGState
from agents.rag.nodes.search import _embed_query, _strip_internal_fields, _with_content_type
from agents.rag.prompts.functions import CHIP_TO_SEARCH
from infrastructure.azure.search.client import SearchService
from core.telemetry import get_tracer_span

logger = logging.getLogger(__name__)


async def _search_single_function(
    fn: str,
    sub_query: str,
    rewritten_query: dict,
    base_filter: str | None,
    content_type: str,
    search_service: SearchService,
    semaphore: asyncio.Semaphore,
) -> dict:
    """Search a single function with content-type fallback chain.

    Acquires a semaphore slot before making any API call to prevent
    concurrent request throttling from Azure Search / OpenAI.
    """
    try:
        search_fn = CHIP_TO_SEARCH.get(fn, fn)
        fn_clause = f"function eq '{search_fn}'"
        scoped_filter = f"({base_filter}) and ({fn_clause})" if base_filter else fn_clause

        query_override = {**rewritten_query, "query": sub_query}

        # Embed the sub-query — semaphore limits concurrent OpenAI calls
        async with semaphore:
            embedded_query = await _embed_query(sub_query)
        if not embedded_query:
            return {"function": fn, "events": [], "query": sub_query}

        # Search — semaphore limits concurrent Azure Search calls
        async with semaphore:
            odata_filter = _with_content_type(scoped_filter, content_type)
            all_results = await search_service.unified_search(
                query_override, embedded_query, odata_filter=odata_filter
            )

        # Fallback to qa_pair if document returned nothing
        if not all_results and content_type == "document":
            async with semaphore:
                qa_filter = _with_content_type(scoped_filter, "qa_pair")
                all_results = await search_service.unified_search(
                    query_override, embedded_query, odata_filter=qa_filter
                )

        curated = _strip_internal_fields(all_results[:TOP_K])
        return {"function": fn, "events": curated, "query": sub_query}
    except Exception as exc:
        logger.warning("_search_single_function(%s) failed: %s", fn, exc, exc_info=True)
        return {"function": fn, "events": [], "query": sub_query}


async def parallel_search_node(state: RAGState, config: RunnableConfig) -> dict:
    """Execute all function searches in parallel via asyncio.gather().

    Emits real-time status messages via asyncio.Queue for progressive UX.
    """
    with get_tracer_span("parallel_search_node"):
        sub_queries = state.get("sub_queries") or []
        rewritten_query = state.get("rewritten_query") or {}

        if not sub_queries or not rewritten_query:
            return {
                "parallel_results": [],
                "error_info": {
                    "error_code": "NO_QUERY",
                    "text": "Missing query or function data for parallel search.",
                },
            }

        base_filter = rewritten_query.get("filter") or None
        requested_ct = (state.get("content_type") or "document").strip() or "document"

        search_service = SearchService()
        timeout_sec = PARALLEL_SEARCH_TIMEOUT / 1000.0

        # Semaphore limits concurrent API calls to Azure Search / OpenAI
        # to prevent throttling (429 errors) when many functions are searched.
        semaphore = asyncio.Semaphore(MAX_PARALLEL_SEARCHES)

        # ── Real-time status delivery via asyncio.Queue ──
        queue: asyncio.Queue | None = config.get("configurable", {}).get("_deep_search_queue")
        status_log: list[str] = []

        def emit_status(msg: str) -> None:
            status_log.append(msg)
            if queue is not None:
                queue.put_nowait(msg)

        fn_names = ", ".join(sq["function"] for sq in sub_queries)
        if len(sub_queries) == 1:
            emit_status(f"Searching in **{fn_names}** for the most relevant answer.")
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
                    base_filter=base_filter,
                    content_type=requested_ct,
                    search_service=search_service,
                    semaphore=semaphore,
                ),
                timeout=timeout_sec,
            )
            tasks.append(task)

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
