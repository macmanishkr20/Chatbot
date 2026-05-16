"""
LMS sub-intent classifier node.

Single LLM call that maps the user query to one of:
    "balance" | "applications" | "approvals" | "unknown"

Why classify before fetching:
  - Each sub-intent has a single allowed tool. Pre-classifying eliminates
    the chance of the tool-calling LLM picking the wrong tool.
  - The classifier is cheap (≤200 input tokens, ~30 output tokens).
  - Failure mode is graceful: on parse failure or LLM error we fall back
    to "unknown" so the format node asks the user to clarify rather than
    hallucinating data.
"""
from __future__ import annotations

import json
import logging

from core.telemetry import get_tracer_span, record_event
from agents.rag.state import RAGState
from agents.lms.prompts.classifier import LMS_CLASSIFIER_SYSTEM_PROMPT
from core.config import AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY
from infrastructure.openai.client import (
    create_async_client,
    get_llm_model,
    prepare_model_args,
    retry_with_llm_backoff,
)

logger = logging.getLogger(__name__)

_VALID_SUB_INTENTS = {"balance", "applications", "approvals", "unknown"}


@retry_with_llm_backoff()
async def _classify(user_input: str, llm_model: str) -> dict:
    messages = [
        {"role": "system", "content": LMS_CLASSIFIER_SYSTEM_PROMPT},
        {"role": "user", "content": user_input},
    ]
    client = create_async_client(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_key=AZURE_OPENAI_KEY,
        llm_model=llm_model,
    )
    response = await client.chat.completions.create(
        **prepare_model_args(
            request_messages=messages,
            stream=False,
            use_data=False,
            tools=None,
            tool_choice=None,
            response_format="json_object",
            llm_model=llm_model,
        )
    )
    return json.loads(response.choices[0].message.content)


def _safe_default(reason: str) -> dict:
    """Conservative fallback when classification fails."""
    return {
        "sub_intent": "unknown",
        "leave_type": None,
        "status_filter": None,
        "rationale": reason,
    }


async def lms_classify_node(state: RAGState) -> dict:
    """Decide the LMS sub-intent and stash filters into state."""
    with get_tracer_span("node.lms_classify"):
        user_input = (state.get("user_input") or "").strip()
        if not user_input:
            decision = _safe_default("empty user_input")
        else:
            try:
                decision = await _classify(user_input, get_llm_model("rewrite_query"))
            except Exception as exc:
                logger.warning("lms_classify LLM failed: %s — falling back to unknown", exc)
                decision = _safe_default(f"llm_error:{type(exc).__name__}")

            # Hard-validate the sub_intent — never trust untrusted LLM output.
            sub_intent = decision.get("sub_intent")
            if sub_intent not in _VALID_SUB_INTENTS:
                logger.warning("lms_classify produced invalid sub_intent=%r — falling back to unknown", sub_intent)
                decision = _safe_default(f"invalid_sub_intent:{sub_intent!r}")

        record_event(
            "lms.classify",
            {
                "sub_intent": decision.get("sub_intent"),
                "has_leave_type": bool(decision.get("leave_type")),
                "has_status_filter": bool(decision.get("status_filter")),
            },
        )

        return {
            "lms_sub_intent": decision.get("sub_intent"),
            # Reuse `rewritten_query` as a side-channel for tool args — keeps
            # state surface narrow. Format node will pull from lms_result.
            "lms_result": {
                "_classifier": {
                    "leave_type": decision.get("leave_type"),
                    "status_filter": decision.get("status_filter"),
                    "rationale": decision.get("rationale"),
                }
            },
        }
