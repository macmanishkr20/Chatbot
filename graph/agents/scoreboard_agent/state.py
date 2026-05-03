"""
Per-agent state extension for the Scoreboard agent.

Same shape as ExpenseAgentState because both share the predicate-tree
pipeline. Authorisation comes from ``services.role_lookup`` reading
``AgentUserRoles``.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from graph.state import RAGState


class ScoreboardAgentState(RAGState, total=False):
    employee_id: str
    viewer_role: Literal["user", "manager", "admin"]
    viewer_scope: Literal["self", "all"]

    query_plan: dict | None
    plan_explanation: str | None
    query_sql: str | None
    query_rows: list[dict[str, Any]] | None
    aggregate_value: Any | None
    row_count: int | None
    privacy_blocked_reason: Optional[str]
