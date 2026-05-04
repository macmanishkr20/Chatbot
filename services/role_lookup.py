"""
AgentUserRoles lookup — single source of truth for analytical-agent
authorisation.

Schema (sql/create_agent_tables.sql):
    AgentUserRoles(UserId NVARCHAR(100), Role NVARCHAR(20))

Role values used by the agents:
    'user'    — sees only their own rows (default).
    'manager' — sees all rows (relaxed because the schema does not
                carry a ManagerId column we can filter on).
    'admin'   — sees all rows.

Resolution result:
    role        : the canonical role (defaults to 'user' if the user is
                  not in the table).
    scope       : 'self' | 'all' — drives whether to inject an
                  EmployeeId security predicate.
    can_see_others: convenience boolean.

The result is cached in-process for the duration of one chat session
so we don't round-trip the DB on every tool call.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal, Optional

from services.data_db import DataDB

logger = logging.getLogger(__name__)


Role = Literal["user", "manager", "admin"]
Scope = Literal["self", "all"]


@dataclass(frozen=True)
class RoleResolution:
    role: Role
    scope: Scope

    @property
    def can_see_others(self) -> bool:
        return self.scope == "all"


# ── Per-process cache. Keys: user_id (string). TTL: process lifetime. ──
# Reset by tests via _reset_role_cache(). Cache is fine here because the
# write path (admin role assignment) is rare and operationally controlled.

_cache: dict[str, RoleResolution] = {}
_cache_lock = asyncio.Lock()


async def get_role(user_id: str, *, default: Role = "user") -> RoleResolution:
    """Return the user's role + derived scope.

    Args:
        user_id: the auth-user identifier (typically email or employee
            id — whichever the supervisor stamps into state.user_id).
        default: role to assume when the user is not in the table.
    """
    if not user_id:
        return RoleResolution(role=default, scope="self")

    async with _cache_lock:
        cached = _cache.get(user_id)
    if cached is not None:
        return cached

    role: Role = default
    try:
        db = DataDB()
        row = await db.fetchone(
            "SELECT TOP 1 Role FROM AgentUserRoles WHERE LOWER(UserId) = LOWER(?)",
            [user_id],
        )
        if row:
            raw = (row.get("Role") or "").strip().lower()
            if raw in {"user", "manager", "admin"}:
                role = raw  # type: ignore[assignment]
            else:
                logger.info(
                    "AgentUserRoles: unexpected role %r for user %r — falling back to default.",
                    raw, user_id,
                )
    except Exception as exc:
        logger.warning(
            "AgentUserRoles lookup failed for %r: %s — defaulting to %r.",
            user_id, exc, default,
        )

    scope: Scope = "all" if role in {"manager", "admin"} else "self"
    resolution = RoleResolution(role=role, scope=scope)

    async with _cache_lock:
        _cache[user_id] = resolution
    return resolution


async def _reset_role_cache() -> None:
    """Test helper — clears the in-process cache."""
    async with _cache_lock:
        _cache.clear()
        _employee_id_cache.clear()


# ── EmployeeId resolution (for self-scoped RLS) ─────────────────────────
#
# AgentUserRoles per the current schema (sql/create_agent_tables.sql) does
# NOT carry an EmployeeId column — the table only has Id / UserId / Role.
# Until/unless the schema is extended with an EmployeeId mapping column,
# this lookup must fail closed: the caller (agent node) is expected to
# treat a None return as "cannot enforce row-level security for self
# scope" and refuse the query.
#
# This function probes the table for an ``EmployeeId`` column and uses it
# when present; otherwise it returns None. That keeps the helper future-
# proof when the column is added without forcing a code change.

_employee_id_cache: dict[str, Optional[str]] = {}
_employee_id_column_known: Optional[bool] = None


async def _probe_employee_id_column() -> bool:
    """Return True if AgentUserRoles has an EmployeeId column."""
    global _employee_id_column_known
    if _employee_id_column_known is not None:
        return _employee_id_column_known
    try:
        db = DataDB()
        row = await db.fetchone(
            "SELECT TOP 1 COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = 'AgentUserRoles' AND COLUMN_NAME = 'EmployeeId'",
        )
        _employee_id_column_known = row is not None
    except Exception as exc:
        logger.warning("EmployeeId column probe failed: %s", exc)
        _employee_id_column_known = False
    return _employee_id_column_known


async def resolve_employee_id(user_id: str) -> Optional[str]:
    """Look up the numeric employee id for ``user_id`` (typically email).

    Returns None when:
      * user_id is empty,
      * AgentUserRoles has no EmployeeId column in this deployment,
      * the user is not present in the table,
      * the DB lookup fails.

    Callers MUST treat None as "no RLS predicate available — fail closed
    for self-scoped queries".
    """
    if not user_id:
        return None
    async with _cache_lock:
        if user_id in _employee_id_cache:
            return _employee_id_cache[user_id]

    has_column = await _probe_employee_id_column()
    if not has_column:
        async with _cache_lock:
            _employee_id_cache[user_id] = None
        return None

    employee_id: Optional[str] = None
    try:
        db = DataDB()
        row = await db.fetchone(
            "SELECT TOP 1 EmployeeId FROM AgentUserRoles "
            "WHERE LOWER(UserId) = LOWER(?)",
            [user_id],
        )
        if row:
            raw = row.get("EmployeeId")
            if raw is not None and str(raw).strip():
                employee_id = str(raw).strip()
    except Exception as exc:
        logger.warning("resolve_employee_id failed for %r: %s", user_id, exc)

    async with _cache_lock:
        _employee_id_cache[user_id] = employee_id
    return employee_id
