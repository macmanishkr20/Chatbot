"""
LMS fetch node — calls the appropriate tool based on the classifier decision.

We deliberately do NOT use LLM tool-calling here. The classifier already
decided what to do; we just dispatch deterministically. This:
  - Cuts one LLM round-trip per request.
  - Removes a class of bugs (LLM hallucinating tool names / args).
  - Keeps the contract testable end-to-end without LLM mocking.

The Phase-2 hook for richer behaviour (e.g. compound queries) is to allow
the classifier to return a list of (sub_intent, args) pairs; this node
would then fan-out. The state surface already supports that — we just
loop here. For v1 we run one tool per turn.
"""
from __future__ import annotations

import logging

from core.telemetry import get_tracer_span, record_event
from agents.rag.state import RAGState
from agents.lms.tools.leave import (
    get_leave_applications,
    get_leave_balance,
    get_pending_approvals,
)

logger = logging.getLogger(__name__)


async def lms_fetch_node(state: RAGState) -> dict:
    """Dispatch on lms_sub_intent and execute exactly one LMS tool.

    On `unknown` we skip the tool call entirely — the format node will
    return a clarification prompt without inventing data.
    """
    with get_tracer_span("node.lms_fetch"):
        sub_intent = state.get("lms_sub_intent") or "unknown"
        classifier_meta = (state.get("lms_result") or {}).get("_classifier") or {}
        leave_type = classifier_meta.get("leave_type")
        status_filter = classifier_meta.get("status_filter")

        user_id = state.get("user_id") or ""

        tool_result: dict
        if sub_intent == "balance":
            # @tool wrappers accept .ainvoke for structured invocation.
            tool_result = await get_leave_balance.ainvoke(
                {"employee_id": user_id, "leave_type": leave_type}
            )
        elif sub_intent == "applications":
            tool_result = await get_leave_applications.ainvoke(
                {"employee_id": user_id, "status": status_filter, "limit": 10}
            )
        elif sub_intent == "approvals":
            # In a real deployment, manager_id would be resolved separately.
            # For v1 we treat the current user as the manager — the data
            # source can decide whether that is permitted.
            tool_result = await get_pending_approvals.ainvoke(
                {"manager_id": user_id}
            )
        else:
            # Unknown sub-intent — emit a structured "needs clarification"
            # marker so the format node can ask the user to rephrase.
            tool_result = {
                "ok": False,
                "tool": None,
                "error": {
                    "code": "UNKNOWN_SUB_INTENT",
                    "detail": "Query did not match an LMS sub-intent.",
                    "retriable": False,
                },
            }

        record_event(
            "lms.fetch",
            {
                "sub_intent": sub_intent,
                "tool": tool_result.get("tool"),
                "ok": tool_result.get("ok", False),
                "error_code": (tool_result.get("error") or {}).get("code"),
            },
        )

        # Merge into existing lms_result so the classifier metadata survives.
        existing = state.get("lms_result") or {}
        existing["tool_result"] = tool_result
        return {"lms_result": existing}
