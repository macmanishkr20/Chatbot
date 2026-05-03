"""
Per-agent state extension. Composes with the shared ``RAGState`` so
existing nodes (persist_node, save_memory_node) keep working.

Keeping a per-agent state TypedDict — instead of one fat global state —
limits the blast radius of new fields and makes the agent's I/O explicit.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from graph.state import RAGState


class ExpenseAgentState(RAGState, total=False):
    # ── Auth / row-level-security context ──
    employee_id: str
    manager_id: Optional[str]
    viewer_scope: Literal["self", "team", "all"]

    # ── Planner output ──
    query_plan: dict | None
    plan_explanation: str | None

    # ── Executor output ──
    query_sql: str | None
    query_rows: list[dict[str, Any]] | None
    aggregate_value: Any | None
    row_count: int | None
