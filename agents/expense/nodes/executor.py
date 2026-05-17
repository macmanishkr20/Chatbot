"""
Expense executor node — compile the QueryPlan + apply RLS + run SQL.

RLS contract:
  - rank_code ∈ FULL_DATA_ACCESS_RANK_CODES → no GUI predicate
  - everyone else → ``EmployeeId = <user_gui>`` AND-injected by the compiler
"""
from __future__ import annotations

import logging
from typing import Any

from agents._base.sql_planner import (
    CompileError,
    QueryPlan,
    compile_query_plan,
    explain_query_plan,
)
from agents._base.sql_planner.data_source import DataSourceError
from agents.expense.data_sources import get_expense_data_source
from agents.expense.schema import EXPENSE_SCHEMA
from agents.rag.state import RAGState
from core.config import PLANNER_CONFIDENCE_THRESHOLD, PLANNER_ROW_CAP
from core.rbac import can_query_other_gui
from core.telemetry import get_tracer_span, record_event

logger = logging.getLogger(__name__)


def _build_security_predicates(state: RAGState) -> list[tuple[str, list[Any]]]:
    """Return the RLS WHERE fragments for this user.

    Empty list → full access (rank 11 / 13).
    Non-empty  → forces ``EmployeeId = <gui>`` so the user can never see
                 anyone else's data, even if the LLM somehow tried.
    """
    if can_query_other_gui(state.get("rank_code")):
        return []
    gui = (state.get("gui") or "").strip()
    if not gui:
        # No GUI and not an admin rank → reject everything.
        return [("1 = 0", [])]
    return [("EmployeeId = ?", [gui])]


async def expense_executor_node(state: RAGState) -> dict[str, Any]:
    """Compile + execute the Expense plan; stash result for the format node."""
    with get_tracer_span("node.expense_executor"):
        plan_dict = state.get("expense_plan") or {}
        try:
            plan = QueryPlan(**plan_dict)
        except Exception as exc:
            logger.error("expense_executor: bad plan in state: %s", exc, exc_info=True)
            return _no_result_payload(
                error_code="BAD_PLAN",
                explain="planner produced an invalid plan",
            )

        if plan.confidence < PLANNER_CONFIDENCE_THRESHOLD:
            # Skip execution — surface clarification via the format node.
            return {
                "expense_result": {
                    "ok": False,
                    "needs_clarification": True,
                    "clarification_question": plan.clarification_question,
                    "rows": [],
                    "rowcount": 0,
                    "sql": None,
                    "explain": "low planner confidence",
                    "source": {"backend": "n/a"},
                }
            }

        security_preds = _build_security_predicates(state)

        try:
            sql, params = compile_query_plan(
                plan,
                EXPENSE_SCHEMA,
                security_predicates=security_preds,
                hard_row_cap=PLANNER_ROW_CAP,
            )
        except CompileError as exc:
            logger.warning("expense compile error: %s", exc)
            return _no_result_payload(
                error_code="COMPILE_ERROR",
                explain=str(exc),
            )

        explain = explain_query_plan(plan, EXPENSE_SCHEMA)
        ds = get_expense_data_source()

        try:
            rows = await ds.execute_query(sql, params)
        except DataSourceError as exc:
            logger.warning("expense data-source error: %s", exc)
            record_event("expense.execute", {"ok": False, "error_code": exc.code})
            return _no_result_payload(
                error_code=exc.code,
                explain=f"{exc.code}: {exc.detail[:200]}",
                sql=sql,
            )

        record_event(
            "expense.execute",
            {
                "ok": True,
                "backend": ds.backend_name,
                "rowcount": len(rows),
                "rls_applied": bool(security_preds),
            },
        )

        return {
            "expense_result": {
                "ok": True,
                "rows": rows,
                "rowcount": len(rows),
                "sql": sql,
                "explain": explain,
                "rls_applied": bool(security_preds),
                "source": {"backend": ds.backend_name, "table": EXPENSE_SCHEMA.table},
            }
        }


def _no_result_payload(*, error_code: str, explain: str, sql: str | None = None) -> dict:
    return {
        "expense_result": {
            "ok": False,
            "needs_clarification": False,
            "rows": [],
            "rowcount": 0,
            "sql": sql,
            "explain": explain,
            "error_code": error_code,
            "source": {"backend": "n/a"},
        }
    }
