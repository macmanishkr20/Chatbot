"""
Data DB client — shared Azure SQL access for the analytical agents
(Expense, Scoreboard, …).

Kept separate from ``services.sql_client`` (which owns the chat-history
schema) so the analytical schema can evolve independently and so a
read-only credential can be wired in later for the agent path.

Tables (created idempotently by ``DataDB.ensure()``):
  ExpenseCategories  (lookup; seeded with Excel-derived names on import)
  Expenses           (analytical fact table — agent queries hit this)
  Scoreboards        (per-employee performance metric facts)
  ExpenseImportRuns  (audit trail of Excel loads)
  ScoreboardImportRuns

Design notes:
  * Connection string is reused from ``config.MSSQL_CONNECTION_STRING`` —
    no new infra. A future read-only credential just swaps the conn-str.
  * All writes go through this module; agents only read via
    ``DataDB.fetchall(sql, params)``.
  * Async wrappers via ``asyncio.to_thread`` so calls don't block the
    event loop.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Sequence

import pyodbc

from config import MSSQL_CONNECTION_STRING

logger = logging.getLogger(__name__)


class DataDBError(RuntimeError):
    """Raised for any data-DB operation failure."""


class DataDB:
    """Singleton facade for the analytical SQL data store."""

    _instance: Optional["DataDB"] = None

    def __new__(cls) -> "DataDB":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        # Re-init guard — singleton wakes up once
        if getattr(self, "_initialised", False):
            return
        self._connection_string = MSSQL_CONNECTION_STRING
        if not self._connection_string:
            raise DataDBError(
                "MSSQL_CONNECTION_STRING is not configured — DataDB cannot start.",
            )
        self._initialised = True

    # ── Low-level connection helpers ──

    def _get_connection(self) -> pyodbc.Connection:
        return pyodbc.connect(self._connection_string)

    async def ensure(self) -> None:
        """Create / migrate analytical tables idempotently."""

        def _run() -> None:
            conn = self._get_connection()
            try:
                cur = conn.cursor()

                # ── ExpenseCategories ──
                cur.execute("""
                    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='ExpenseCategories' AND xtype='U')
                    CREATE TABLE ExpenseCategories (
                        CategoryId      INT IDENTITY(1,1) PRIMARY KEY,
                        Name            NVARCHAR(255) NOT NULL UNIQUE,
                        ParentGroup     NVARCHAR(128) NULL,
                        TaxonomyPath    NVARCHAR(512) NULL,
                        IsActive        BIT NOT NULL DEFAULT 1,
                        CreatedAt       DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
                        ModifiedAt      DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
                    )
                """)

                # ── Expenses (the analytical fact table) ──
                cur.execute("""
                    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Expenses' AND xtype='U')
                    CREATE TABLE Expenses (
                        ExpenseId         BIGINT IDENTITY(1,1) PRIMARY KEY,
                        EmployeeId        NVARCHAR(64)  NOT NULL,
                        EmployeeName      NVARCHAR(255) NULL,
                        ManagerId         NVARCHAR(64)  NULL,
                        Department        NVARCHAR(128) NULL,
                        Location          NVARCHAR(128) NULL,
                        ExpenseDate       DATE          NOT NULL,
                        FiscalYear        NVARCHAR(8)   NOT NULL,
                        FiscalQuarter     NVARCHAR(8)   NOT NULL,
                        CategoryId        INT           NULL REFERENCES ExpenseCategories(CategoryId),
                        CategoryName      NVARCHAR(255) NULL,
                        Vendor            NVARCHAR(255) NULL,
                        Description       NVARCHAR(1024) NULL,
                        Amount            DECIMAL(18,2) NOT NULL,
                        Currency          CHAR(3)       NOT NULL DEFAULT 'USD',
                        AmountUsd         DECIMAL(18,2) NOT NULL,
                        Status            NVARCHAR(32)  NOT NULL DEFAULT 'submitted',
                        ReceiptUrl        NVARCHAR(512) NULL,
                        SourceFile        NVARCHAR(255) NULL,
                        SourceRow         INT           NULL,
                        DedupeKey         NVARCHAR(256) NOT NULL,
                        ImportedAt        DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
                        IsDeleted         BIT           NOT NULL DEFAULT 0
                    )
                """)
                cur.execute("""
                    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='UX_Expenses_DedupeKey' AND object_id=OBJECT_ID('Expenses'))
                    CREATE UNIQUE INDEX UX_Expenses_DedupeKey ON Expenses(DedupeKey)
                """)
                cur.execute("""
                    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_Expenses_Employee_FY' AND object_id=OBJECT_ID('Expenses'))
                    CREATE INDEX IX_Expenses_Employee_FY ON Expenses(EmployeeId, FiscalYear)
                """)
                cur.execute("""
                    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_Expenses_Date' AND object_id=OBJECT_ID('Expenses'))
                    CREATE INDEX IX_Expenses_Date ON Expenses(ExpenseDate)
                """)
                cur.execute("""
                    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_Expenses_Category' AND object_id=OBJECT_ID('Expenses'))
                    CREATE INDEX IX_Expenses_Category ON Expenses(CategoryId)
                """)

                # ── Scoreboards (Phase 3) ──
                cur.execute("""
                    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Scoreboards' AND xtype='U')
                    CREATE TABLE Scoreboards (
                        ScoreboardId      BIGINT IDENTITY(1,1) PRIMARY KEY,
                        EmployeeId        NVARCHAR(64)  NOT NULL,
                        EmployeeName      NVARCHAR(255) NULL,
                        ManagerId         NVARCHAR(64)  NULL,
                        Department        NVARCHAR(128) NULL,
                        Location          NVARCHAR(128) NULL,
                        FiscalYear        NVARCHAR(8)   NOT NULL,
                        FiscalQuarter     NVARCHAR(8)   NULL,
                        MetricName        NVARCHAR(128) NOT NULL,
                        Score             DECIMAL(8,2)  NOT NULL,
                        MaxScore          DECIMAL(8,2)  NULL,
                        RankInGroup       INT           NULL,
                        Notes             NVARCHAR(512) NULL,
                        SourceFile        NVARCHAR(255) NULL,
                        SourceRow         INT           NULL,
                        DedupeKey         NVARCHAR(256) NOT NULL,
                        ImportedAt        DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
                        IsDeleted         BIT           NOT NULL DEFAULT 0
                    )
                """)
                cur.execute("""
                    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='UX_Scoreboards_DedupeKey' AND object_id=OBJECT_ID('Scoreboards'))
                    CREATE UNIQUE INDEX UX_Scoreboards_DedupeKey ON Scoreboards(DedupeKey)
                """)
                cur.execute("""
                    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_Scoreboards_Employee_FY' AND object_id=OBJECT_ID('Scoreboards'))
                    CREATE INDEX IX_Scoreboards_Employee_FY ON Scoreboards(EmployeeId, FiscalYear)
                """)
                cur.execute("""
                    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_Scoreboards_Metric' AND object_id=OBJECT_ID('Scoreboards'))
                    CREATE INDEX IX_Scoreboards_Metric ON Scoreboards(MetricName)
                """)

                # ── Audit trails ──
                cur.execute("""
                    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='ExpenseImportRuns' AND xtype='U')
                    CREATE TABLE ExpenseImportRuns (
                        RunId        BIGINT IDENTITY(1,1) PRIMARY KEY,
                        SourceFile   NVARCHAR(255) NOT NULL,
                        StartedAt    DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
                        FinishedAt   DATETIME2 NULL,
                        RowsRead     INT NULL,
                        RowsInserted INT NULL,
                        RowsSkipped  INT NULL,
                        Status       NVARCHAR(32) NOT NULL DEFAULT 'running',
                        ErrorMessage NVARCHAR(2048) NULL,
                        TriggeredBy  NVARCHAR(256) NULL
                    )
                """)
                cur.execute("""
                    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='ScoreboardImportRuns' AND xtype='U')
                    CREATE TABLE ScoreboardImportRuns (
                        RunId        BIGINT IDENTITY(1,1) PRIMARY KEY,
                        SourceFile   NVARCHAR(255) NOT NULL,
                        StartedAt    DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
                        FinishedAt   DATETIME2 NULL,
                        RowsRead     INT NULL,
                        RowsInserted INT NULL,
                        RowsSkipped  INT NULL,
                        Status       NVARCHAR(32) NOT NULL DEFAULT 'running',
                        ErrorMessage NVARCHAR(2048) NULL,
                        TriggeredBy  NVARCHAR(256) NULL
                    )
                """)

                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_run)

    # ── Read API ──

    async def fetchall(self, sql: str, params: Sequence[Any] | None = None) -> list[dict]:
        """Execute a parameterised SELECT and return list-of-dicts.

        Used by the predicate-tree compiler. SQL is generated by trusted
        code, never by the LLM directly.
        """
        params = params or ()

        def _run() -> list[dict]:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute(sql, params)
                cols = [c[0] for c in cur.description] if cur.description else []
                rows = cur.fetchall()
                return [dict(zip(cols, row)) for row in rows]
            finally:
                conn.close()

        return await asyncio.to_thread(_run)

    async def fetchone(self, sql: str, params: Sequence[Any] | None = None) -> dict | None:
        rows = await self.fetchall(sql, params)
        return rows[0] if rows else None

    # ── Write API (only the ETL loaders use this) ──

    async def execute_many(self, sql: str, rows: list[Sequence[Any]]) -> int:
        """Bulk insert / update. Returns affected row count."""
        if not rows:
            return 0

        def _run() -> int:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.fast_executemany = True
                cur.executemany(sql, rows)
                conn.commit()
                return cur.rowcount or 0
            finally:
                conn.close()

        return await asyncio.to_thread(_run)

    async def execute(self, sql: str, params: Sequence[Any] | None = None) -> int:
        params = params or ()

        def _run() -> int:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute(sql, params)
                conn.commit()
                return cur.rowcount or 0
            finally:
                conn.close()

        return await asyncio.to_thread(_run)
