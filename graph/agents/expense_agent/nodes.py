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

import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from config import AZURE_OPENAI_KEY
from graph.agents.expense_agent.state import ExpenseAgentState
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
from services.data_schemas import EXPENSE_SCHEMA
from services.openai_client import get_llm_model
from services.role_lookup import get_role
from services.telemetry import get_tracer_span
from services.text_to_predicate import (
    CompileError,
    QueryPlan,
    compile_query_plan,
    explain_query_plan,
)

logger = logging.getLogger(__name__)


# ── Lazy LLM construction ──

_planner_llm = None
_synthesizer_llm = None


def _get_planner_llm():
    """Structured-output LLM for the planner step."""
    from langchain_openai import AzureChatOpenAI
    from config import AZURE_OPENAI_API_VERSION
    global _planner_llm
    if _planner_llm is None:
        _planner_llm = AzureChatOpenAI(
            azure_deployment=get_llm_model("planner"),
            api_key=AZURE_OPENAI_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
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
            examples=EXPENSE_EXAMPLES,
        )
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
            logger.warning("expense.understand_query: planner failed: %s", exc, exc_info=True)
            return {
                "query_plan": None,
                "error_info": {
                    "error_code": "PLANNER_FAILED",
                    "text": "I couldn't understand that as an expense query — try rephrasing.",
                },
            }

        return {
            "query_plan": plan.model_dump(),
            "plan_explanation": explain_query_plan(plan, EXPENSE_SCHEMA),
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
        # `viewer_scope` is set by `resolve_role_node` from AgentUserRoles.
        # 'self' (default for role='user') → restrict to EmployeeId.
        # 'all'  (manager / admin)         → no row filter — they may
        #                                     see anyone, since the
        #                                     schema does not carry a
        #                                     ManagerId column we could
        #                                     filter on.
        scope = state.get("viewer_scope") or "self"
        viewer_employee_id = state.get("employee_id") or state.get("user_id") or ""

        security_predicates: list[tuple[str, list]] = []
        if scope == "self":
            if not viewer_employee_id:
                return {
                    "query_rows": [],
                    "error_info": {
                        "error_code": "NO_IDENTITY",
                        "text": "Could not resolve your employee identity for this query.",
                    },
                }
            security_predicates.append(("EmployeeId = ?", [viewer_employee_id]))
        elif scope == "all":
            pass  # manager / admin
        else:
            return {
                "query_rows": [],
                "error_info": {"error_code": "BAD_SCOPE", "text": f"Unknown viewer_scope={scope!r}"},
            }

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

        if error_info and not rows:
            text = error_info.get("text", "Sorry, I couldn't run that query.")
            return {
                "messages": [AIMessage(content=text)],
                "ai_content": text,
                "is_free_form": True,
            }

        rows_json = json.dumps(rows[:50], default=str, indent=2)
        system = DATA_SYNTHESIZE_SYSTEM_PROMPT.format(
            plan_explanation=plan_explanation,
            row_count=len(rows),
            aggregate_value="(none)" if aggregate_value is None else str(aggregate_value),
            rows_json=rows_json,
        )
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
        }
