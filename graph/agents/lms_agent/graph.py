"""
LMS agent sub-graph.

Pipeline:
  enrich_context → confirmation_gate → react_loop (bounded ReAct)
                 → persist → save_memory → END

confirmation_gate inspects ``pending_write_action`` (set on the previous
turn when the LLM asked for confirmation before a write):
  * user said yes  → mark user_confirmed_write=True, continue to react_loop
  * user said no   → cancel, route directly to persist
  * ambiguous reply → re-ask, route directly to persist
  * no pending     → fall through to react_loop unchanged
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph.agents.lms_agent.nodes import (
    _after_confirmation_gate,
    confirmation_gate_node,
    enrich_context_node,
    react_loop_node,
)
from graph.agents.lms_agent.state import LMSAgentState
from graph.nodes.memory_node import save_memory_node
from graph.nodes.persist_node import persist_node


def build_lms_subgraph(store=None, checkpointer=None):
    """Compile the LMS sub-graph. ``store`` and ``checkpointer`` are accepted
    for parity with other agent builders; the LMS agent itself doesn't
    currently need cross-session memory (the upstream HR system is the
    source of truth) but the supervisor's compiled checkpointer will handle
    state persistence at the parent level when passed in."""
    g = StateGraph(LMSAgentState)

    g.add_node("enrich_context", enrich_context_node)
    g.add_node("confirmation_gate", confirmation_gate_node)
    g.add_node("react_loop", react_loop_node)
    g.add_node("persist", persist_node)
    g.add_node("save_memory", save_memory_node)

    g.add_edge(START, "enrich_context")
    g.add_edge("enrich_context", "confirmation_gate")
    g.add_conditional_edges(
        "confirmation_gate",
        _after_confirmation_gate,
        {"react_loop": "react_loop", "persist": "persist"},
    )
    g.add_edge("react_loop", "persist")
    g.add_edge("persist", "save_memory")
    g.add_edge("save_memory", END)

    compile_kwargs: dict = {}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer
    if store is not None:
        compile_kwargs["store"] = store
    return g.compile(**compile_kwargs)
