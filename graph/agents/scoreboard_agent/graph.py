"""
Scoreboard agent sub-graph.

Pipeline:
  privacy_gate → understand_query → execute_query → synthesize → persist → save_memory → END
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph.agents.scoreboard_agent.nodes import (
    execute_query_node,
    privacy_gate_node,
    synthesize_node,
    understand_query_node,
)
from graph.agents.scoreboard_agent.state import ScoreboardAgentState
from graph.nodes.memory_node import save_memory_node
from graph.nodes.persist_node import persist_node


def build_scoreboard_subgraph():
    g = StateGraph(ScoreboardAgentState)

    g.add_node("privacy_gate", privacy_gate_node)
    g.add_node("understand_query", understand_query_node)
    g.add_node("execute_query", execute_query_node)
    g.add_node("synthesize", synthesize_node)
    g.add_node("persist", persist_node)
    g.add_node("save_memory", save_memory_node)

    g.add_edge(START, "privacy_gate")
    g.add_edge("privacy_gate", "understand_query")
    g.add_edge("understand_query", "execute_query")
    g.add_edge("execute_query", "synthesize")
    g.add_edge("synthesize", "persist")
    g.add_edge("persist", "save_memory")
    g.add_edge("save_memory", END)

    return g.compile()
