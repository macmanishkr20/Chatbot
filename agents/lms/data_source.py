"""
LMS data-source contract.

Defines the abstract interface that every LMS backend must implement.
Implementations live under ``agents/lms/data_sources/`` (stub, http, sql, …).

The contract is intentionally narrow and read-only for v1. Write operations
(apply leave, approve / reject) will be added in a later phase behind an
explicit user-confirmation gate.

Design notes:
  - Returns plain dicts (no ORM coupling) so callers / tools / format nodes
    can JSON-serialise without converters.
  - Each result includes a `source` block with backend identity and a UTC
    timestamp. Downstream renderers MUST surface this as provenance.
  - Errors are raised as :class:`LMSDataSourceError`. The fetch node catches
    and renders a graceful fallback — never swallow silently.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable


# ── Errors ────────────────────────────────────────────────────────────────────

class LMSDataSourceError(Exception):
    """Wraps any failure from an LMS backend (HTTP, SQL, stub).

    Attributes:
        retriable: True when a transient failure (timeout, 5xx) — caller MAY
                   retry. False when permanent (404, 403, bad input).
        code:      Short stable identifier for telemetry / metrics.
        detail:    Free-form description; not shown to end user.
    """

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        retriable: bool = False,
    ) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.retriable = retriable


# ── Helpers for implementations ───────────────────────────────────────────────

def make_source_block(backend: str, **extra: Any) -> dict:
    """Return a uniform `source` block to attach to every result.

    Every LMS data-source response embeds this so downstream code can show
    provenance ("Source: HRIS · as of 2026-05-16 14:22 UTC") without
    knowing which backend produced it.
    """
    return {
        "backend": backend,
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **extra,
    }


# ── Protocol ──────────────────────────────────────────────────────────────────

@runtime_checkable
class LMSDataSource(Protocol):
    """Read-only LMS contract. v1 covers three sub-intents.

    All methods are async to keep call sites consistent regardless of whether
    the backend is HTTP (naturally async) or SQL (run in a thread pool).
    """

    backend_name: str  # "stub" | "http" | "sql" — for telemetry & provenance

    async def get_leave_balance(
        self,
        employee_id: str,
        leave_type: str | None = None,
    ) -> dict:
        """Remaining balance for the user, optionally filtered by leave_type.

        Returns:
            {
              "employee_id": str,
              "as_of_year": int,
              "balances": [
                {"leave_type": "Annual", "entitled": 25.0, "used": 12.5,
                 "remaining": 12.5, "unit": "days"},
                ...
              ],
              "source": {"backend": "...", "as_of": "..."}
            }
        """
        ...

    async def get_leave_applications(
        self,
        employee_id: str,
        status: str | None = None,
        limit: int = 10,
    ) -> dict:
        """Recent leave applications for the user, newest first.

        Returns:
            {
              "employee_id": str,
              "applications": [
                {"id": "...", "leave_type": "...", "from": "YYYY-MM-DD",
                 "to": "YYYY-MM-DD", "days": float, "status": "Approved|Pending|Rejected"},
                ...
              ],
              "source": {...}
            }
        """
        ...

    async def get_pending_approvals(self, manager_id: str) -> dict:
        """Leave requests awaiting approval by this manager.

        Returns:
            {
              "manager_id": str,
              "approvals": [
                {"id": "...", "applicant": "...", "leave_type": "...",
                 "from": "YYYY-MM-DD", "to": "YYYY-MM-DD", "days": float,
                 "submitted_at": "ISO-8601"},
                ...
              ],
              "source": {...}
            }
        """
        ...
