"""
Agent registry — pluggable specialist agents under the Supervisor.

Adding a new agent is a single-file change:

    from graph.agents import AgentSpec, register_agent

    register_agent(AgentSpec(
        name="my_agent",
        description="One-line summary the supervisor LLM uses to decide routing.",
        build_subgraph=lambda store=None: build_my_agent_subgraph(store),
        sample_prompts=[...],
    ))

The supervisor reads ``AgentRegistry.list()`` to populate its routing prompt
and to register sub-graphs as workflow nodes. Disabled agents (via env
flag) are skipped at boot.
"""
from graph.agents.base import (
    AGENT_RESPOND,
    AgentRegistry,
    AgentSpec,
    register_agent,
)

# Side-effect imports — register the built-in agents on package import.
# Each module calls ``register_agent(...)`` at top level.
from graph.agents import rag_agent  # noqa: F401
from graph.agents import expense_agent  # noqa: F401
from graph.agents import scoreboard_agent  # noqa: F401
from graph.agents import lms_agent  # noqa: F401


__all__ = [
    "AGENT_RESPOND",
    "AgentRegistry",
    "AgentSpec",
    "register_agent",
]
