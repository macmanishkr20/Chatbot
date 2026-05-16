"""
SQL LMS data source — direct queries against the HRIS database.

Skeleton for the future when LMS data is consumed via SQL instead of HTTP.
Same Protocol, same agent code — only this file changes.

Wiring plan:
  - Use the existing infrastructure.azure.sql.connection helper to fetch a
    pooled connection.
  - Run queries in a thread pool (asyncio.to_thread) since pyodbc is
    synchronous.
  - Map cursor rows to the dict shape documented in data_source.py.
  - On constraint / driver failures raise LMSDataSourceError with
    retriable=False; on transient connection errors raise retriable=True.
"""
from __future__ import annotations

from agents.lms.data_source import LMSDataSource, LMSDataSourceError


class SQLLMSDataSource(LMSDataSource):
    """Placeholder. Implement when LMS table contract is finalised."""

    backend_name: str = "sql"

    async def get_leave_balance(
        self,
        employee_id: str,
        leave_type: str | None = None,
    ) -> dict:
        raise LMSDataSourceError(
            code="NOT_IMPLEMENTED",
            detail="SQL LMS backend not yet implemented; set LMS_DATA_SOURCE_KIND=stub.",
            retriable=False,
        )

    async def get_leave_applications(
        self,
        employee_id: str,
        status: str | None = None,
        limit: int = 10,
    ) -> dict:
        raise LMSDataSourceError(
            code="NOT_IMPLEMENTED",
            detail="SQL LMS backend not yet implemented; set LMS_DATA_SOURCE_KIND=stub.",
            retriable=False,
        )

    async def get_pending_approvals(self, manager_id: str) -> dict:
        raise LMSDataSourceError(
            code="NOT_IMPLEMENTED",
            detail="SQL LMS backend not yet implemented; set LMS_DATA_SOURCE_KIND=stub.",
            retriable=False,
        )
