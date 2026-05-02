"""
RAG StateGraph definition.

Flow:
  load_memory → rewrite → embed → search
    → (ambiguous/empty? → persist → save_memory → END)
    → (multi-function? → planner → parallel_search → synthesize → grader → generate → persist → save_memory → END)
    → grader → generate → persist → save_memory → END

Checkpointer: AsyncAzureSQLCheckpointSaver — per-thread conversation state.
Store:        AzureSQLStore               — cross-thread long-term memory.
"""
from typing import Any

from langgraph.graph import END, StateGraph

from graph.state import RAGState
from graph.nodes.memory_node import load_memory_node, save_memory_node
from graph.nodes.rewrite_node import rewrite_node
from graph.nodes.embed_node import embed_node
from graph.nodes.search_node import search_node
from graph.nodes.grader_node import grader_node
from graph.nodes.generate_node import generate_node
from graph.nodes.persist_node import persist_node
from graph.nodes.function_gate_node import function_gate_node
from graph.nodes.planner_node import planner_node
from graph.nodes.parallel_search_node import parallel_search_node
from graph.nodes.synthesize_node import synthesize_node


# ── Conditional Routing ──

def _after_function_gate(state: RAGState) -> str:
    """Short-circuit when the user must (re)select a MENA function."""
    if state.get("requires_function_selection"):
        return "persist"
    return "rewrite"


def _after_search(state: RAGState) -> str:
    """Route after search: parallel multi-function path, short-circuit on empty, or grader."""
    if state.get("needs_multi_search"):
        return "planner"
    if state.get("error_info") and not state.get("events"):
        return "persist"
    return "grader"


def _after_synthesize(state: RAGState) -> str:
    """Route after synthesize: persist on exhausted (error_info set), or grader."""
    if state.get("error_info") and not state.get("events"):
        return "persist"
    return "grader"


# ── Graph Builder ──

def build_rag_graph(checkpointer: Any = None, memory_store: Any = None) -> StateGraph:
    """Build and compile the RAG LangGraph StateGraph."""
    graph = StateGraph(RAGState)

    graph.add_node("load_memory", load_memory_node)
    graph.add_node("function_gate", function_gate_node)
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("embed", embed_node)
    graph.add_node("search", search_node)
    graph.add_node("grader", grader_node)
    graph.add_node("generate", generate_node)
    graph.add_node("persist", persist_node)
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
    graph.add_edge("rewrite", "embed")
    graph.add_edge("embed", "search")
    graph.add_conditional_edges(
        "search",
        _after_search,
        {
            "persist": "persist",
            "grader": "grader",
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
            "grader": "grader",
        },
    )
    # ── Common path ──
    graph.add_edge("grader", "generate")
    graph.add_edge("generate", "persist")
    graph.add_edge("persist", "save_memory")
    graph.add_edge("save_memory", END)

    return graph.compile(checkpointer=checkpointer, store=memory_store)
