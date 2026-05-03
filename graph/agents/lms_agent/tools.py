"""
LangChain tool wrappers around services.lms_client.

Today the upstream HR system exposes only a single read endpoint
(``GET /api/LeaveSnapshot?email=…``). Read tools project from that
snapshot; write / holiday tools call into the client and surface its
``LMSNotImplementedError`` cleanly so the LLM can tell the user what
isn't available yet.

Each tool returns a JSON-serialisable dict — the ReAct loop converts
those into ``ToolMessage`` content for the next LLM turn.
"""
from __future__ import annotations

import contextvars
import logging
from datetime import date as _date, datetime
from typing import Any

from langchain_core.tools import tool

from services.lms_client import (
    Holiday,
    LeaveBalance,
    LeaveRequest,
    LMSError,
    LMSNotImplementedError,
    LMSValidationError,
    get_lms_client,
)

logger = logging.getLogger(__name__)


# ── Context plumbing ────────────────────────────────────────────────────
#
# Tools defined with @tool can't see the LangGraph state directly, so we
# carry the per-request identity in a contextvar set by the agent.
# `email` is the LeaveSnapshot key; `employee_id` is kept for parity
# with other agents and falls back to the email when no separate id is
# available.

_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "lms_tool_context",
    default={},
)


def set_tool_context(*, session_id: str, email: str, employee_id: str | None = None,
                     location: str | None = None, today: _date | None = None) -> contextvars.Token:
    """Bind the per-call context for the LMS toolbelt. Returns a token to reset."""
    return _CONTEXT.set({
        "session_id": session_id,
        "email": email,
        "employee_id": employee_id or email,
        "location": location or "ALL",
        "today": today or datetime.now().date(),
    })


def reset_tool_context(token: contextvars.Token) -> None:
    _CONTEXT.reset(token)


def _ctx() -> dict[str, Any]:
    c = _CONTEXT.get()
    if not c.get("session_id") or not c.get("email"):
        raise RuntimeError(
            "LMS tool called without a bound context — "
            "call set_tool_context() first.",
        )
    return c


# ── Serialisation helpers ──────────────────────────────────────────────

def _serialise_balance(b: LeaveBalance) -> dict:
    return {
        "leave_type": b.leave_type,
        "available_days": b.available_days,
        "accrued_days": b.accrued_days,
        "used_days": b.used_days,
        "pending_days": b.pending_days,
    }


def _serialise_request(r: LeaveRequest) -> dict:
    return {
        "request_id": r.request_id,
        "employee_id": r.employee_id,
        "leave_type": r.leave_type,
        "start_date": r.start_date.isoformat(),
        "end_date": r.end_date.isoformat(),
        "days": r.days,
        "status": r.status,
        "reason": r.reason,
    }


def _serialise_holiday(h: Holiday) -> dict:
    return {
        "name": h.name,
        "date": h.holiday_date.isoformat(),
        "location": h.location,
        "is_optional": h.is_optional,
    }


# ── Read-only tools (backed by /api/LeaveSnapshot) ─────────────────────

@tool
async def get_leave_snapshot() -> dict:
    """Return the full leave snapshot for the current user as raw JSON.

    Use this when the user asks anything about their leave (balance,
    pending requests, anything else surfaced by the HR system) — it
    contains every field the upstream returns, so the answer can be
    derived from one call.
    """
    ctx = _ctx()
    try:
        snapshot = await get_lms_client().get_leave_snapshot(
            session_id=ctx["session_id"],
            email=ctx["email"],
        )
        return {"ok": True, "snapshot": snapshot}
    except LMSError as exc:
        logger.warning("get_leave_snapshot failed: %s", exc)
        return {"ok": False, "error": str(exc)}


@tool
async def get_leave_balance(leave_type: str | None = None) -> dict:
    """Return the user's leave balance.

    Args:
        leave_type: Optional filter, e.g. "Annual" / "Sick" / "Casual".
            Omit to return balances for all leave types.
    """
    ctx = _ctx()
    try:
        balances = await get_lms_client().get_leave_balance(
            session_id=ctx["session_id"],
            email=ctx["email"],
            leave_type=leave_type,
        )
        return {"ok": True, "balances": [_serialise_balance(b) for b in balances]}
    except LMSError as exc:
        logger.warning("get_leave_balance failed: %s", exc)
        return {"ok": False, "error": str(exc)}


