"""
Generic analytical data-source contract — shared by Expense, Scorecard, …

Two methods, both async, both narrow:
  - ``execute_query(sql, params)`` returns a list of dict rows.
  - ``backend_name`` identifies the backend for provenance footers.

The compiled SQL passed to ``execute_query`` already contains only safe
identifiers and parameter placeholders (``?``); the implementation simply
forwards to its underlying driver.

Implementations live under each agent's ``data_sources/`` package
(``stub`` for dev / CI, ``sql`` for the real Azure SQL DB). The agent
code never imports a concrete implementation directly — selection is
config-driven via a factory.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol, Sequence, runtime_checkable


class DataSourceError(Exception):
    """Wraps any failure from an analytical data source."""

    def __init__(self, code: str, detail: str, *, retriable: bool = False) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.retriable = retriable


def make_source_block(backend: str, **extra: Any) -> dict:
    """Provenance block attached to every result for audit / UX footers."""
    return {
        "backend": backend,
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **extra,
    }


@runtime_checkable
class AnalyticalDataSource(Protocol):
    """Run pre-compiled, parameterised SELECTs and return list-of-dict rows."""

    backend_name: str  # "stub" | "sql" — for telemetry & provenance

    async def execute_query(
        self,
        sql: str,
        params: Sequence[Any] = (),
    ) -> list[dict]:
        """Execute ``sql`` with ``params`` and return rows as dicts."""
        ...
