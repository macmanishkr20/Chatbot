"""
Scorecard executor — compile plan + apply RLS + run SQL.

Identical RLS semantics to Expense: non-admin ranks (rank ∉ {11, 13})
are AND-injected with ``EmployeeId = <gui>`` at compile time.
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
from agents.rag.state import RAGState
from agents.scorecard.data_sources import get_scorecard_data_source
from agents.scorecard.schema import SCORECARD_SCHEMA
from core.config import PLANNER_CONFIDENCE_THRESHOLD, PLANNER_ROW_CAP
from core.rbac import can_query_other_gui
from core.telemetry import get_tracer_span, record_event

logger = logging.getLogger(__name__)


def _build_security_predicates(state: RAGState) -> list[tuple[str, list[Any]]]:
    if can_query_other_gui(state.get("rank_code")):
        return []
    gui = (state.get("gui") or "").strip()
    if not gui:
        return [("1 = 0", [])]
    return [("EmployeeId = ?", [gui])]


async def scorecard_executor_node(state: RAGState) -> dict[str, Any]:
    with get_tracer_span("node.scorecard_executor"):
        plan_dict = state.get("scorecard_plan") or {}
        try:
            plan = QueryPlan(**plan_dict)
        except Exception as exc:
            logger.error("scorecard_executor: bad plan in state: %s", exc, exc_info=True)
            return _no_result_payload(error_code="BAD_PLAN", explain="invalid plan")

        if plan.confidence < PLANNER_CONFIDENCE_THRESHOLD:
            return {
                "scorecard_result": {
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
                SCORECARD_SCHEMA,
                security_predicates=security_preds,
                hard_row_cap=PLANNER_ROW_CAP,
            )
        except CompileError as exc:
            logger.warning("scorecard compile error: %s", exc)
            return _no_result_payload(error_code="COMPILE_ERROR", explain=str(exc))

        explain = explain_query_plan(plan, SCORECARD_SCHEMA)
        ds = get_scorecard_data_source()

        try:
            rows = await ds.execute_query(sql, params)
        except DataSourceError as exc:
            logger.warning("scorecard data-source error: %s", exc)
            record_event("scorecard.execute", {"ok": False, "error_code": exc.code})
            return _no_result_payload(
                error_code=exc.code,
                explain=f"{exc.code}: {exc.detail[:200]}",
                sql=sql,
            )

        record_event(
            "scorecard.execute",
            {
                "ok": True,
                "backend": ds.backend_name,
                "rowcount": len(rows),
                "rls_applied": bool(security_preds),
                "intent": plan.intent,
            },
        )
        return {
            "scorecard_result": {
                "ok": True,
                "rows": rows,
                "rowcount": len(rows),
                "sql": sql,
                "explain": explain,
                "intent": plan.intent,
                "rls_applied": bool(security_preds),
                "source": {"backend": ds.backend_name, "table": SCORECARD_SCHEMA.table},
            }
        }


def _no_result_payload(*, error_code: str, explain: str, sql: str | None = None) -> dict:
    return {
        "scorecard_result": {
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
