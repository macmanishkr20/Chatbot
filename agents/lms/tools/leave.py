"""
LangChain @tool wrappers exposed to the LLM during the LMS fetch node.

These functions are thin façades — they delegate to the active
:class:`LMSDataSource` (selected by config) and return its raw dict so the
format node can render structured output with provenance.

The LLM sees these signatures via tool-calling. Keep parameter names,
types, and docstrings stable; they are part of the LLM-facing contract.
"""
from __future__ import annotations

import logging
from typing import Optional

from langchain_core.tools import tool

from agents.lms.data_source import LMSDataSourceError
from agents.lms.data_sources import get_lms_data_source

logger = logging.getLogger(__name__)


def _error_payload(err: LMSDataSourceError, tool_name: str) -> dict:
    """Convert a data-source error into a tool-result dict the LLM can read.

    The LLM should NOT retry — the fetch node decides what to do based on the
    `error` and `retriable` flags. The format node renders a graceful message.
    """
    logger.warning("LMS tool '%s' failed: code=%s detail=%s", tool_name, err.code, err.detail)
    return {
        "ok": False,
        "tool": tool_name,
        "error": {"code": err.code, "detail": err.detail, "retriable": err.retriable},
    }


@tool
async def get_leave_balance(
    employee_id: str,
    leave_type: Optional[str] = None,
) -> dict:
    """Look up the user's remaining leave balance.

    Args:
        employee_id: Email or HRIS ID of the user (from the chat state).
        leave_type:  Optional filter — e.g. "Annual", "Sick", "Paternity".
                     When omitted, returns balances for every leave type.

    Use this for queries like:
      - "What is my leave balance?"
      - "How many annual leaves do I have left?"
      - "What's my paternity leave entitlement?"
    """
    ds = get_lms_data_source()
    try:
        result = await ds.get_leave_balance(employee_id, leave_type)
        return {"ok": True, "tool": "get_leave_balance", "data": result}
    except LMSDataSourceError as err:
        return _error_payload(err, "get_leave_balance")


@tool
async def get_leave_applications(
    employee_id: str,
    status: Optional[str] = None,
    limit: int = 10,
) -> dict:
    """List the user's leave applications, newest first.

    Args:
        employee_id: Email or HRIS ID of the user (from the chat state).
        status:      Optional filter — "Approved", "Pending", "Rejected".
        limit:       Maximum number of entries (1–50). Default 10.

    Use this for queries like:
      - "Show my leave applications"
      - "What pending leaves do I have?"
      - "List my approved leaves this year"
    """
    ds = get_lms_data_source()
    try:
        capped_limit = max(1, min(int(limit), 50))
        result = await ds.get_leave_applications(employee_id, status, capped_limit)
        return {"ok": True, "tool": "get_leave_applications", "data": result}
    except LMSDataSourceError as err:
        return _error_payload(err, "get_leave_applications")


@tool
async def get_pending_approvals(manager_id: str) -> dict:
    """List leave requests waiting for the manager to approve / reject.

    Args:
        manager_id: Email or HRIS ID of the approver (typically the
                    current user when they are in an approver role).

    Use this for queries like:
      - "Who is waiting for my approval?"
      - "Show me pending leave approvals for my team"
      - "Do I have leave requests to review?"
    """
    ds = get_lms_data_source()
    try:
        result = await ds.get_pending_approvals(manager_id)
        return {"ok": True, "tool": "get_pending_approvals", "data": result}
    except LMSDataSourceError as err:
        return _error_payload(err, "get_pending_approvals")


# Ordered list — passed to LLM via .bind_tools() in the fetch node.
LMS_TOOLS = [
    get_leave_balance,
    get_leave_applications,
    get_pending_approvals,
]
