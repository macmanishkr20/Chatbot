"""
HTTP LMS data source — calls the production LMS REST API.

Skeleton implementation. The shape is final; only the URLs / auth scheme /
JSON-to-dict mapping need to be filled in once the LMS API contract is
confirmed by the LMS team.

When endpoints are known, replace the NotImplementedError stubs with httpx
calls; do not change the method signatures. The agent code does not care
which backend it is talking to.
"""
from __future__ import annotations

import logging

from agents.lms.data_source import (
    LMSDataSource,
    LMSDataSourceError,
    make_source_block,
)
from core.config import LMS_HTTP_BASE_URL, LMS_HTTP_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class HTTPLMSDataSource(LMSDataSource):
    """HTTP REST client for the LMS API.

    Configured via ``LMS_HTTP_BASE_URL`` and ``LMS_HTTP_TIMEOUT_SECONDS``.
    Auth headers and retry strategy will be added when the contract is
    finalised. Keep the public methods aligned with the Protocol.
    """

    backend_name: str = "http"

    def __init__(self) -> None:
        if not LMS_HTTP_BASE_URL:
            logger.warning(
                "HTTPLMSDataSource constructed without LMS_HTTP_BASE_URL — "
                "calls will fail until the env var is set."
            )
        self._base_url = LMS_HTTP_BASE_URL
        self._timeout = LMS_HTTP_TIMEOUT_SECONDS

    async def get_leave_balance(
        self,
        employee_id: str,
        leave_type: str | None = None,
    ) -> dict:
        # TODO(LMS-INTEGRATION):
        #   GET {base}/employees/{employee_id}/leave-balance?leave_type=...
        #   Map response → contract shape in data_source.py docstring.
        raise LMSDataSourceError(
            code="NOT_IMPLEMENTED",
            detail="HTTP LMS backend wiring pending; set LMS_DATA_SOURCE_KIND=stub.",
            retriable=False,
        )

    async def get_leave_applications(
        self,
        employee_id: str,
        status: str | None = None,
        limit: int = 10,
    ) -> dict:
        # TODO(LMS-INTEGRATION):
        #   GET {base}/employees/{employee_id}/leave-applications?status=...&limit=N
        raise LMSDataSourceError(
            code="NOT_IMPLEMENTED",
            detail="HTTP LMS backend wiring pending; set LMS_DATA_SOURCE_KIND=stub.",
            retriable=False,
        )

    async def get_pending_approvals(self, manager_id: str) -> dict:
        # TODO(LMS-INTEGRATION):
        #   GET {base}/managers/{manager_id}/pending-approvals
        raise LMSDataSourceError(
            code="NOT_IMPLEMENTED",
            detail="HTTP LMS backend wiring pending; set LMS_DATA_SOURCE_KIND=stub.",
            retriable=False,
        )

    # Helper to keep future implementations consistent.
    def _attach_source(self, payload: dict, *, endpoint: str) -> dict:
        payload["source"] = make_source_block(
            self.backend_name,
            base_url=self._base_url or None,
            endpoint=endpoint,
        )
        return payload
