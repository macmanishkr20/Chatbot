"""
Expense data-source factory.

Reads ``core.config.EXPENSE_DATA_SOURCE_KIND`` and returns the matching impl
satisfying :class:`agents._base.sql_planner.data_source.AnalyticalDataSource`.

Backends:
  "stub" — SQLite :memory: loaded from tests/report.xlsx at first use.
            Identical query semantics to Azure SQL for the documented
            schema, so the SAME compiled SQL flows through both.
  "sql"  — pyodbc → Azure SQL (the canonical UserExpenses table).
"""
from __future__ import annotations

import logging
from functools import lru_cache

from agents._base.sql_planner.data_source import AnalyticalDataSource
from core.config import EXPENSE_DATA_SOURCE_KIND

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_expense_data_source() -> AnalyticalDataSource:
    """Return the singleton expense data source for the configured backend."""
    kind = EXPENSE_DATA_SOURCE_KIND
    logger.info("Expense data source: %s", kind)
    if kind == "stub":
        from agents.expense.data_sources.stub import StubExpenseDataSource
        return StubExpenseDataSource()
    if kind == "sql":
        from agents.expense.data_sources.sql import SQLExpenseDataSource
        return SQLExpenseDataSource()
    raise ValueError(
        f"Unknown EXPENSE_DATA_SOURCE_KIND={kind!r}. "
        f"Valid values: 'stub', 'sql'."
    )
