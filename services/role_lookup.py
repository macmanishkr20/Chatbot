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
from typing import Literal

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
            "SELECT TOP 1 Role FROM AgentUserRoles WHERE UserId = ?",
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
