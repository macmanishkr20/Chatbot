"""
Synthesize node — merges parallel search results from multiple functions
into a unified events list for the generate node.

Design decisions:
  - Purely programmatic — no LLM call (fast, deterministic).
  - Interleaves results by function, preserving provenance (function field)
    so citations correctly reference their source.
  - If only 1 function returned results, passes through without modification.
  - Handles edge case where no results came back (sets error_info).
"""
from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from graph.state import RAGState
from services.telemetry import get_tracer_span

logger = logging.getLogger(__name__)


async def synthesize_node(state: RAGState) -> dict:
    """Merge parallel_results into a single events list for generate_node.

    Interleaves results by function in round-robin fashion so the LLM
    sees balanced context from each source.
    """
    with get_tracer_span("synthesize_node"):
        parallel_results = state.get("parallel_results") or []

        # Filter to only results that have events
        with_events = [pr for pr in parallel_results if pr.get("events")]

        if not with_events:
            # No results from any function
            fallback_text = (
                "I searched across multiple functions but wasn't able to find a "
                "specific answer for your query. To help me get you the best result, "
                "could you please select the specific function your question relates to? "
                "This will allow me to search more precisely."
            )
            logger.info("synthesize: no results from any function")
            return {
                "events": [],
                "messages": [AIMessage(content=fallback_text)],
                "ai_content": fallback_text,
                "error_info": {
                    "error_code": "MULTI_SEARCH_EXHAUSTED",
                    "text": fallback_text,
                },
                "needs_multi_search": False,
            }

        # ── Single function with results — pass through directly ──
        if len(with_events) == 1:
            result = with_events[0]
            logger.info(
                "synthesize: single function with results: %s (%d events)",
                result["function"], len(result["events"]),
            )
            return {
                "events": result["events"],
                "functions_found": [result["function"]],
                "needs_multi_search": False,
            }

        # ── Multiple functions — interleave events (round-robin) ──
        merged: list = []
        max_len = max(len(pr["events"]) for pr in with_events)

        for i in range(max_len):
            for pr in with_events:
                if i < len(pr["events"]):
                    merged.append(pr["events"][i])

        # Deduplicate by content (same content from different functions = keep first)
        seen_content: set = set()
        deduped: list = []
        for event in merged:
            content_key = (event.get("content", ""))[:200]
            if content_key and content_key in seen_content:
                continue
            seen_content.add(content_key)
            deduped.append(event)

        functions_with_results = [pr["function"] for pr in with_events]
        logger.info(
            "synthesize: merged %d events from %d functions: %s",
            len(deduped), len(with_events), functions_with_results,
        )

        return {
            "events": deduped,
            "functions_found": functions_with_results,
            "needs_multi_search": False,
        }
