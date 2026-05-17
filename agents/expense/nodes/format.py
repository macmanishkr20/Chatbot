"""
Expense format node — renders rows into a streaming user-facing answer.

Streams via the same SSE mechanism as RAG ``generate`` and LMS
``lms_format`` — the node name ``expense_format`` is registered in
``api/_runtime.STREAMABLE_NODES`` so its tokens hit the wire as they
arrive.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

from agents.expense.prompts.format import EXPENSE_FORMAT_SYSTEM_PROMPT
from agents.rag.state import RAGState
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


def _format_user_envelope(state: RAGState, expense_result: dict) -> str:
    rank_info = state.get("rank_info") or {}
    rank_name = rank_info.get("rank_name", "Staff")
    full_access = can_query_other_gui(state.get("rank_code"))
    payload = {
        "user_question": state.get("user_input"),
        "user_rank": rank_name,
        "user_full_access": full_access,
        "user_gui": state.get("gui"),
        "explain": expense_result.get("explain"),
        "rowcount": expense_result.get("rowcount"),
        "rows": expense_result.get("rows", [])[:50],   # cap rendered rows
        "source": expense_result.get("source"),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


async def expense_format_node(state: RAGState) -> dict:
    """Render the executed-query result as a markdown response."""
    with get_tracer_span("node.expense_format"):
        result = state.get("expense_result") or {}

        # ── (1) Clarification path ──
        if result.get("needs_clarification"):
            question = result.get("clarification_question") or (
                "Could you clarify what you'd like to see? "
                "For example: \"my highest expense in FY26\" or "
                "\"total spent on flights this year\"."
            )
            record_event("expense.format", {"path": "clarify"})
            return {
                "ai_content": question,
                "is_free_form": True,
                "messages": [AIMessage(content=question)],
                "events": [],
            }

        # ── (2) Error path ──
        if not result.get("ok"):
            error_code = result.get("error_code") or "UNKNOWN"
            apology = (
                "I couldn't run that expense query right now. "
                f"({error_code}). Please try again, or rephrase your question."
            )
            record_event("expense.format", {"path": "error", "error_code": error_code})
            return {
                "ai_content": apology,
                "is_free_form": True,
                "messages": [AIMessage(content=apology)],
                "events": [],
            }

        # ── (3) Empty-result path: still surface the explain + footer ──
        if result.get("rowcount", 0) == 0:
            empty = (
                "I didn't find any matching expense rows.\n\n"
                "*Source: UserExpenses · 0 rows · as of "
                f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}*"
            )
            record_event("expense.format", {"path": "empty"})
            return {
                "ai_content": empty,
                "is_free_form": True,
                "messages": [AIMessage(content=empty)],
                "events": [],
            }

        # ── (4) Normal: LLM renders the result rows ──
        envelope = _format_user_envelope(state, result)
        messages = [
            SystemMessage(content=EXPENSE_FORMAT_SYSTEM_PROMPT),
            HumanMessage(content=envelope),
        ]
        response = await _build_llm().ainvoke(messages)
        ai_content = (response.content or "").strip()

        record_event(
            "expense.format",
            {"path": "ok", "rowcount": result.get("rowcount"), "tokens_out": len(ai_content)},
        )
        return {
            "ai_content": ai_content,
            "is_free_form": True,
            "messages": [AIMessage(content=ai_content)],
            "events": [],
        }
