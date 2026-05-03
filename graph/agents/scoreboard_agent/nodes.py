"""
Scoreboard agent nodes — predicate-tree pipeline shared with Expense
agent, plus a privacy gate.

  privacy_gate     → reject queries that ask for OTHER employees' scores
                     when the viewer doesn't have manager / admin scope.
  understand_query → LLM emits typed QueryPlan
  execute_query    → compile + RLS + DataDB.fetchall
  synthesize       → narrate the result
  persist          → chat-history record
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
from graph.agents.scoreboard_agent.state import ScoreboardAgentState
from prompts.data_synthesize import (
    DATA_SYNTHESIZE_SYSTEM_PROMPT,
    synthesize_user_template,
)
from prompts.predicate_planner import (
    PREDICATE_PLANNER_SYSTEM_PROMPT,
    SCOREBOARD_EXAMPLES,
    planner_user_template,
)
from services.data_db import DataDB
from services.data_schemas import SCOREBOARD_SCHEMA
from services.openai_client import get_llm_model
from services.telemetry import get_tracer_span
from services.text_to_predicate import (
    CompileError,
    QueryPlan,
    compile_query_plan,
    explain_query_plan,
)

logger = logging.getLogger(__name__)


# ── LLM construction (independent caches so concurrent agents don't collide) ──

_planner_llm = None
_synthesizer_llm = None


def _get_planner_llm():
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


# ── Privacy gate ────────────────────────────────────────────────────────

_BLOCK_TEMPLATE = (
    "I can only show scoreboard information you're authorised to see. "
    "Your query asked about other employees, but you don't have manager "
    "or HR permissions for them. Try asking about your own scoreboard "
    "instead."
)


def _resolve_scope(state: ScoreboardAgentState) -> str:
    """Decide row-level visibility based on the auth user's role.

    Priority:
      * is_admin / HR → all
      * is_manager     → team
      * default        → self
    """
    if state.get("is_admin"):
        return "all"
    if state.get("is_manager"):
        return "team"
    return "self"


async def privacy_gate_node(state: ScoreboardAgentState) -> dict:
    """Pre-flight: detect queries that exceed the viewer's scope.

    Heuristic: if the user mentions another employee by name / id and
    the resolved scope is "self", reject before we even plan.

    The execute step also enforces RLS at SQL level — this node just
    short-circuits early so the LLM doesn't spend tokens on an
    impossible query.
    """
    user_input = (state.get("user_input") or "").lower()
    scope = _resolve_scope(state)

    # Cheap signal: ranking questions that ask "which employee" at "self"
    # scope can never return a non-self answer for the viewer.
    suspicious_phrases = [
        "which employee", "who has the highest", "who has the lowest",
        "top employee", "best employee", "everyone", "all employees",
        "team scoreboard", "compare employees",
    ]
    triggered = any(p in user_input for p in suspicious_phrases)

    if scope == "self" and triggered:
        return {
            "viewer_scope": scope,
            "privacy_blocked_reason": _BLOCK_TEMPLATE,
        }

    return {"viewer_scope": scope}


# ── understand_query ────────────────────────────────────────────────────

async def understand_query_node(state: ScoreboardAgentState) -> dict:
    """LLM → QueryPlan. Skipped if privacy gate already blocked."""
    if state.get("privacy_blocked_reason"):
        return {}

    with get_tracer_span("scoreboard.understand_query"):
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
            schema_description=SCOREBOARD_SCHEMA.render_for_prompt(),
            examples=SCOREBOARD_EXAMPLES,
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
            logger.warning("scoreboard.understand_query: planner failed: %s", exc, exc_info=True)
            return {
                "query_plan": None,
                "error_info": {
                    "error_code": "PLANNER_FAILED",
                    "text": "I couldn't understand that as a scoreboard query — try rephrasing.",
                },
            }

        return {
            "query_plan": plan.model_dump(),
            "plan_explanation": explain_query_plan(plan, SCOREBOARD_SCHEMA),
        }


# ── execute_query ───────────────────────────────────────────────────────

async def execute_query_node(state: ScoreboardAgentState) -> dict:
    if state.get("privacy_blocked_reason"):
        return {}

    with get_tracer_span("scoreboard.execute_query"):
        plan_dict = state.get("query_plan")
        if not plan_dict:
            return {"query_rows": [], "aggregate_value": None}

        try:
            plan = QueryPlan.model_validate(plan_dict)
        except Exception as exc:
            return {
                "query_rows": [],
                "error_info": {"error_code": "INVALID_PLAN", "text": str(exc)},
            }

        scope = state.get("viewer_scope") or "self"
        viewer_employee_id = state.get("employee_id") or state.get("user_id") or ""
        viewer_manager_id = state.get("manager_id") or viewer_employee_id

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
        elif scope == "team":
            if not viewer_manager_id:
                security_predicates.append(("EmployeeId = ?", [viewer_employee_id]))
            else:
                security_predicates.append(("ManagerId = ?", [viewer_manager_id]))
        elif scope == "all":
            pass
        else:
            return {
                "query_rows": [],
                "error_info": {"error_code": "BAD_SCOPE", "text": f"Unknown viewer_scope={scope!r}"},
            }

        try:
            sql, params = compile_query_plan(
                plan,
                SCOREBOARD_SCHEMA,
                security_predicates=security_predicates,
                hard_row_cap=1000,
            )
        except CompileError as exc:
            logger.warning("scoreboard.execute_query: compile failed: %s", exc)
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
            logger.error("scoreboard.execute_query: DB error: %s", exc, exc_info=True)
            return {
                "query_rows": [],
                "error_info": {
                    "error_code": "DB_ERROR",
                    "text": "I couldn't reach the scoreboard database — please try again shortly.",
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


# ── synthesize ──────────────────────────────────────────────────────────

async def synthesize_node(state: ScoreboardAgentState) -> dict:
    """Narrate the rows. If privacy gate blocked, render the template."""
    blocked = state.get("privacy_blocked_reason")
    if blocked:
        return {
            "messages": [AIMessage(content=blocked)],
            "ai_content": blocked,
            "is_free_form": True,
        }

    with get_tracer_span("scoreboard.synthesize"):
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
            logger.error("scoreboard.synthesize: LLM error: %s", exc, exc_info=True)
            content = "Sorry, I hit an error while writing the answer. Please try again."

        return {
            "messages": [AIMessage(content=content)],
            "ai_content": content,
            "is_free_form": True,
        }
