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
from typing import Any

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


# ── Conditional Routing ──

def _after_function_gate(state: RAGState) -> str:
    """Short-circuit when the user must (re)select a MENA function."""
    if state.get("requires_function_selection"):
        return "persist"
    return "rewrite"


def _after_search(state: RAGState) -> str:
    """Route after search: parallel multi-function path or generate."""
    if state.get("needs_multi_search"):
        return "planner"
    return "generate"


def _after_synthesize(state: RAGState) -> str:
    """Route after synthesize: persist on exhausted (error_info set), or generate."""
    if state.get("error_info") and not state.get("events"):
        return "persist"
    return "generate"


# ── Graph Builder ──

def build_rag_graph(checkpointer: Any = None, memory_store: Any = None) -> StateGraph:
    """Build and compile the RAG LangGraph StateGraph."""
    graph = StateGraph(RAGState)

    graph.add_node("load_memory", load_memory_node)
    graph.add_node("function_gate", function_gate_node)
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("search", search_node)
    graph.add_node("generate", generate_node)
    graph.add_node("persist", persist_node)
    graph.add_node("summarize", summarize_node)
    graph.add_node("save_memory", save_memory_node)
    graph.add_node("planner", planner_node)
    graph.add_node("parallel_search", parallel_search_node)
    graph.add_node("synthesize", synthesize_node)

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
    graph.add_edge("generate", "persist")
    graph.add_edge("persist", "summarize")
    graph.add_edge("summarize", "save_memory")
    graph.add_edge("save_memory", END)

    return graph.compile(checkpointer=checkpointer, store=memory_store)
