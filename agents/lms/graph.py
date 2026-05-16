"""
LMS sub-graph.

Flow:
    load_memory → lms_classify → lms_fetch → lms_format → persist → summarize
                                                                       ↓
                                                                  save_memory → END

Mirrors RAG's overall outer-shape (load_memory at the top, persist + summarize +
save_memory at the bottom) so conversation history, citation map, and
long-term memory all behave identically.

Safe-node wrappers are used so a backend or LLM failure surfaces a friendly
error rather than crashing the supervisor graph.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph

from core.telemetry import get_tracer_span, record_exception
from agents.lms.state import RAGState
from agents.lms.nodes.classify import lms_classify_node
from agents.lms.nodes.fetch import lms_fetch_node
from agents.lms.nodes.format import lms_format_node
from agents._base.nodes.memory import load_memory_node, save_memory_node
from agents._base.nodes.persist import persist_node
from agents._base.nodes.summarize import summarize_node

logger = logging.getLogger(__name__)

_ERROR_MESSAGE = (
    "I'm sorry, the leave system is temporarily unavailable. "
    "Please try again in a moment."
)


# ── Error-safe node wrappers (parity with rag/graph.py) ──────────────────────

def _safe_node(node_fn):
    """Wrap a node so an unhandled exception becomes a graceful answer."""
    import inspect
    _accepts_config = "config" in inspect.signature(node_fn).parameters
    _is_async = inspect.iscoroutinefunction(node_fn)

    async def _wrapped(state: RAGState, config=None):
        with get_tracer_span(f"node.{node_fn.__name__}"):
            try:
                if _is_async:
                    if _accepts_config:
                        return await node_fn(state, config)
                    return await node_fn(state)
                if _accepts_config:
                    return node_fn(state, config)
                return node_fn(state)
            except Exception as exc:
                logger.error(
                    "LMS node '%s' failed: %s", node_fn.__name__, exc, exc_info=True,
                )
                record_exception(exc, {"node": node_fn.__name__, "agent": "lms"})
                return {
                    "ai_content": _ERROR_MESSAGE,
                    "is_free_form": True,
                    "error_info": {
                        "error_code": "LMS_NODE_ERROR",
                        "text": f"{node_fn.__name__}: {type(exc).__name__}: {exc}",
                    },
                    "messages": [AIMessage(content=_ERROR_MESSAGE)],
                    "events": [],
                }
    _wrapped.__name__ = node_fn.__name__
    return _wrapped


def _soft_safe_node(node_fn):
    """Wrap a node so a failure logs but does not replace ai_content.

    Used for persist / summarize where a failure must not overwrite the
    user-facing answer the format node produced.
    """
    import inspect
    _accepts_config = "config" in inspect.signature(node_fn).parameters
    _is_async = inspect.iscoroutinefunction(node_fn)

    async def _wrapped(state: RAGState, config=None):
        with get_tracer_span(f"node.{node_fn.__name__}"):
            try:
                if _is_async:
                    if _accepts_config:
                        return await node_fn(state, config)
                    return await node_fn(state)
                if _accepts_config:
                    return node_fn(state, config)
                return node_fn(state)
            except Exception as exc:
                logger.error(
                    "LMS node '%s' failed (soft): %s", node_fn.__name__, exc, exc_info=True,
                )
                record_exception(exc, {"node": node_fn.__name__, "agent": "lms"})
                return {}
    _wrapped.__name__ = node_fn.__name__
    return _wrapped


# ── Builder ──────────────────────────────────────────────────────────────────

def build_lms_graph(checkpointer: Any = None, memory_store: Any = None) -> Any:
    """Build and compile the LMS LangGraph sub-graph."""
    graph = StateGraph(RAGState)

    # load_memory / save_memory rely on LangGraph injecting `store` via the
    # function signature — they must be added unwrapped.
    graph.add_node("load_memory", load_memory_node)
    graph.add_node("save_memory", save_memory_node)

    graph.add_node("lms_classify", _safe_node(lms_classify_node))
    graph.add_node("lms_fetch", _safe_node(lms_fetch_node))
    graph.add_node("lms_format", _safe_node(lms_format_node))

    # persist + summarize use the soft wrapper so their failure does not
    # overwrite the user-visible ai_content from lms_format.
    graph.add_node("persist", _soft_safe_node(persist_node))
    graph.add_node("summarize", _soft_safe_node(summarize_node))

    graph.set_entry_point("load_memory")
    graph.add_edge("load_memory", "lms_classify")
    graph.add_edge("lms_classify", "lms_fetch")
    graph.add_edge("lms_fetch", "lms_format")
    graph.add_edge("lms_format", "persist")
    graph.add_edge("persist", "summarize")
    graph.add_edge("summarize", "save_memory")
    graph.add_edge("save_memory", END)

    return graph.compile(checkpointer=checkpointer, store=memory_store)
