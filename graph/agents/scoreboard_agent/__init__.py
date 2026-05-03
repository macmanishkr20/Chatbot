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
    "Answers structured questions about scoreboards and performance KPIs. "
    "Key metrics include: GTER (Global Total Engagement Revenue), ANSR "
    "(Adjusted Net Standard Revenue), TER (Total Engagement Revenue), "
    "GlobalMargin, GlobalMarginPct, GlobalSales, WeightedPipeline, "
    "EngMargin, EngMarginPct, UtilizationPct, Billing, Collection, AR, "
    "ARReserve, TotalNUI, AgedNUI (above 180/365 days), RevenueDays, "
    "FYTDBacklogTER, TotalBacklogTER, GTERPlanAchievedPct. "
    "Route here for any query mentioning these KPIs or asking about "
    "employee performance rankings, scorecards, plan attainment, "
    "utilization, revenue metrics, or pipeline — NOT for expense "
    "transactions or leave data."
)


register_agent(AgentSpec(
    name="scoreboard_agent",
    description=_DESCRIPTION,
    build_subgraph=lambda store=None, checkpointer=None: build_scoreboard_subgraph(),
    sample_prompts=(
        "Show me the scoreboard in FY26.",
        "Which employee has the highest ANSR?",
        "What is my GTER plan attainment in FY26 P9?",
        "Top 5 employees by utilization this quarter.",
        "Compare my GlobalMargin across the last 3 periods.",
        "Who has the most aged NUI above 365 days?",
    ),
    enabled_by_default=False,
    requires_employee_context=True,
))
