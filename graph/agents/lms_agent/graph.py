"""
LMS agent sub-graph.

Pipeline:
  enrich_context → react_loop (bounded ReAct over the toolbelt)
                 → persist → save_memory → END

The react_loop owns the HITL gate internally: it returns a confirmation
message instead of calling a write tool when ``user_confirmed_write`` is
False. The next user turn (with confirmation) re-enters the agent and
the same tool call proceeds.
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph.agents.lms_agent.nodes import enrich_context_node, react_loop_node
from graph.agents.lms_agent.state import LMSAgentState
from graph.nodes.memory_node import save_memory_node
from graph.nodes.persist_node import persist_node


def build_lms_subgraph(store=None):
    """Compile the LMS sub-graph. ``store`` is accepted for parity with
    other agent builders but the LMS agent doesn't currently need
    cross-session memory — the upstream HR system is the source of truth."""
    g = StateGraph(LMSAgentState)

    g.add_node("enrich_context", enrich_context_node)
    g.add_node("react_loop", react_loop_node)
    g.add_node("persist", persist_node)
    g.add_node("save_memory", save_memory_node)

    g.add_edge(START, "enrich_context")
    g.add_edge("enrich_context", "react_loop")
    g.add_edge("react_loop", "persist")
    g.add_edge("persist", "save_memory")
    g.add_edge("save_memory", END)

    return g.compile()
