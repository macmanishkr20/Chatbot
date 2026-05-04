"""
LMS agent — leave-management questions answered via 3rd-party HR APIs
(no local DB). Implemented as a ReAct loop with a typed toolbelt.

Sub-graph (Phase 4):
  enrich_context (employee_id, location, current_date, timezone) →
    react_agent (loop: think → tool → observe → repeat) →
      [ get_leave_balance | get_holiday_calendar | get_team_calendar
      | apply_leave (HITL) | cancel_leave (HITL)
      | recommend_leave_window ] →
    synthesize → persist → save_memory → END
"""
from __future__ import annotations

from graph.agents.base import AgentSpec, register_agent


def _build(store=None, checkpointer=None):
    # Lazy import: keeps service modules (lms_client, etc.) out of the
    # import-time graph so registration doesn't trigger network/KV access.
    from graph.agents.lms_agent.graph import build_lms_subgraph
    return build_lms_subgraph(store=store, checkpointer=checkpointer)


_DESCRIPTION = (
    "Handles leave / time-off questions and operations — checking leave "
    "balance, viewing pending requests, applying or cancelling leave, "
    "looking up holidays for the user's location, and recommending "
    "optimal leave windows. Always location-aware and date-aware. Route "
    "here for any operational leave query (the answer requires a live "
    "system call rather than a document lookup)."
)


register_agent(AgentSpec(
    name="lms_agent",
    description=_DESCRIPTION,
    build_subgraph=_build,
    sample_prompts=(
        "What is my leave balance?",
        "Apply for leave from Mar 5 to Mar 8.",
        "Recommend 3 days off near a long weekend.",
        "What are the public holidays in Dubai this month?",
    ),
    enabled_by_default=False,
    requires_employee_context=True,
))
