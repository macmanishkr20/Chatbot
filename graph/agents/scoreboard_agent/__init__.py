"""
Scoreboard agent — answers natural-language questions over employee
performance scoreboards stored in Azure SQL.

Reuses the shared text-to-predicate-tree compiler from
``services.text_to_predicate``. A privacy gate enforces visibility:
employee → self only; manager → team; HR/admin → all.
"""
from __future__ import annotations

from graph.agents.base import AgentSpec, register_agent
from graph.agents.scoreboard_agent.graph import build_scoreboard_subgraph


_DESCRIPTION = (
    "Answers structured questions about scoreboards / performance metrics "
    "('show me the scoreboard in FY26', 'highest scoreboard FY26', 'which "
    "employee has the highest scoreboard'). Route here ONLY for numeric / "
    "aggregate / ranking questions over scoreboard data — narrative "
    "questions about how scoring works go to rag_graph instead."
)


register_agent(AgentSpec(
    name="scoreboard_agent",
    description=_DESCRIPTION,
    build_subgraph=lambda store=None, checkpointer=None: build_scoreboard_subgraph(),
    sample_prompts=(
        "Show me the scoreboard in FY26.",
        "Which is the highest scoreboard in FY26?",
        "Which employee has the highest scoreboard?",
        "Compare my scoreboard to last quarter.",
    ),
    enabled_by_default=False,
    requires_employee_context=True,
))
