"""
RAG agent — the original document-retrieval pipeline, registered through
the AgentRegistry so the supervisor can discover it dynamically.
"""
from __future__ import annotations

from graph.agents.base import AgentSpec, register_agent
from graph.rag_graph import build_rag_graph


_RAG_DESCRIPTION = (
    "Handles all knowledge-base retrieval — policy lookups, process "
    "guidance, function-specific procedures, document-grounded answers, "
    "and any question that needs information from the indexed corpus. "
    "Route here whenever the user asks WHAT, HOW, WHY, or WHO about EY "
    "MENA functions, policies, services, or compliance rules."
)


def _build(store=None, checkpointer=None):
    """Compile the RAG sub-graph. Called once during supervisor compilation.

    Note: the RAG sub-graph does not need its own checkpointer — the parent
    supervisor's checkpointer captures state across the whole flow.
    """
    return build_rag_graph(checkpointer=checkpointer, memory_store=store)


register_agent(AgentSpec(
    name="rag_graph",
    description=_RAG_DESCRIPTION,
    build_subgraph=_build,
    sample_prompts=(
        "What are the Finance function policies?",
        "How do I submit a BRIDGE request?",
        "Where can I access the GCO templates?",
        "What is the internal transfer process?",
    ),
    enabled_by_default=True,
))
