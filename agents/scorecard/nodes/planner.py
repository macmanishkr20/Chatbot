"""
Scorecard planner node.

Has a deterministic fast-path: when the user query matches the
"default scorecard view" intent verbatim, we skip the LLM call and emit
a hard-coded QueryPlan that selects the canonical KPI columns. Cheaper +
guaranteed correct for the most common interaction.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import AzureChatOpenAI

from agents._base.sql_planner import QueryPlan
from agents.rag.state import RAGState
from agents.scorecard.prompts.planner import (
    SCORECARD_PLANNER_SYSTEM_PROMPT,
    scorecard_planner_user_template,
)
from agents.scorecard.schema import SCORECARD_DEFAULT_VIEW_COLUMNS, SCORECARD_SCHEMA
from core.config import (
    AZURE_OPENAI_CHAT_API_VERSION,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
)
from core.telemetry import get_tracer_span, record_event
from infrastructure.openai.client import get_llm_model

logger = logging.getLogger(__name__)


# Trigger phrases for the deterministic default-view fast path.
_DEFAULT_VIEW_RE = re.compile(
    r"\b("
    r"my\s+scorecard|"
    r"show\s+(?:me\s+)?(?:my\s+)?scorecard|"
    r"give\s+(?:me\s+)?(?:my\s+)?scorecard|"
    r"scorecard\s+summary|"
    r"scorecard\s+(?:view|snapshot)|"
    r"display\s+(?:my\s+)?scorecard"
    r")\b",
    re.IGNORECASE,
)


def _default_view_plan() -> QueryPlan:
    """Hard-coded plan that matches the reference scorecard image."""
    return QueryPlan(
        intent="list",
        select_columns=list(SCORECARD_DEFAULT_VIEW_COLUMNS),
        limit=1,
        confidence=1.0,
    )


def _low_confidence_plan() -> QueryPlan:
    return QueryPlan(
        intent="list",
        select_columns=[],
        confidence=0.0,
        clarification_question=(
            "I can show your scorecard KPIs, rank employees by a metric, "
            "or summarise totals. What would you like to see?"
        ),
    )


_planner_llm: AzureChatOpenAI | None = None


def _get_planner_llm() -> AzureChatOpenAI:
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


async def scorecard_planner_node(state: RAGState) -> dict[str, Any]:
    with get_tracer_span("node.scorecard_planner"):
        user_input = (state.get("user_input") or "").strip()

        # ── Fast path: deterministic default-view ──
        if user_input and _DEFAULT_VIEW_RE.search(user_input):
            plan = _default_view_plan()
            record_event("scorecard.plan", {"path": "default_view"})
            return {"scorecard_plan": plan.model_dump()}

        # ── Otherwise: LLM planner ──
        if not user_input:
            plan = _low_confidence_plan()
        else:
            try:
                system_prompt = SCORECARD_PLANNER_SYSTEM_PROMPT.format(
                    schema_block=SCORECARD_SCHEMA.render_for_prompt(),
                )
                prompt = ChatPromptTemplate.from_messages([
                    ("system", system_prompt),
                    ("human", scorecard_planner_user_template(user_input)),
                ])
                chain = prompt | _get_planner_llm().with_structured_output(QueryPlan)
                plan = await chain.ainvoke({})
            except Exception as exc:
                logger.warning("scorecard planner LLM failed: %s — clarifying", exc)
                plan = _low_confidence_plan()

        record_event(
            "scorecard.plan",
            {
                "path": "llm",
                "intent": plan.intent,
                "aggregate": plan.aggregate,
                "n_filters": len(plan.filters),
                "limit": plan.limit,
                "confidence": plan.confidence,
            },
        )
        return {"scorecard_plan": plan.model_dump()}
