"""
Per-query telemetry log for analytical agents.

Inserts one row per (Expense / Scoreboard) query into ``QueryTelemetry``
(see ``sql/create_agent_tables.sql``). Used for offline analysis only —
the write is fire-and-forget so a slow/broken telemetry path can never
delay the user-facing response.

Usage from a node:
    asyncio.create_task(log_query({...}))

Errors are swallowed and logged at WARNING — never raised.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from services.data_db import DataDB

logger = logging.getLogger(__name__)


# Allowed status values mirror the column comment in the DDL.
_ALLOWED_STATUSES: frozenset[str] = frozenset({
    "success", "no_results", "planner_error", "sql_error", "clarified",
})


@dataclass
class QueryTelemetryRecord:
    user_id: Optional[str] = None
    agent_name: Optional[str] = None
    user_prompt: Optional[str] = None
    query_plan: Optional[dict[str, Any]] = None
    confidence_score: Optional[float] = None
    executed_sql: Optional[str] = None
    row_count: Optional[int] = None
    latency_ms: Optional[int] = None
    status: Optional[str] = None
    error_message: Optional[str] = None


_INSERT_SQL = (
    "INSERT INTO QueryTelemetry "
    "(UserId, AgentName, UserPrompt, QueryPlanJson, ConfidenceScore, "
    " ExecutedSql, RowCountReturned, LatencyMs, Status, ErrorMessage) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def _truncate(value: Optional[str], limit: int = 4000) -> Optional[str]:
    if value is None:
        return None
    s = str(value)
    if len(s) > limit:
        return s[:limit]
    return s


async def log_query(record: QueryTelemetryRecord | dict[str, Any]) -> None:
    """Fire-and-forget telemetry insert. Never raises.

    Accepts either a dataclass record or a dict with the same keys.
    """
    try:
        if isinstance(record, dict):
            rec = QueryTelemetryRecord(**{
                k: v for k, v in record.items()
                if k in QueryTelemetryRecord.__dataclass_fields__
            })
        else:
            rec = record

        status = rec.status
        if status and status not in _ALLOWED_STATUSES:
            # Don't refuse — just log the oddity.
            logger.info("query_telemetry: unknown status %r", status)

        plan_json: Optional[str] = None
        if rec.query_plan is not None:
            try:
                plan_json = json.dumps(rec.query_plan, default=str)
            except Exception:
                plan_json = None

        params = [
            _truncate(rec.user_id, 200),
            _truncate(rec.agent_name, 50),
            _truncate(rec.user_prompt, 4000),
            plan_json,
            rec.confidence_score,
            _truncate(rec.executed_sql, 4000),
            rec.row_count,
            rec.latency_ms,
            _truncate(rec.status, 30),
            _truncate(rec.error_message, 4000),
        ]

        db = DataDB()
        await db.execute(_INSERT_SQL, params)
    except Exception as exc:
        logger.warning("query_telemetry insert failed: %s", exc)


def fire_and_forget(record: QueryTelemetryRecord | dict[str, Any]) -> None:
    """Schedule ``log_query`` on the running loop without awaiting.

    Safe to call from sync contexts inside an async runtime — falls back
    silently to a no-op when no loop is available.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — best-effort skip.
        logger.debug("query_telemetry: no running loop, skipping")
        return
    loop.create_task(log_query(record))
