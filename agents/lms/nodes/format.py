"""
LMS format node — turns the raw tool result into a user-facing answer.

Streams tokens just like the RAG generate node, so /chat SSE behaves
identically from the frontend's perspective (the streaming bus already
knows how to surface tokens from a streamable node name — we register
``lms_format`` in api/_runtime.STREAMABLE_NODES).

Hard guarantees:
  - Numbers come only from the tool result; the prompt is explicit.
  - Provenance footer always present.
  - Tool error → graceful apology, no internal codes leaked.
  - "unknown" sub-intent → polite clarification ask.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

from core.telemetry import get_tracer_span, record_event
from agents.rag.state import RAGState
from agents.lms.prompts.format import LMS_FORMAT_SYSTEM_PROMPT
from core.config import (
    AZURE_OPENAI_CHAT_API_VERSION,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
    AZURE_OPENAI_TEMPERATURE,
    MAX_TOKENS,
)
from infrastructure.openai.client import get_llm_model

logger = logging.getLogger(__name__)


_UNKNOWN_INTENT_FALLBACK = (
    "I can help with leave-related queries. Could you tell me which of "
    "these you would like:\n"
    "- **Leave balance** — how many days you have remaining\n"
    "- **Leave applications** — your past or pending leaves\n"
    "- **Pending approvals** — leave requests waiting on your approval\n\n"
    "If you have a policy question (e.g. paternity leave rules), just ask "
    "and I'll look it up in the knowledge base."
)


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


def _format_user_prompt(
    user_input: str,
    tool_result: dict,
    rank_name: str | None,
) -> str:
    """Compact JSON envelope handed to the format LLM."""
    return (
        f"<user_question>\n{user_input}\n</user_question>\n\n"
        f"<user_role>{rank_name or 'Staff'}</user_role>\n\n"
        f"<tool_result>\n{json.dumps(tool_result, ensure_ascii=False, indent=2)}\n</tool_result>"
    )


async def lms_format_node(state: RAGState) -> dict:
    """Render the LMS response and update state for persist + save_memory."""
    with get_tracer_span("node.lms_format"):
        user_input = state.get("user_input") or ""
        sub_intent = state.get("lms_sub_intent") or "unknown"
        lms_state = state.get("lms_result") or {}
        tool_result: dict[str, Any] = lms_state.get("tool_result") or {}

        # ── Short-circuit on unknown sub-intent ──
        if sub_intent == "unknown":
            record_event("lms.format", {"path": "unknown_intent_fallback"})
            return {
                "ai_content": _UNKNOWN_INTENT_FALLBACK,
                "is_free_form": True,
                "messages": [AIMessage(content=_UNKNOWN_INTENT_FALLBACK)],
                "events": [],
            }

        # ── Otherwise, delegate rendering to the LLM with strict rules ──
        rank_info = state.get("rank_info") or {}
        rank_name = rank_info.get("rank_name") if isinstance(rank_info, dict) else None

        messages = [
            SystemMessage(content=LMS_FORMAT_SYSTEM_PROMPT),
            HumanMessage(content=_format_user_prompt(user_input, tool_result, rank_name)),
        ]

        llm = _build_llm()
        response = await llm.ainvoke(messages)
        ai_content = (response.content or "").strip()

        record_event(
            "lms.format",
            {
                "sub_intent": sub_intent,
                "tool_ok": tool_result.get("ok", False),
                "tokens_out": len(ai_content),
            },
        )

        return {
            "ai_content": ai_content,
            "is_free_form": True,
            "messages": [response],
            # Clear events so the response renders without a citations block
            # (LMS provenance is in the answer text itself).
            "events": [],
        }
