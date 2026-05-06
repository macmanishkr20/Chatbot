"""
Expense agent nodes — share the same shape as Scoreboard, both built on
the predicate-tree compiler.

  resolve_role     → AgentUserRoles → (role, scope), cached per session.
  understand_query → LLM turns the question into a typed QueryPlan.
  execute_query    → deterministic compile + DataDB.fetchall + RLS.
  synthesize       → LLM narrates the rows.
  persist          → reuses persist_node for chat-history recording.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from config import AZURE_OPENAI_KEY
from graph.agents.expense_agent.state import ExpenseAgentState
from helpers.fiscal import derive_fiscal_year
from prompts.data_synthesize import (
    DATA_SYNTHESIZE_SYSTEM_PROMPT,
    synthesize_user_template,
)
from prompts.predicate_planner import (
    EXPENSE_EXAMPLES,
    PREDICATE_PLANNER_SYSTEM_PROMPT,
    planner_user_template,
)
from services.data_db import DataDB
from services.data_schemas import EXPENSE_SCHEMA, render_column_enums
from services.drill_suggestions import build_suggestions
from services.openai_client import get_llm_model
from services.query_telemetry import QueryTelemetryRecord, log_query
from services.role_lookup import get_role, resolve_employee_id
from services.telemetry import get_tracer_span
from services.text_to_predicate import (
    CompileError,
    FilterClause,
    QueryPlan,
    compile_query_plan,
    explain_query_plan,
)


# ── Confidence threshold below which we ask, instead of executing ──
_CONFIDENCE_THRESHOLD = 0.6


def _has_time_filter(plan: QueryPlan) -> bool:
    date_cols = {
        c.name.lower() for c in EXPENSE_SCHEMA.columns
        if c.py_type == "date"
    }
    for f in plan.filters:
        if f.fy_label or f.fq_label:
            return True
        if (f.column or "").lower() in date_cols:
            return True
    return False


def _inject_current_fy_default(plan: QueryPlan) -> tuple[QueryPlan, list[str]]:
    """If the plan has no time filter, add a TransactionDate FY filter for
    the current fiscal year and return (plan, applied_defaults)."""
    if _has_time_filter(plan):
        return plan, []
    fy_label = derive_fiscal_year(date.today())
    new_filter = FilterClause(
        column="TransactionDate",
        op="between",
        fy_label=fy_label,
    )
    plan.filters.append(new_filter)
    return plan, [f"current_fy={fy_label}"]

logger = logging.getLogger(__name__)


# ── Lazy LLM construction ──

_planner_llm = None
_synthesizer_llm = None


def _get_planner_llm():
    """Structured-output LLM for the planner step."""
    from langchain_openai import AzureChatOpenAI
    from config import AZURE_OPENAI_CHAT_API_VERSION, AZURE_OPENAI_ENDPOINT
    global _planner_llm
    if _planner_llm is None:
        deployment = get_llm_model("planner")
        logger.info(
            "expense._get_planner_llm: deployment=%s, api_version=%s, endpoint=%s",
            deployment, AZURE_OPENAI_CHAT_API_VERSION, AZURE_OPENAI_ENDPOINT,
        )
        _planner_llm = AzureChatOpenAI(
            azure_deployment=deployment,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_KEY,
            api_version=AZURE_OPENAI_CHAT_API_VERSION,
            temperature=0.0,
            max_retries=2,
            streaming=False,
        )
    return _planner_llm


def _get_synthesizer_llm():
    """Streaming LLM for narrating results."""
    from langchain_openai import AzureChatOpenAI
    from config import AZURE_OPENAI_CHAT_API_VERSION
    global _synthesizer_llm
    if _synthesizer_llm is None:
        _synthesizer_llm = AzureChatOpenAI(
            azure_deployment=get_llm_model("events"),
            api_key=AZURE_OPENAI_KEY,
            api_version=AZURE_OPENAI_CHAT_API_VERSION,
            temperature=0.2,
            streaming=True,
            max_retries=2,
        )
    return _synthesizer_llm


# ── JSON helper ─────────────────────────────────────────────────────────

def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


# ── Node 0: resolve_role (RLS) ──────────────────────────────────────────

async def resolve_role_node(state: ExpenseAgentState) -> dict:
    """Look up the viewer's role from AgentUserRoles and stamp the
    derived scope into state. Cached in-process per user_id."""
    user_id = state.get("user_id") or state.get("employee_id") or ""
    logger.debug("expense.resolve_role: user_id=%s", user_id)
    resolution = await get_role(user_id)
    return {
        "viewer_role": resolution.role,
        "viewer_scope": resolution.scope,
    }


# ── Node 1: understand_query ────────────────────────────────────────────

async def understand_query_node(state: ExpenseAgentState) -> dict:
    """Turn the user question into a typed ``QueryPlan``."""
    with get_tracer_span("expense.understand_query"):
        user_input = (state.get("user_input") or "").strip()
        if not user_input:
            return {
                "query_plan": None,
                "error_info": {"error_code": "EMPTY_QUERY", "text": "No question provided."},
            }

        now = datetime.now()
        system = PREDICATE_PLANNER_SYSTEM_PROMPT.format(
            current_date=now.strftime("%Y-%m-%d"),
            current_date_readable=now.strftime("%A, %B %d, %Y"),
            schema_description=EXPENSE_SCHEMA.render_for_prompt(),
            column_enums=render_column_enums(EXPENSE_SCHEMA.enums or {}),
            examples=EXPENSE_EXAMPLES,
        )
        # Escape literal braces from examples/schema so ChatPromptTemplate
        # doesn't interpret them as template variables.
        system = system.replace("{", "{{").replace("}", "}}")
        prompt = ChatPromptTemplate.from_messages([
            ("system", system),
            ("human", "{user_message}"),
        ])
        chain = prompt | _get_planner_llm().with_structured_output(QueryPlan)
        try:
            plan: QueryPlan = await chain.ainvoke(
                {"user_message": planner_user_template(user_input)},
            )
        except Exception as exc:
            logger.error(
                "expense.understand_query: planner failed: type=%s message=%s",
                type(exc).__name__, exc, exc_info=True,
            )
            # Fire-and-forget telemetry for planner failure.
            try:
                asyncio.create_task(log_query(QueryTelemetryRecord(
                    user_id=state.get("user_id"),
                    agent_name="expense_agent",
                    user_prompt=user_input,
                    status="planner_error",
                    error_message=f"{type(exc).__name__}: {exc}",
                )))
            except Exception:
                pass
            return {
                "query_plan": None,
                "error_info": {
                    "error_code": "PLANNER_FAILED",
                    "text": "I couldn't understand that as an expense query — try rephrasing.",
                },
                "telemetry_status": "planner_error",
            }

        # ── Clarification check (P4) ──
        applied_defaults: list[str] = []
        clarification_needed: dict | None = None
        if (plan.confidence or 1.0) < _CONFIDENCE_THRESHOLD:
            options = list(plan.clarification_options or [])
            clarification_needed = {
                "question": plan.clarification_question
                or "I'm not sure I understood — could you rephrase or pick one?",
                "options": options,
            }
        else:
            # ── Smart default: inject current FY when no time filter present ──
            plan, applied_defaults = _inject_current_fy_default(plan)

        assumption: dict | None = None
        if applied_defaults:
            assumption = {
                "text": (
                    f"Assumed {applied_defaults[0].split('=', 1)[-1]} — change?"
                    if "=" in applied_defaults[0]
                    else f"Applied default: {applied_defaults[0]}"
                ),
                "alternatives": [
                    {"label": "FY25", "prompt": "Show this for FY25 instead."},
                    {"label": "All time", "prompt": "Show this without a date filter."},
                ],
            }

        return {
            "query_plan": plan.model_dump(),
            "plan_explanation": explain_query_plan(plan, EXPENSE_SCHEMA),
            "applied_defaults": applied_defaults,
            "clarification_needed": clarification_needed,
            "assumption": assumption,
        }


# ── Node 2: execute_query ───────────────────────────────────────────────

async def execute_query_node(state: ExpenseAgentState) -> dict:
    """Compile the QueryPlan and run it. RLS predicates are injected
    based on ``viewer_scope``."""
    with get_tracer_span("expense.execute_query"):
        plan_dict = state.get("query_plan")
        if not plan_dict:
            return {"query_rows": [], "aggregate_value": None}

        try:
            plan = QueryPlan.model_validate(plan_dict)
        except Exception as exc:
            logger.warning("expense.execute_query: invalid plan: %s", exc, exc_info=True)
            return {
                "query_rows": [],
                "error_info": {"error_code": "INVALID_PLAN", "text": str(exc)},
            }

        # ── Row-level security ─────────────────────────────────────────
        # scope == "self"  → MUST inject EmployeeId predicate; if we can't
        #                    resolve a numeric EmployeeId for this user, fail
        #                    closed (refuse the query) rather than leak rows.
        # scope == "all"   → manager/admin/HR — no predicate, full visibility.
        scope = state.get("viewer_scope") or "self"
        security_predicates: list[tuple[str, list]] = []
        if scope == "self":
            user_id = state.get("user_id") or state.get("employee_id") or ""
            employee_id = await resolve_employee_id(user_id)
            if not employee_id:
                msg = (
                    "Your employee profile is not yet linked. Contact "
                    "support to enable expense access."
                )
                return {
                    "query_rows": [],
                    "error_info": {"error_code": "RLS_NOT_LINKED", "text": msg},
                }
            security_predicates.append(("EmployeeId = ?", [employee_id]))

        try:
            sql, params = compile_query_plan(
                plan,
                EXPENSE_SCHEMA,
                security_predicates=security_predicates,
                hard_row_cap=1000,
            )
        except CompileError as exc:
            logger.warning("expense.execute_query: compile failed: %s", exc)
            return {
                "query_rows": [],
                "error_info": {
                    "error_code": "COMPILE_FAILED",
                    "text": "Sorry, that query couldn't be compiled safely. Try rephrasing.",
                },
            }

        logger.info("expense.execute_query: SQL=%s | params=%s", sql, params)
        logger.debug("expense.execute_query: sql=%s params=%s", sql, params)

        try:
            db = DataDB()
            rows = await db.fetchall(sql, params)
        except Exception as exc:
            logger.error("expense.execute_query: DB error: %s", exc, exc_info=True)
            return {
                "query_rows": [],
                "error_info": {
                    "error_code": "DB_ERROR",
                    "text": "I couldn't reach the expense database — please try again shortly.",
                },
            }

        aggregate_value: Any | None = None
        if plan.intent == "aggregate" and rows and "Value" in rows[0]:
            if not plan.group_by and len(rows) == 1:
                aggregate_value = rows[0]["Value"]

        return {
            "query_sql": sql,
            "query_rows": [_jsonable(r) for r in rows],
            "aggregate_value": _jsonable(aggregate_value),
            "row_count": len(rows),
        }


# ── Node 3: synthesize ──────────────────────────────────────────────────

async def synthesize_node(state: ExpenseAgentState) -> dict:
    """Narrate the rows in plain English."""
    with get_tracer_span("expense.synthesize"):
        user_input = (state.get("user_input") or "").strip()
        rows = state.get("query_rows") or []
        plan_explanation = state.get("plan_explanation") or ""
        aggregate_value = state.get("aggregate_value")
        error_info = state.get("error_info") or None
        clarification = state.get("clarification_needed")

        # ── Clarification short-circuit (P4) ──
        if clarification:
            question = clarification.get("question") or "Could you clarify?"
            text = (
                f"I'd like to make sure I answer the right thing. {question}"
            )
            try:
                asyncio.create_task(log_query(QueryTelemetryRecord(
                    user_id=state.get("user_id"),
                    agent_name="expense_agent",
                    user_prompt=user_input,
                    query_plan=state.get("query_plan"),
                    confidence_score=(state.get("query_plan") or {}).get("confidence"),
                    status="clarified",
                )))
            except Exception:
                pass
            return {
                "messages": [AIMessage(content=text)],
                "ai_content": text,
                "is_free_form": True,
                "telemetry_status": "clarified",
            }

        # ── Drill-chip suggestions (P2) ──
        drill_suggestions: list[dict] = []
        plan_dict = state.get("query_plan")
        if plan_dict and not error_info:
            try:
                plan_obj = QueryPlan.model_validate(plan_dict)
                drill_suggestions = build_suggestions(
                    plan_obj, EXPENSE_SCHEMA, user_input=user_input,
                )
            except Exception:  # pragma: no cover
                drill_suggestions = []

        # ── Telemetry: terminal status ──
        if error_info and not rows:
            terminal_status = "sql_error" if error_info.get("error_code") in {
                "DB_ERROR", "COMPILE_FAILED", "INVALID_PLAN", "RLS_NOT_LINKED",
            } else "planner_error"
        elif not rows:
            terminal_status = "no_results"
        else:
            terminal_status = "success"

        try:
            asyncio.create_task(log_query(QueryTelemetryRecord(
                user_id=state.get("user_id"),
                agent_name="expense_agent",
                user_prompt=user_input,
                query_plan=state.get("query_plan"),
                confidence_score=(state.get("query_plan") or {}).get("confidence"),
                executed_sql=state.get("query_sql"),
                row_count=state.get("row_count"),
                status=terminal_status,
                error_message=(error_info or {}).get("text"),
            )))
        except Exception:
            pass

        if error_info and not rows:
            text = error_info.get("text", "Sorry, I couldn't run that query.")
            return {
                "messages": [AIMessage(content=text)],
                "ai_content": text,
                "is_free_form": True,
                "drill_suggestions": drill_suggestions,
                "telemetry_status": terminal_status,
            }

        rows_json = json.dumps(rows[:50], default=str, indent=2)
        system = DATA_SYNTHESIZE_SYSTEM_PROMPT.format(
            plan_explanation=plan_explanation,
            row_count=len(rows),
            aggregate_value="(none)" if aggregate_value is None else str(aggregate_value),
            rows_json=rows_json,
        )
        # Escape literal braces (from JSON data) so ChatPromptTemplate
        # doesn't interpret them as template variables.
        system = system.replace("{", "{{").replace("}", "}}")
        prompt = ChatPromptTemplate.from_messages([
            ("system", system),
            ("human", "{user_message}"),
        ])
        chain = prompt | _get_synthesizer_llm()
        try:
            response = await chain.ainvoke(
                {"user_message": synthesize_user_template(user_input)},
            )
            content = (response.content or "").strip() or "Sorry, I couldn't render the result."
        except Exception as exc:
            logger.error("expense.synthesize: LLM error: %s", exc, exc_info=True)
            content = "Sorry, I hit an error while writing the answer. Please try again."

        return {
            "messages": [AIMessage(content=content)],
            "ai_content": content,
            "is_free_form": True,
            "drill_suggestions": drill_suggestions,
            "telemetry_status": terminal_status,
        }
