"""
Per-agent state extension for Scoreboard. Same shape as ExpenseAgentState
because both share the predicate-tree pipeline.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from graph.state import RAGState


class ScoreboardAgentState(RAGState, total=False):
    employee_id: str
    manager_id: Optional[str]
    viewer_scope: Literal["self", "team", "all"]
    is_admin: bool
    is_manager: bool

    query_plan: dict | None
    plan_explanation: str | None
    query_sql: str | None
    query_rows: list[dict[str, Any]] | None
    aggregate_value: Any | None
    row_count: int | None
    privacy_blocked_reason: Optional[str]
