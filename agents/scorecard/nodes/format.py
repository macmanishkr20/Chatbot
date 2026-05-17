"""Scorecard format node — same shape as Expense, separate prompt."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

from agents.rag.state import RAGState
from agents.scorecard.prompts.format import SCORECARD_FORMAT_SYSTEM_PROMPT
from core.config import (
    AZURE_OPENAI_CHAT_API_VERSION,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
    AZURE_OPENAI_TEMPERATURE,
    MAX_TOKENS,
)
from core.rbac import can_query_other_gui
from core.telemetry import get_tracer_span, record_event
from infrastructure.openai.client import get_llm_model

logger = logging.getLogger(__name__)


def _build_llm() -> AzureChatOpenAI:
    return AzureChatOpenAI(
        azure_deployment=get_llm_model("events"),
        api_key=AZURE_OPENAI_KEY,
        api_version=AZURE_OPENAI_CHAT_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        temperature=AZURE_OPENAI_TEMPERATURE,
        max_tokens=int(MAX_TOKENS),
        streaming=True,
        max_retries=2,
    )


def _format_user_envelope(state: RAGState, result: dict) -> str:
    rank_info = state.get("rank_info") or {}
    rank_name = rank_info.get("rank_name", "Staff")
    payload = {
        "user_question": state.get("user_input"),
        "user_rank": rank_name,
        "user_full_access": can_query_other_gui(state.get("rank_code")),
        "user_gui": state.get("gui"),
        "explain": result.get("explain"),
        "intent": result.get("intent"),
        "rowcount": result.get("rowcount"),
        "rows": result.get("rows", [])[:50],
        "source": result.get("source"),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


async def scorecard_format_node(state: RAGState) -> dict:
    with get_tracer_span("node.scorecard_format"):
        result = state.get("scorecard_result") or {}

        # ── Clarification ──
        if result.get("needs_clarification"):
            question = result.get("clarification_question") or (
                "Could you clarify? Try \"show me my scorecard\" or "
                "\"which employee has the highest GTER?\"."
            )
            record_event("scorecard.format", {"path": "clarify"})
            return {
                "ai_content": question,
                "is_free_form": True,
                "messages": [AIMessage(content=question)],
                "events": [],
            }

        # ── Error ──
        if not result.get("ok"):
            error_code = result.get("error_code") or "UNKNOWN"
            apology = (
                "I couldn't run that scorecard query right now. "
                f"({error_code}). Please try again, or rephrase your question."
            )
            record_event("scorecard.format", {"path": "error", "error_code": error_code})
            return {
                "ai_content": apology,
                "is_free_form": True,
                "messages": [AIMessage(content=apology)],
                "events": [],
            }

        # ── Empty ──
        if result.get("rowcount", 0) == 0:
            empty = (
                "I didn't find any matching scorecard rows.\n\n"
                "*Source: UserScoreboard · 0 rows · as of "
                f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}*"
            )
            record_event("scorecard.format", {"path": "empty"})
            return {
                "ai_content": empty,
                "is_free_form": True,
                "messages": [AIMessage(content=empty)],
                "events": [],
            }

        # ── Normal ──
        envelope = _format_user_envelope(state, result)
        messages = [
            SystemMessage(content=SCORECARD_FORMAT_SYSTEM_PROMPT),
            HumanMessage(content=envelope),
        ]
        response = await _build_llm().ainvoke(messages)
        ai_content = (response.content or "").strip()

        record_event(
            "scorecard.format",
            {"path": "ok", "rowcount": result.get("rowcount"), "tokens_out": len(ai_content)},
        )
        return {
            "ai_content": ai_content,
            "is_free_form": True,
            "messages": [AIMessage(content=ai_content)],
            "events": [],
        }
