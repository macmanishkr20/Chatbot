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
        """Create the loader audit tables idempotently.

        The user-facing fact tables (``UserExpenses``, ``UserScoreboard``,
        ``AgentUserRoles``) are created via ``sql/create_agent_tables.sql``
        — owned by DBAs, not by this code. We only own the ETL audit
        trails so loaders can run end-to-end without manual setup.
        """

        def _run() -> None:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
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

    async def verify_user_tables(self) -> None:
        """Raise if the user-facing tables (created via the DDL script)
        are missing. Called by the agents during cold-start to fail fast
        with a clear error rather than letting a query crash later."""

        def _run() -> list[str]:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT name
                    FROM sysobjects
                    WHERE xtype='U' AND name IN ('UserExpenses','UserScoreboard','AgentUserRoles')
                """)
                return [r[0] for r in cur.fetchall()]
            finally:
                conn.close()

        present = set(await asyncio.to_thread(_run))
        expected = {"UserExpenses", "UserScoreboard", "AgentUserRoles"}
        missing = expected - present
        if missing:
            raise DataDBError(
                f"Required tables are missing: {sorted(missing)}. "
                "Apply sql/create_agent_tables.sql against the database first.",
            )

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
