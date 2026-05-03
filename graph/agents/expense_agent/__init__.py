"""
Expense agent — answers natural-language questions over expense data
stored in Azure SQL.

Sub-graph (filled in during Phase 2):
  understand_query (LLM extracts intent + filters + group_by + aggregate)
    → resolve_values (vocabulary / fuzzy lookup, optional)
    → compile_predicate (deterministic predicate-tree → parameterised SQL)
    → execute (read-only SQL, row-cap, query timeout, RLS injection)
    → synthesize (LLM narrates results, picks tabular / chart / number form)
    → persist
"""
from __future__ import annotations

from graph.agents.base import AgentSpec, register_agent
from graph.agents.expense_agent.graph import build_expense_subgraph


_DESCRIPTION = (
    "Answers structured questions about user / team expenses — totals, "
    "filters, comparisons, rankings ('show me expenses in FY26', 'highest "
    "expense this quarter', 'how many expenses under 100', 'travel "
    "spending by month'). Route here ONLY for numeric / aggregate / filter "
    "questions over expense data — narrative how-to questions about "
    "expense policy go to rag_graph instead."
)


register_agent(AgentSpec(
    name="expense_agent",
    description=_DESCRIPTION,
    build_subgraph=lambda store=None, checkpointer=None: build_expense_subgraph(),
    sample_prompts=(
        "Show me my expenses in FY26.",
        "Which is the highest expense in FY26?",
        "How many expenses are less than 100?",
        "Total travel spending last quarter.",
    ),
    # OFF by default — flip ENABLE_EXPENSE_AGENT_AGENT=true after data load.
    enabled_by_default=False,
    requires_employee_context=True,
))
