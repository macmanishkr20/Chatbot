"""LMS tools exposed to the LLM for tool-calling.

The tools are thin wrappers over :class:`agents.lms.data_source.LMSDataSource`
so the LLM never knows which backend it is talking to.
"""
from agents.lms.tools.leave import (
    LMS_TOOLS,
    get_leave_applications,
    get_leave_balance,
    get_pending_approvals,
)

__all__ = [
    "LMS_TOOLS",
    "get_leave_balance",
    "get_leave_applications",
    "get_pending_approvals",
]
