"""
RAG StateGraph definition.

Flow:
  load_memory → function_gate → rewrite → search
    → (multi-function? → planner → parallel_search → synthesize)
    → generate → persist → summarize → save_memory → END

  The generation model self-assesses relevance via [NO_ANSWER] (Claude-style)
  — no separate grader step.

Checkpointer: AsyncAzureSQLCheckpointSaver — per-thread conversation state.
Store:        AzureSQLStore               — cross-thread long-term memory.
"""
import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph

from graph.state import RAGState
from graph.nodes.memory_node import load_memory_node, save_memory_node
from graph.nodes.rewrite_node import rewrite_node
from graph.nodes.search_node import search_node
from graph.nodes.generate_node import generate_node
from graph.nodes.persist_node import persist_node
from graph.nodes.function_gate_node import function_gate_node
from graph.nodes.planner_node import planner_node
from graph.nodes.parallel_search_node import parallel_search_node
from graph.nodes.synthesize_node import synthesize_node
from graph.nodes.summarize_node import summarize_node

logger = logging.getLogger(__name__)

_ERROR_MESSAGE = (
    "I'm sorry, something went wrong while processing your request. "
    "Please try again."
)


# ── Error-safe node wrapper ──

def _safe_node(node_fn):
    """Wrap a graph node with error handling so unhandled exceptions
    don't crash the graph. Routes to persist with a user-friendly message."""
    import inspect
    _accepts_config = "config" in inspect.signature(node_fn).parameters

    async def _wrapped(state: RAGState, config=None):
        try:
            if _accepts_config:
                return await node_fn(state, config)
            return await node_fn(state)
        except Exception as exc:
            logger.error(
                "Node '%s' failed: %s", node_fn.__name__, exc, exc_info=True,
            )
            return {
                "ai_content": _ERROR_MESSAGE,
                "is_free_form": True,
                "error_info": {
                    "error_code": "NODE_ERROR",
                    "text": f"{node_fn.__name__}: {type(exc).__name__}: {exc}",
                },
                "messages": [AIMessage(content=_ERROR_MESSAGE)],
                "events": [],
            }
    _wrapped.__name__ = node_fn.__name__
    return _wrapped


# ── Conditional Routing ──

def _after_function_gate(state: RAGState) -> str:
    """Short-circuit when the user must (re)select a MENA function."""
    if state.get("requires_function_selection"):
        return "persist"
    return "rewrite"


def _after_search(state: RAGState) -> str:
    """Route after search: error → persist, parallel multi-function → planner, else generate."""
    if state.get("error_info") and state.get("ai_content"):
        return "persist"
    if state.get("needs_multi_search"):
        return "planner"
    return "generate"


def _after_synthesize(state: RAGState) -> str:
    """Route after synthesize: persist on exhausted (error_info set), or generate."""
    if state.get("error_info") and not state.get("events"):
        return "persist"
    return "generate"


def _after_generate(state: RAGState) -> str:
    """Route after generate: retry with qa_pair if document search didn't answer."""
    if state.get("needs_doc_fallback"):
        return "set_doc_fallback"
    return "persist"


def _set_doc_fallback(state: RAGState) -> dict:
    """Switch content_type to qa_pair and prevent further fallback loops."""
    return {
        "content_type": "qa_pair",
        "doc_fallback_attempted": True,
        "needs_doc_fallback": False,
    }


# ── Graph Builder ──

def build_rag_graph(checkpointer: Any = None, memory_store: Any = None) -> StateGraph:
    """Build and compile the RAG LangGraph StateGraph."""
    graph = StateGraph(RAGState)

    graph.add_node("load_memory", load_memory_node)
    graph.add_node("function_gate", function_gate_node)
    graph.add_node("rewrite", _safe_node(rewrite_node))
    graph.add_node("search", _safe_node(search_node))
    graph.add_node("generate", _safe_node(generate_node))
    graph.add_node("persist", persist_node)
    graph.add_node("summarize", summarize_node)
    graph.add_node("save_memory", save_memory_node)
    graph.add_node("planner", _safe_node(planner_node))
    graph.add_node("parallel_search", _safe_node(parallel_search_node))
    graph.add_node("synthesize", _safe_node(synthesize_node))
    graph.add_node("set_doc_fallback", _set_doc_fallback)

    graph.set_entry_point("load_memory")

    graph.add_edge("load_memory", "function_gate")
    graph.add_conditional_edges(
        "function_gate",
        _after_function_gate,
        {
            "persist": "persist",
            "rewrite": "rewrite",
        },
    )
    graph.add_edge("rewrite", "search")
    graph.add_conditional_edges(
        "search",
        _after_search,
        {
            "generate": "generate",
            "planner": "planner",
            "persist": "persist",
        },
    )
    # ── Parallel multi-function path ──
    graph.add_edge("planner", "parallel_search")
    graph.add_edge("parallel_search", "synthesize")
    graph.add_conditional_edges(
        "synthesize",
        _after_synthesize,
        {
            "persist": "persist",
            "generate": "generate",
        },
    )
    # ── Common path ──
    graph.add_conditional_edges(
        "generate",
        _after_generate,
        {
            "set_doc_fallback": "set_doc_fallback",
            "persist": "persist",
        },
    )
    graph.add_edge("set_doc_fallback", "search")
    graph.add_edge("persist", "summarize")
    graph.add_edge("summarize", "save_memory")
    graph.add_edge("save_memory", END)

    return graph.compile(checkpointer=checkpointer, store=memory_store)
