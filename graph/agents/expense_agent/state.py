"""
Per-agent state extension for the Expense agent.

Composes with the shared ``RAGState`` so existing nodes
(persist_node, save_memory_node) keep working.

Authorisation is sourced from ``services.role_lookup`` which reads
``AgentUserRoles``. The agent stamps the resolved role + scope into
state once (in ``understand_query_node``) so all downstream nodes see
the same value.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from graph.state import RAGState


class ExpenseAgentState(RAGState, total=False):
    # ── Auth / row-level-security context ──
    employee_id: str
    viewer_role: Literal["user", "manager", "admin"]
    viewer_scope: Literal["self", "all"]

    # ── Planner output ──
    query_plan: dict | None
    plan_explanation: str | None

    # ── Executor output ──
    query_sql: str | None
    query_rows: list[dict[str, Any]] | None
    aggregate_value: Any | None
    row_count: int | None
