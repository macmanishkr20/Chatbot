"""
LangChain tool wrappers around services.lms_client.

Tools are split into READ-ONLY and WRITE buckets so the ReAct graph can
gate writes through a confirmation step (HITL) before they execute.

Each tool returns a JSON-serialisable dict — the ReAct loop converts
those into ``ToolMessage`` content for the next LLM turn.
"""
from __future__ import annotations

import logging
from datetime import date as _date, datetime, timedelta
from typing import Any

from langchain_core.tools import tool

from services.lms_client import (
    Holiday,
    LeaveBalance,
    LeaveRequest,
    LMSError,
    LMSValidationError,
    get_lms_client,
)

logger = logging.getLogger(__name__)


# ── Context plumbing ────────────────────────────────────────────────────
#
# Tools defined with @tool can't see the LangGraph state directly, so we
# carry the per-request identity in a contextvar set by the agent. This
# is much cleaner than threading kwargs through every tool signature.

import contextvars

_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "lms_tool_context",
    default={},
)


def set_tool_context(*, session_id: str, employee_id: str, location: str | None,
                     manager_id: str | None, today: _date) -> contextvars.Token:
    """Bind the per-call context for the LMS toolbelt. Returns a token to reset."""
    return _CONTEXT.set({
        "session_id": session_id,
        "employee_id": employee_id,
        "location": location or "ALL",
        "manager_id": manager_id,
        "today": today,
    })


def reset_tool_context(token: contextvars.Token) -> None:
    _CONTEXT.reset(token)


def _ctx() -> dict[str, Any]:
    c = _CONTEXT.get()
    if not c.get("session_id") or not c.get("employee_id"):
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


def _parse_date(value: str | _date) -> _date:
    if isinstance(value, _date):
        return value
    return datetime.fromisoformat(str(value)).date()


# ── Read-only tools ────────────────────────────────────────────────────

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
            employee_id=ctx["employee_id"],
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
            employee_id=ctx["employee_id"],
        )
        return {"ok": True, "requests": [_serialise_request(r) for r in requests]}
    except LMSError as exc:
        logger.warning("get_pending_leaves failed: %s", exc)
        return {"ok": False, "error": str(exc)}


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
    except LMSError as exc:
        logger.warning("get_holiday_calendar failed: %s", exc)
        return {"ok": False, "error": str(exc)}


# ── Write tools (must go through confirmation in the agent) ─────────────

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
        sd = _parse_date(start_date)
        ed = _parse_date(end_date)
    except ValueError:
        return {"ok": False, "error": "Invalid date format. Use YYYY-MM-DD."}
    try:
        req = await get_lms_client().apply_leave(
            session_id=ctx["session_id"],
            employee_id=ctx["employee_id"],
            start_date=sd,
            end_date=ed,
            leave_type=leave_type,
            reason=reason,
        )
        return {"ok": True, "request": _serialise_request(req)}
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
            employee_id=ctx["employee_id"],
            request_id=request_id,
        )
        return {"ok": True, "cancelled_request_id": request_id}
    except LMSError as exc:
        logger.warning("cancel_leave failed: %s", exc)
        return {"ok": False, "error": str(exc)}


# ── Recommendation tool (deterministic — no LLM) ────────────────────────

