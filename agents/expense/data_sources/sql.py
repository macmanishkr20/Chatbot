"""
Azure SQL Expense data source (production).

Skeleton — the SQLChatClient pattern in ``infrastructure/azure/sql/client.py``
holds the connection strategy (managed identity, fallback, retry). When
the UserExpenses table is provisioned, plug the connection string in and
remove the NotImplementedError.

The compiled SQL produced by ``agents/_base/sql_planner/compiler.py`` is
already SQL-Server flavour (TOP, parameterised ``?`` placeholders) so no
transformation is needed here — just forward to pyodbc.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Sequence

from agents._base.sql_planner.data_source import (
    AnalyticalDataSource,
    DataSourceError,
)

logger = logging.getLogger(__name__)


class SQLExpenseDataSource(AnalyticalDataSource):
    """pyodbc → Azure SQL ``UserExpenses`` table."""

    backend_name: str = "sql"

    def __init__(self) -> None:
        # Lazy import — keeps the stub path importable on machines without
        # the unixodbc driver installed.
        from infrastructure.azure.sql.client import SQLChatClient
        self._client = SQLChatClient()

    async def execute_query(
        self,
        sql: str,
        params: Sequence[Any] = (),
    ) -> list[dict]:
        def _run() -> list[dict]:
            try:
                conn = self._client._get_connection()
                cur = conn.cursor()
                try:
                    cur.execute(sql, list(params))
                    cols = [d[0] for d in cur.description] if cur.description else []
                    rows = cur.fetchall()
                    return [dict(zip(cols, r)) for r in rows]
                finally:
                    cur.close()
                    conn.close()
            except Exception as e:
                raise DataSourceError(
                    code="SQL_ERROR",
                    detail=f"{type(e).__name__}: {e}",
                    retriable=True,
                ) from e

        return await asyncio.to_thread(_run)
