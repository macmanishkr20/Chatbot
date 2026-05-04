"""
Expense agent sub-graph — analytical Q&A over the UserExpenses fact table.

Pipeline:
  resolve_role     (AgentUserRoles → role + scope)
    → understand_query (LLM → typed QueryPlan)
    → execute_query    (deterministic compile + DB.fetchall + RLS)
    → synthesize       (LLM narrates rows; emits AIMessage)
    → persist          (chat-history record via existing persist_node)
    → save_memory
    → END

Errors at any node short-circuit to synthesize, which produces a polite
fallback message instead of crashing the supervisor.
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph.agents.expense_agent.nodes import (
    execute_query_node,
    resolve_role_node,
    synthesize_node,
    understand_query_node,
)
from graph.agents.expense_agent.state import ExpenseAgentState
from graph.nodes.memory_node import save_memory_node
from graph.nodes.persist_node import persist_node


def build_expense_subgraph(store=None, checkpointer=None):
    """Compile the expense agent sub-graph.

    ``store`` and ``checkpointer`` are forwarded to ``g.compile`` when
    provided (parity with other agent builders). Either may be omitted —
    LangGraph compiles fine without them.
    """
    g = StateGraph(ExpenseAgentState)

    g.add_node("resolve_role", resolve_role_node)
    g.add_node("understand_query", understand_query_node)
    g.add_node("execute_query", execute_query_node)
    g.add_node("synthesize", synthesize_node)
    g.add_node("persist", persist_node)
    g.add_node("save_memory", save_memory_node)

    g.add_edge(START, "resolve_role")
    g.add_edge("resolve_role", "understand_query")
    g.add_edge("understand_query", "execute_query")
    g.add_edge("execute_query", "synthesize")
    g.add_edge("synthesize", "persist")
    g.add_edge("persist", "save_memory")
    g.add_edge("save_memory", END)

    compile_kwargs: dict = {}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer
    if store is not None:
        compile_kwargs["store"] = store
    return g.compile(**compile_kwargs)
