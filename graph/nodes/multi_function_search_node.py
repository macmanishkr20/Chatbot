"""
Multi-function search node — iteratively searches each candidate function
when a query spans multiple MENA functions, finds the first function with
a valid answer, and routes its results to the generate node for streaming.

Activated when search_node sets needs_multi_search=True (i.e. results came
from multiple functions with no clear score winner).

Flow per function:
  1. Build OData filter for that function
  2. Run unified_search
  3. If results found → call _generate_response (non-streaming) to CHECK
  4. If LLM response starts with [NO_ANSWER] → skip to next function
  5. Otherwise → set events to this function's results and return
     (the generate node handles the actual streaming response)

IMPORTANT — streaming design:
  LangGraph's ``messages`` stream mode captures ALL LLM calls made inside a
  node, including our intermediate _generate_response checks.  To prevent
  raw [NO_ANSWER] responses from leaking to the frontend:
    • This node is NOT in _STREAMABLE_NODES (messages mode is suppressed).
    • Status messages go into ``multi_search_status`` (plain strings).
    • The ``updates`` mode handler in app.py emits them as SSE events.
    • The actual streaming answer is produced by the generate node
      (which IS in _STREAMABLE_NODES) using the winning function's events.
"""
from __future__ import annotations

import asyncio
import logging

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from config import TOP_K
from graph.state import RAGState
from graph.nodes.generate_node import _generate_response
from graph.nodes.search_node import _strip_internal_fields
from prompts._functions import CHIP_TO_SEARCH
from services.search_client import SearchService

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


async def multi_function_search_node(state: RAGState, config: RunnableConfig) -> dict:
    """Iteratively search each candidate function and return the first
    successful answer, emitting status messages for progressive UX."""

    if not state.get("needs_multi_search"):
        return {}

    functions_to_try = state.get("functions_found", [])
    rewritten_query = state.get("rewritten_query")
    embedded_query = state.get("embedded_query")

    if not functions_to_try or not rewritten_query or not embedded_query:
        return {
            "needs_multi_search": False,
            "error_info": {
                "error_code": "NO_QUERY",
                "text": "Missing query or function data for multi-function search.",
            },
        }

    base_filter = rewritten_query.get("filter") or None
    requested_ct = (state.get("content_type") or "qa_pair").strip() or "qa_pair"
    fallback_chain = [requested_ct]
    if requested_ct == "qa_pair":
        fallback_chain.append("document")

    search_service = SearchService()

    # ── Real-time status delivery via asyncio.Queue side-channel ──
    # The queue is created by _stream_graph in app.py and passed via config.
    # Messages pushed here are drained by the stream generator between
    # LangGraph chunks, giving near-real-time delivery to the frontend.
    queue: asyncio.Queue | None = config.get("configurable", {}).get("_deep_search_queue")
    status_log: list[str] = []

    def emit_status(msg: str) -> None:
        """Push status to both the real-time queue and the state log."""
        status_log.append(msg)
        if queue is not None:
            queue.put_nowait(msg)

    fn_names = ", ".join(functions_to_try)
    emit_status(
        f"This query falls under multiple functions ({fn_names}). "
        "Let me search each one for the most relevant answer."
    )

    logger.info(
        "multi_function_search: trying functions %s", functions_to_try,
    )

    # ── Iterate each candidate function ──
    for fn in functions_to_try:
        emit_status(f"Searching in **{fn}** function...")

        # Search with content-type fallback (qa_pair → document)
        results: list = []
        for ct in fallback_chain:
            odata_filter = _build_function_filter(fn, base_filter, ct)
            results = await search_service.unified_search(
                rewritten_query, embedded_query, odata_filter=odata_filter,
            )
            if results:
                break

        if not results:
            emit_status(
                f"No results found under **{fn}** function. "
                "Let me search the next function."
            )
            logger.info("multi_function_search: no results for %s", fn)
            continue

        curated = _strip_internal_fields(results[:TOP_K])

        # ── Generate a response for these results (non-streaming) ──
        try:
            ai_content, prompt_used, citation_map, _ = await _generate_response(
                curated, state, streaming=False,
            )
        except Exception as exc:
            logger.warning(
                "multi_function_search: generation failed for %s: %s",
                fn, exc, exc_info=True,
            )
            emit_status(
                f"Error generating response for {fn}. Trying next function."
            )
            continue

        # ── Check if LLM actually answered ──
        content_stripped = (ai_content or "").strip()
        if content_stripped.startswith("[NO_ANSWER]"):
            emit_status(
                f"No relevant answer found under **{fn}** function. "
                "Let me search the next function."
            )
            logger.info("multi_function_search: [NO_ANSWER] for %s", fn)
            continue

        # ── SUCCESS — pass results to generate node for streaming ──
        emit_status(f"Found answer under **{fn}** function:")

        logger.info("multi_function_search: success with %s", fn)

        return {
            # Don't set messages or ai_content here — the generate node
            # will produce the streaming response using these events.
            "multi_search_status": status_log,
            "events": curated,
            "functions_found": [fn],
            "is_ambiguous": False,
            "needs_multi_search": False,
        }

    # ── All functions exhausted — no answer found ──
    fallback_text = (
        "I searched across multiple functions but wasn't able to find a "
        "specific answer for your query. To help me get you the best result, "
        "could you please select the specific function your question relates to? "
        "This will allow me to search more precisely."
    )
    emit_status(fallback_text)

    logger.info("multi_function_search: exhausted all functions, no answer")

    return {
        "messages": [AIMessage(content=fallback_text)],
        "multi_search_status": status_log,
        "events": [],
        "functions_found": functions_to_try,
        "is_ambiguous": False,
        "needs_multi_search": False,
        "ai_content": fallback_text,
        "error_info": {
            "error_code": "MULTI_SEARCH_EXHAUSTED",
            "text": fallback_text,
        },
    }