@tool
async def recommend_leave_window(days: int, prefer_long_weekends: bool = True,
                                 from_date: str | None = None,
                                 horizon_days: int = 90) -> dict:
    """Suggest leave windows that maximise time off relative to balance + holidays.

    Args:
        days: Number of leave days to take (1–14).
        prefer_long_weekends: When True, ranks options that bridge a
            holiday or weekend higher.
        from_date: Earliest date to consider (ISO YYYY-MM-DD). Defaults to
            today.
        horizon_days: Look-ahead window. Default 90 days.

    Returns up to 3 ranked windows with the *blocked* time-off count
    (calendar days from the first leave day to the day before the
    employee returns).
    """
    ctx = _ctx()
    if days < 1 or days > 14:
        return {"ok": False, "error": "days must be between 1 and 14."}

    today = _parse_date(from_date) if from_date else ctx["today"]
    horizon_end = today + timedelta(days=max(7, min(horizon_days, 365)))

    # ── Gather holidays in the horizon (single upstream call) ──
    try:
        holidays = await get_lms_client().get_holiday_calendar(
            session_id=ctx["session_id"],
            location=ctx["location"],
            year=today.year,
        )
        if horizon_end.year != today.year:
            holidays += await get_lms_client().get_holiday_calendar(
                session_id=ctx["session_id"],
                location=ctx["location"],
                year=horizon_end.year,
            )
    except LMSError as exc:
        return {"ok": False, "error": f"Could not load holidays: {exc}"}

    holiday_dates = {h.holiday_date for h in holidays}

    # ── Gather balance to make sure we don't over-recommend ──
    try:
        balances = await get_lms_client().get_leave_balance(
            session_id=ctx["session_id"],
            employee_id=ctx["employee_id"],
        )
    except LMSError:
        balances = []
    annual = next((b for b in balances if b.leave_type.lower() == "annual"), None)
    available = annual.available_days if annual else float(days)
    if days > available:
        return {
            "ok": False,
            "error": (
                f"Requested {days} day(s) but only {available:.1f} day(s) of "
                f"Annual leave available."
            ),
        }

    # ── Rank candidate windows ──
    candidates = []
    cursor = today
    while cursor <= horizon_end:
        # Build the leave window (skip weekends in the count)
        leave_days_used = 0
        d = cursor
        leave_dates: list[_date] = []
        while leave_days_used < days and d <= horizon_end:
            if d.weekday() < 5:  # Mon–Fri
                leave_dates.append(d)
                leave_days_used += 1
            d += timedelta(days=1)

        if leave_days_used < days:
            break

        first = leave_dates[0]
        last = leave_dates[-1]

        # Calendar span = from leave_start through next working day - 1 (the day before return)
        # plus any preceding/following weekend or public holiday that bridges.
        span_start = first
        span_end = last
        # Extend forward through weekends + holidays
        probe = last + timedelta(days=1)
        while probe.weekday() >= 5 or probe in holiday_dates:
            span_end = probe
            probe += timedelta(days=1)
            if (probe - last).days > 7:
                break
        # Extend backward through weekends + holidays
        probe = first - timedelta(days=1)
        while probe.weekday() >= 5 or probe in holiday_dates:
            span_start = probe
            probe -= timedelta(days=1)
            if (first - probe).days > 7:
                break

        blocked_days = (span_end - span_start).days + 1
        savings_ratio = blocked_days / max(days, 1)

        score = blocked_days + (2 if prefer_long_weekends and blocked_days > days else 0)

        candidates.append({
            "leave_start": first.isoformat(),
            "leave_end": last.isoformat(),
            "calendar_start": span_start.isoformat(),
            "calendar_end": span_end.isoformat(),
            "leave_days": days,
            "calendar_days_off": blocked_days,
            "savings_ratio": round(savings_ratio, 2),
            "_score": score,
        })

        # Step forward by ~1 week to cover variety
        cursor += timedelta(days=7)

    candidates.sort(key=lambda c: c["_score"], reverse=True)
    top = []
    for c in candidates:
        c.pop("_score", None)
        top.append(c)
        if len(top) >= 3:
            break

    return {"ok": True, "windows": top, "available_days": available}


# ── Toolbelt exports ────────────────────────────────────────────────────

READ_TOOLS = [
    get_leave_balance,
    get_pending_leaves,
    get_holiday_calendar,
    recommend_leave_window,
]

WRITE_TOOLS = [
    apply_leave,
    cancel_leave,
]

ALL_TOOLS = READ_TOOLS + WRITE_TOOLS
