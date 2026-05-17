"""
Stub Scorecard data source — SQLite :memory: loaded from tests/output.xlsx.

The Excel headers in the template differ slightly from the DDL column
names (spaces, %, etc.), so this loader applies an explicit mapping. The
``Period`` and ``ReportDate`` columns are not in the snapshot template,
so we synthesize them at load time using the current fiscal period.
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
from agents.scorecard.schema import SCORECARD_TABLE

logger = logging.getLogger(__name__)


# Excel header → SQL column.
SCORECARD_COLUMN_MAP: dict[str, str] = {
    "GUI":                  "GUI",
    "GPN":                  "GPN",
    "Name":                 "EmployeeName",
    "Country":              "Country",
    "SL":                   "SL",
    "SSL":                  "SSL",
    "Current rank":         "CurrentRank",
    "Role":                 "Role",
    "Additionnal role":     "AdditionalRole",        # note: header is misspelled in the template
    "GTER":                 "GTER",
    "GTER Plan":            "GTERPlan",
    "GTER Plan Achieved%":  "GTERPlanAchievedPct",
    "Global Margin":        "GlobalMargin",
    "Global Margin%":       "GlobalMarginPct",
    "Global Sales":         "GlobalSales",
    "Weighted Pipeline":    "WeightedPipeline",
    "TER":                  "TER",
    "ANSR":                 "ANSR",
    "ANSR/GTER Ratio":      "ANSRGTERRatio",
    "Eng Margin":           "EngMargin",
    "Eng Margin %":         "EngMarginPct",
    "FYTD Backlog (TER)":   "FYTDBacklogTER",
    "Total Backlog (TER)":  "TotalBacklogTER",
    "Utilization%":         "UtilizationPct",
    "Billing":              "Billing",
    "Collection":           "Collection",
    "AR":                   "AR",
    "AR Reserve":           "ARReserve",
    "Total NUI":            "TotalNUI",
    "Aged NUI above 180 days": "AgedNUIAbove180Days",
    "Aged NUI above 365 days": "AgedNUIAbove365Days",
    "Revenue Days":         "RevenueDays",
}


_DEFAULT_XLSX = Path(__file__).resolve().parents[3] / "tests" / "output.xlsx"


class StubScorecardDataSource(AnalyticalDataSource):
    """SQLite-backed Scorecard stub. EmployeeId column is synthesized from GUI."""

    backend_name: str = "stub"

    def __init__(self, xlsx_path: str | Path | None = None) -> None:
        self._xlsx_path = Path(xlsx_path) if xlsx_path else _DEFAULT_XLSX
        self._conn: sqlite3.Connection | None = None

    def _conn_lazy(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = load_sqlite_from_xlsx(
                self._xlsx_path,
                sheet_name="Scorecard_Output",
                table_name=SCORECARD_TABLE,
                column_map=SCORECARD_COLUMN_MAP,
            )
            # The DDL has ``EmployeeId`` as the canonical key and synthesizes
            # ``Period`` / ``ReportDate``. The template doesn't carry those —
            # bolt them on once so RLS predicates and Period filters work.
            try:
                conn.execute("ALTER TABLE UserScoreboard ADD COLUMN EmployeeId NUMERIC")
            except sqlite3.OperationalError:
                pass  # already added
            try:
                conn.execute("ALTER TABLE UserScoreboard ADD COLUMN Period TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE UserScoreboard ADD COLUMN ReportDate TEXT")
            except sqlite3.OperationalError:
                pass
            conn.execute("UPDATE UserScoreboard SET EmployeeId = GUI WHERE EmployeeId IS NULL")
            # Tag every row with the current default period — matches the
            # header line on the reference image ("Period: FY26 P9").
            conn.execute("UPDATE UserScoreboard SET Period = 'FY26 P9' WHERE Period IS NULL")
            conn.commit()
            self._conn = conn
        return self._conn

    async def execute_query(
        self,
        sql: str,
        params: Sequence[Any] = (),
    ) -> list[dict]:
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
