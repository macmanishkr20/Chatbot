"""
RAG StateGraph definition.

Flow:
  load_memory → rewrite → embed → search
    → (ambiguous/empty? → persist → save_memory → END)
    → generate → persist → save_memory → END

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
from graph.nodes.generate_node import generate_node
from graph.nodes.persist_node import persist_node


# ── Conditional Routing ──

def _after_search(state: RAGState) -> str:
    """Route after search: short-circuit on ambiguity or empty results with error."""
    if state.get("is_ambiguous"):
        return "persist"
    if state.get("error_info") and not state.get("events"):
        return "persist"
    return "generate"


# ── Graph Builder ──

def build_rag_graph(checkpointer: Any = None, memory_store: Any = None) -> StateGraph:
    """Build and compile the RAG LangGraph StateGraph."""
    graph = StateGraph(RAGState)

    graph.add_node("load_memory", load_memory_node)
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("embed", embed_node)
    graph.add_node("search", search_node)
    graph.add_node("generate", generate_node)
    graph.add_node("persist", persist_node)
    graph.add_node("save_memory", save_memory_node)

    graph.set_entry_point("load_memory")

    graph.add_edge("load_memory", "rewrite")
    graph.add_edge("rewrite", "embed")
    graph.add_edge("embed", "search")
    graph.add_conditional_edges(
        "search",
        _after_search,
        {
            "persist": "persist",
            "generate": "generate",
        },
    )
    graph.add_edge("generate", "persist")
    graph.add_edge("persist", "save_memory")
    graph.add_edge("save_memory", END)

    return graph.compile(checkpointer=checkpointer, store=memory_store)
