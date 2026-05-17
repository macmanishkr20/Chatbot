"""
Stub Expense data source — SQLite :memory: loaded from tests/report.xlsx.

The stub is functionally a real SQL backend. The same compiled SQL the
Azure SQL backend would execute also runs here, so end-to-end tests
exercise the predicate planner exactly the way production will.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path
from typing import Any, Sequence

from agents._base.sql_planner.data_source import (
    AnalyticalDataSource,
    DataSourceError,
)
from agents._base.sql_planner.sqlite_loader import (
    load_sqlite_from_xlsx,
    sqlserver_to_sqlite,
)
from agents.expense.schema import EXPENSE_TABLE

logger = logging.getLogger(__name__)


# Excel header → SQL column. Headers not in this map are dropped.
EXPENSE_COLUMN_MAP: dict[str, str] = {
    "Country Name":               "CountryName",
    "Country Code":               "CountryCode",
    "Company Code":               "CompanyCode",
    "Company Code Description":   "CompanyCodeDescription",
    "Cost Center ID":             "CostCenterId",
    "Cost Center":                "CostCenter",
    "Employee ID":                "EmployeeId",
    "Employee Name":              "EmployeeName",
    "Home Address":               "HomeAddress",
    "Employee Rank - Description": "EmployeeRank",
    "Report ID":                  "ReportId",
    "Report Key":                 "ReportKey",
    "Report Name":                "ReportName",
    "Policy":                     "Policy",
    "Approval Status":            "ApprovalStatus",
    "Approved By":                "ApprovedBy",
    "Payment Status":             "PaymentStatus",
    "Trip Start Date":            "TripStartDate",
    "Trip End Date":              "TripEndDate",
    "Original Submission Date/Time": "OriginalSubmissionDateTime",
    "Last Submitted Date/Time":    "LastSubmittedDateTime",
    "Transaction Date":           "TransactionDate",
    "Expense Type":               "ExpenseType",
    "Expense Sub Type 1":         "ExpenseSubType1",
    "Expense Sub Type 2":         "ExpenseSubType2",
    "Origin":                     "Origin",
    "Destination":                "Destination",
    "From Date":                  "FromDate",
    "To Date":                    "ToDate",
    "Business Purpose":           "BusinessPurpose",
    "Original Reimbursement Amount": "OriginalReimbursementAmount",
    "Reimbursement Amount":       "ReimbursementAmount",
    "Reimbursement Currency":     "ReimbursementCurrency",
    "Transaction Amount":         "TransactionAmount",
    "Transaction Currency":       "TransactionCurrency",
    "Work Location Country":      "WorkLocationCountry",
    "Work Location Region":       "WorkLocationRegion",
    "Work Location City":         "WorkLocationCity",
    "Country of Purchase":        "CountryOfPurchase",
    "Region of Purchase":         "RegionOfPurchase",
    "City of Purchase":           "CityOfPurchase",
    "Vendor":                     "Vendor",
    "GL account":                 "GLAccount",
    "Engagement Name":            "EngagementName",
    "Engagement Code with Activity": "EngagementCode",
    "Engagement Percentage":      "EngagementPercentage",
    "Transaction Type":           "TransactionType",
    "# of Attendees":             "NumberOfAttendees",
    "Trip Over 3 Months":         "TripOver3Months",
}


_DEFAULT_XLSX = Path(__file__).resolve().parents[3] / "tests" / "report.xlsx"


class StubExpenseDataSource(AnalyticalDataSource):
    """SQLite-backed stub. Identical interface to the production SQL impl."""

    backend_name: str = "stub"

    def __init__(self, xlsx_path: str | Path | None = None) -> None:
        self._xlsx_path = Path(xlsx_path) if xlsx_path else _DEFAULT_XLSX
        self._conn: sqlite3.Connection | None = None

    def _conn_lazy(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = load_sqlite_from_xlsx(
                self._xlsx_path,
                sheet_name="page",
                table_name=EXPENSE_TABLE,
                column_map=EXPENSE_COLUMN_MAP,
            )
        return self._conn

    async def execute_query(
        self,
        sql: str,
        params: Sequence[Any] = (),
    ) -> list[dict]:
        """Run a compiled SELECT through SQLite (off-thread)."""
        def _run() -> list[dict]:
            conn = self._conn_lazy()
            sqlite_sql = sqlserver_to_sqlite(sql)
            try:
                cur = conn.execute(sqlite_sql, list(params))
                rows = cur.fetchall()
                return [dict(r) for r in rows]
            except sqlite3.Error as e:
                raise DataSourceError(
                    code="SQLITE_ERROR",
                    detail=f"{e} | sql={sqlite_sql!r} params={list(params)!r}",
                    retriable=False,
                ) from e

        return await asyncio.to_thread(_run)
