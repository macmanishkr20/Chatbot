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


def _build(store=None, checkpointer=None):
    # Lazy import — keeps services.data_db / services.text_to_predicate
    # out of the import-time graph (no DB/KV hit until first use).
    from graph.agents.expense_agent.graph import build_expense_subgraph
    return build_expense_subgraph(store=store, checkpointer=checkpointer)


_DESCRIPTION = (
    "Answers structured questions about expense transactions — totals, "
    "filters, comparisons, rankings over the UserExpenses table. Covers: "
    "expense amounts, reimbursement status, expense types (Air Travel, "
    "Hotel, Meals, etc.), vendors, approval status, countries/cities of "
    "purchase, report details, engagement codes. "
    "Route here for: 'show me expenses in FY26', 'highest expense this "
    "quarter', 'how many expenses under 100', 'travel spending by month', "
    "'expenses in Bahrain'. "
    "Do NOT route here for performance KPIs (ANSR, GTER, Utilization, "
    "Margin, NUI, Billing, Collection, pipeline) — those go to "
    "scoreboard_agent. Narrative policy questions go to rag_graph."
)


register_agent(AgentSpec(
    name="expense_agent",
    description=_DESCRIPTION,
    build_subgraph=_build,
    sample_prompts=(
        "Show me my expenses in FY26.",
        "Which is the highest expense in FY26?",
        "How many expenses are less than 100?",
        "Total travel spending last quarter.",
    ),
    # OFF by default — flip ENABLE_EXPENSE=true after data load.
    enabled_by_default=False,
    requires_employee_context=True,
))