@tool
async def get_pending_leaves() -> dict:
    """Return the user's pending leave requests."""
    ctx = _ctx()
    try:
        requests = await get_lms_client().get_pending_leaves(
            session_id=ctx["session_id"],
            email=ctx["email"],
        )
        return {"ok": True, "requests": [_serialise_request(r) for r in requests]}
    except LMSError as exc:
        logger.warning("get_pending_leaves failed: %s", exc)
        return {"ok": False, "error": str(exc)}


# ── Tools backed by capabilities the upstream doesn't expose yet ────────
#
# These call into the client which raises LMSNotImplementedError — we
# surface the error cleanly so the LLM tells the user what isn't
# available rather than fabricating an answer.

@tool
async def get_holiday_calendar(year: int | None = None, month: int | None = None) -> dict:
    """Return public holidays for the user's office location.

    Args:
        year: Calendar year. Defaults to the current year if omitted.
        month: Optional month (1-12) to narrow results.
    """
    ctx = _ctx()
    today: _date = ctx["today"]
    try:
        holidays = await get_lms_client().get_holiday_calendar(
            session_id=ctx["session_id"],
            location=ctx["location"],
            year=year or today.year,
            month=month,
        )
        return {"ok": True, "holidays": [_serialise_holiday(h) for h in holidays]}
    except LMSNotImplementedError as exc:
        return {"ok": False, "error": str(exc), "kind": "not_implemented"}
    except LMSError as exc:
        logger.warning("get_holiday_calendar failed: %s", exc)
        return {"ok": False, "error": str(exc)}


@tool
async def apply_leave(start_date: str, end_date: str, leave_type: str = "Annual",
                      reason: str | None = None) -> dict:
    """Submit a leave request.

    Args:
        start_date: First day of leave (ISO YYYY-MM-DD).
        end_date:   Last day of leave (inclusive, ISO YYYY-MM-DD).
        leave_type: "Annual" / "Sick" / "Casual" / etc. Default Annual.
        reason:     Optional free-text reason.
    """
    ctx = _ctx()
    try:
        req = await get_lms_client().apply_leave(
            session_id=ctx["session_id"],
            email=ctx["email"],
            start_date=start_date,
            end_date=end_date,
            leave_type=leave_type,
            reason=reason,
        )
        return {"ok": True, "request": _serialise_request(req)}
    except LMSNotImplementedError as exc:
        return {"ok": False, "error": str(exc), "kind": "not_implemented"}
    except LMSValidationError as exc:
        return {"ok": False, "error": str(exc), "kind": "validation"}
    except LMSError as exc:
        logger.warning("apply_leave failed: %s", exc)
        return {"ok": False, "error": str(exc)}


@tool
async def cancel_leave(request_id: str) -> dict:
    """Cancel an existing leave request by id.

    Args:
        request_id: The request identifier returned by ``get_pending_leaves``.
    """
    ctx = _ctx()
    try:
        await get_lms_client().cancel_leave(
            session_id=ctx["session_id"],
            email=ctx["email"],
            request_id=request_id,
        )
        return {"ok": True, "cancelled_request_id": request_id}
    except LMSNotImplementedError as exc:
        return {"ok": False, "error": str(exc), "kind": "not_implemented"}
    except LMSError as exc:
        logger.warning("cancel_leave failed: %s", exc)
        return {"ok": False, "error": str(exc)}


# ── Toolbelt exports ────────────────────────────────────────────────────

# Read-only tools the agent uses by default. These three exclusively
# back onto /api/LeaveSnapshot, so they're zero-cost beyond the first
# call within a session (cached client-side).
READ_TOOLS = [
    get_leave_snapshot,
    get_leave_balance,
    get_pending_leaves,
    get_holiday_calendar,
]

# Write tools — gated through the ReAct loop's HITL confirmation step.
# Today these always return ``not_implemented`` from the upstream.
# When the upstream wires apply / cancel, the client implementation is
# the only thing that needs to change; this list stays the same.
WRITE_TOOLS = [
    apply_leave,
    cancel_leave,
]

ALL_TOOLS = READ_TOOLS + WRITE_TOOLS
