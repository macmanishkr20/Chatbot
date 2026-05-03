"""
Expense agent sub-graph — analytical Q&A over the Expenses fact table.

Pipeline:
  understand_query (LLM → typed QueryPlan)
    → execute_query (deterministic compile + DB.fetchall + RLS)
    → synthesize    (LLM narrates rows; emits AIMessage)
    → persist       (chat-history record via existing persist_node)
    → save_memory
    → END

Errors at any node short-circuit to synthesize, which produces a polite
fallback message instead of crashing the supervisor.
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph.agents.expense_agent.nodes import (
    execute_query_node,
    synthesize_node,
    understand_query_node,
)
from graph.agents.expense_agent.state import ExpenseAgentState
from graph.nodes.memory_node import save_memory_node
from graph.nodes.persist_node import persist_node


def build_expense_subgraph():
    """Compile the expense agent sub-graph."""
    g = StateGraph(ExpenseAgentState)

    g.add_node("understand_query", understand_query_node)
    g.add_node("execute_query", execute_query_node)
    g.add_node("synthesize", synthesize_node)
    g.add_node("persist", persist_node)
    g.add_node("save_memory", save_memory_node)

    g.add_edge(START, "understand_query")
    g.add_edge("understand_query", "execute_query")
    g.add_edge("execute_query", "synthesize")
    g.add_edge("synthesize", "persist")
    g.add_edge("persist", "save_memory")
    g.add_edge("save_memory", END)

    return g.compile()
