"""
Expense planner node — turns NL into a typed ``QueryPlan``.

Uses ``LLM.with_structured_output(QueryPlan)`` so the LLM cannot return
free-form SQL or anything off-schema. On parse failure or LLM error we
emit a low-confidence stub plan; the graph routes that to a clarification
response instead of executing.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import AzureChatOpenAI

from core.config import (
    AZURE_OPENAI_CHAT_API_VERSION,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
)
from core.telemetry import get_tracer_span, record_event
from agents.rag.state import RAGState
from agents._base.sql_planner import QueryPlan
from agents.expense.schema import EXPENSE_SCHEMA
from agents.expense.prompts.planner import (
    EXPENSE_PLANNER_SYSTEM_PROMPT,
    expense_planner_user_template,
)
from infrastructure.openai.client import get_llm_model

logger = logging.getLogger(__name__)


_planner_llm: AzureChatOpenAI | None = None


def _get_planner_llm() -> AzureChatOpenAI:
    """Singleton planner LLM — deterministic (temp=0), non-streaming."""
    global _planner_llm
    if _planner_llm is None:
        _planner_llm = AzureChatOpenAI(
            azure_deployment=get_llm_model("planner"),
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_KEY,
            api_version=AZURE_OPENAI_CHAT_API_VERSION,
            temperature=0.0,
            streaming=False,
            max_retries=2,
        )
    return _planner_llm


def _low_confidence_plan(reason: str) -> QueryPlan:
    """Fallback plan when the LLM fails to produce a valid one."""
    return QueryPlan(
        intent="list",
        select_columns=[],
        confidence=0.0,
        clarification_question=(
            "I couldn't translate that into an expense query. "
            "Try: \"my highest expense in FY26\" or \"total spent on flights this year\"."
        ),
    )


async def expense_planner_node(state: RAGState) -> dict[str, Any]:
    """Run the planner LLM and stash the QueryPlan into state."""
    with get_tracer_span("node.expense_planner"):
        user_input = (state.get("user_input") or "").strip()
        if not user_input:
            plan = _low_confidence_plan("empty input")
        else:
            try:
                system_prompt = EXPENSE_PLANNER_SYSTEM_PROMPT.format(
                    schema_block=EXPENSE_SCHEMA.render_for_prompt(),
                )
                prompt = ChatPromptTemplate.from_messages([
                    ("system", system_prompt),
                    ("human", expense_planner_user_template(user_input)),
                ])
                chain = prompt | _get_planner_llm().with_structured_output(QueryPlan)
                plan = await chain.ainvoke({})
            except Exception as exc:
                logger.warning("expense planner LLM failed: %s — clarifying", exc)
                plan = _low_confidence_plan(f"llm_error:{type(exc).__name__}")

        record_event(
            "expense.plan",
            {
                "intent": plan.intent,
                "aggregate": plan.aggregate,
                "n_filters": len(plan.filters),
                "n_group_by": len(plan.group_by),
                "limit": plan.limit,
                "confidence": plan.confidence,
            },
        )
        return {"expense_plan": plan.model_dump()}
