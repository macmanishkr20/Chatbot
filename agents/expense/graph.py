"""
Expense sub-graph.

    load_memory → expense_planner → expense_executor → expense_format
                                                            ↓
                                                        persist → summarize → save_memory → END

Same outer shape as RAG and LMS so the rest of the system (checkpointer,
conversation history, summarization, telemetry) just works.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph

from agents._base.nodes.memory import load_memory_node, save_memory_node
from agents._base.nodes.persist import persist_node
from agents._base.nodes.summarize import summarize_node
from agents.expense.nodes.executor import expense_executor_node
from agents.expense.nodes.format import expense_format_node
from agents.expense.nodes.planner import expense_planner_node
from agents.rag.state import RAGState
from core.telemetry import get_tracer_span, record_exception

logger = logging.getLogger(__name__)

_ERROR_MESSAGE = (
    "I'm sorry, the expense system is temporarily unavailable. "
    "Please try again in a moment."
)


# ── Error-safe node wrappers (parity with rag/graph.py + lms/graph.py) ────────

def _safe_node(node_fn):
    _accepts_config = "config" in inspect.signature(node_fn).parameters
    _is_async = inspect.iscoroutinefunction(node_fn)

    async def _wrapped(state: RAGState, config=None):
        with get_tracer_span(f"node.{node_fn.__name__}"):
            try:
                if _is_async:
                    return await (node_fn(state, config) if _accepts_config else node_fn(state))
                return node_fn(state, config) if _accepts_config else node_fn(state)
            except Exception as exc:
                logger.error(
                    "Expense node '%s' failed: %s", node_fn.__name__, exc, exc_info=True,
                )
                record_exception(exc, {"node": node_fn.__name__, "agent": "expense"})
                return {
                    "ai_content": _ERROR_MESSAGE,
                    "is_free_form": True,
                    "error_info": {
                        "error_code": "EXPENSE_NODE_ERROR",
                        "text": f"{node_fn.__name__}: {type(exc).__name__}: {exc}",
                    },
                    "messages": [AIMessage(content=_ERROR_MESSAGE)],
                    "events": [],
                }
    _wrapped.__name__ = node_fn.__name__
    return _wrapped


def _soft_safe_node(node_fn):
    _accepts_config = "config" in inspect.signature(node_fn).parameters
    _is_async = inspect.iscoroutinefunction(node_fn)

    async def _wrapped(state: RAGState, config=None):
        with get_tracer_span(f"node.{node_fn.__name__}"):
            try:
                if _is_async:
                    return await (node_fn(state, config) if _accepts_config else node_fn(state))
                return node_fn(state, config) if _accepts_config else node_fn(state)
            except Exception as exc:
                logger.error(
                    "Expense node '%s' failed (soft): %s", node_fn.__name__, exc, exc_info=True,
                )
                record_exception(exc, {"node": node_fn.__name__, "agent": "expense"})
                return {}
    _wrapped.__name__ = node_fn.__name__
    return _wrapped


def build_expense_graph(checkpointer: Any = None, memory_store: Any = None) -> Any:
    """Build and compile the Expense LangGraph sub-graph."""
    graph = StateGraph(RAGState)

    graph.add_node("load_memory", load_memory_node)
    graph.add_node("save_memory", save_memory_node)
    graph.add_node("expense_planner", _safe_node(expense_planner_node))
    graph.add_node("expense_executor", _safe_node(expense_executor_node))
    graph.add_node("expense_format", _safe_node(expense_format_node))
    graph.add_node("persist", _soft_safe_node(persist_node))
    graph.add_node("summarize", _soft_safe_node(summarize_node))

    graph.set_entry_point("load_memory")
    graph.add_edge("load_memory", "expense_planner")
    graph.add_edge("expense_planner", "expense_executor")
    graph.add_edge("expense_executor", "expense_format")
    graph.add_edge("expense_format", "persist")
    graph.add_edge("persist", "summarize")
    graph.add_edge("summarize", "save_memory")
    graph.add_edge("save_memory", END)

    return graph.compile(checkpointer=checkpointer, store=memory_store)
