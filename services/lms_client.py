"""
LMS (Leave Management System) HTTP client.

Single integration surface for the 3rd-party HR/Leave system. The agent
NEVER calls HTTP directly — all calls go through this module so that:

  * auth, retries, timeouts, and error mapping live in one place,
  * a circuit breaker prevents repeated failures from hammering the
    upstream during an outage,
  * a per-session in-memory cache eliminates duplicate read calls
    during a single chat conversation,
  * the agent layer stays mockable (tests swap in a ``FakeLMSClient``).

Active endpoint (live):
    GET {LMS_BASE_URL}/api/LeaveSnapshot?email={email}
        — returns a snapshot containing balance + pending leaves +
          related metadata in a single payload. The exact response
          shape is parsed best-effort by ``_parse_snapshot()``; the
          raw JSON is also exposed so the LLM can answer questions
          the typed accessors don't anticipate.

Endpoints not yet wired by the upstream system (holidays / apply /
cancel) raise ``LMSNotImplementedError`` so the agent surfaces a clear
"not available" message instead of fabricating data.

Configuration (env or Key Vault):

  LMS_BASE_URL              base URL, e.g. http://10.151.110.162:8087
  LMS_API_KEY               optional; sent as ``X-API-Key`` if set
  LMS_TIMEOUT_MS            per-request timeout (default 8000)
  LMS_CACHE_TTL_SECONDS     read cache TTL (default 60)
  LMS_CIRCUIT_FAILS         consecutive failures before opening (default 5)
  LMS_CIRCUIT_COOLDOWN_SEC  cooldown before half-open probe (default 30)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Errors ─────────────────────────────────────────────────────────────

class LMSError(RuntimeError):
    """Base error for LMS client failures."""


class LMSAuthError(LMSError):
    """Auth/identity problem with the upstream call."""


class LMSUpstreamError(LMSError):
    """Upstream returned 5xx or unparsable response."""


class LMSValidationError(LMSError):
    """Upstream returned 4xx for a request that we should fix locally
    (e.g. invalid date range)."""


class LMSCircuitOpen(LMSError):
    """Circuit breaker is open — we refused to call upstream."""


class LMSNotImplementedError(LMSError):
    """Capability is not yet exposed by the upstream HR system."""


# ── Circuit breaker ────────────────────────────────────────────────────

@dataclass
class _CircuitBreaker:
    fail_threshold: int = 5
    cooldown_sec: float = 30.0
    failures: int = 0
    opened_at: float | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def before_call(self) -> None:
        async with self._lock:
            if self.opened_at is None:
                return
            elapsed = time.monotonic() - self.opened_at
            if elapsed >= self.cooldown_sec:
                self.opened_at = None
                self.failures = 0
                return
            raise LMSCircuitOpen(
                f"LMS circuit breaker is open ({elapsed:.1f}s elapsed of "
                f"{self.cooldown_sec:.0f}s cooldown).",
            )

    async def on_success(self) -> None:
        async with self._lock:
            self.failures = 0
            self.opened_at = None

    async def on_failure(self) -> None:
        async with self._lock:
            self.failures += 1
            if self.failures >= self.fail_threshold:
                self.opened_at = time.monotonic()
                logger.warning(
                    "LMS circuit breaker OPEN after %d consecutive failures.",
                    self.failures,
                )


# ── TTL cache ──────────────────────────────────────────────────────────

@dataclass
class _CachedEntry:
    value: Any
    expires_at: float


class _TTLCache:
    def __init__(self) -> None:
        self._data: dict[tuple, _CachedEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: tuple) -> Any | None:
        async with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            if entry.expires_at <= time.monotonic():
                self._data.pop(key, None)
                return None
            return entry.value

    async def set(self, key: tuple, value: Any, ttl: float) -> None:
        async with self._lock:
            self._data[key] = _CachedEntry(value=value, expires_at=time.monotonic() + ttl)

    async def invalidate(self, prefix: tuple) -> None:
        async with self._lock:
            keys = [k for k in self._data if k[:len(prefix)] == prefix]
            for k in keys:
                self._data.pop(k, None)


# ── Typed projections of the leave snapshot ────────────────────────────

@dataclass
class LeaveBalance:
    leave_type: str
    available_days: float
    accrued_days: float
    used_days: float
    pending_days: float


@dataclass
class LeaveRequest:
    request_id: str
    employee_id: str
    leave_type: str
    start_date: date
    end_date: date
    days: float
    status: str  # pending / approved / rejected / cancelled
    reason: str | None = None
    submitted_at: datetime | None = None


@dataclass
class Holiday:
    name: str
    holiday_date: date
    location: str
    is_optional: bool = False


# ── Snapshot parsing ───────────────────────────────────────────────────

# The upstream payload shape is not formally documented. We parse it
# defensively, accepting common variants:
#
#   { "balances": [ { "leaveType": "...", "available": ..., ... }, ... ] }
#   { "leaveBalances": [ ... ] }
#   { "AnnualBalance": ..., "SickBalance": ... }
#
# whichever appears, plus a `raw` echo so the LLM can read fields we
# didn't anticipate.

def _to_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _ci_get(d: dict, *keys: str, default: Any = None) -> Any:
    """Case-insensitive dict lookup over the supplied keys."""
    if not isinstance(d, dict):
        return default
    lookup = {k.lower(): v for k, v in d.items()}
    for k in keys:
        v = lookup.get(k.lower())
        if v is not None:
            return v
    return default


def _parse_snapshot_balances(snapshot: dict) -> list[LeaveBalance]:
    """Pull a list of LeaveBalance from a snapshot payload."""
    out: list[LeaveBalance] = []

    # ── Variant A: explicit list of balance items ──
    items = _ci_get(snapshot, "balances", "leaveBalances", "leave_balances")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            out.append(LeaveBalance(
                leave_type=str(_ci_get(item, "leaveType", "leave_type", "type", default="Annual")),
                available_days=_to_float(_ci_get(item, "available", "availableDays", "balance", "remaining")),
                accrued_days=_to_float(_ci_get(item, "accrued", "accruedDays", "entitlement", "total")),
                used_days=_to_float(_ci_get(item, "used", "usedDays", "consumed", "taken")),
                pending_days=_to_float(_ci_get(item, "pending", "pendingDays", "inApproval")),
            ))
        if out:
            return out

    # ── Variant B: flat <Type>Balance fields ──
    flat_types = ["Annual", "Sick", "Casual", "Maternity", "Paternity", "Compassionate"]
    for t in flat_types:
        bal = _ci_get(snapshot, f"{t}Balance", f"{t.lower()}Balance")
        if bal is not None:
            out.append(LeaveBalance(
                leave_type=t,
                available_days=_to_float(bal),
                accrued_days=_to_float(_ci_get(snapshot, f"{t}Entitlement", f"{t.lower()}Entitlement", default=bal)),
                used_days=_to_float(_ci_get(snapshot, f"{t}Used", f"{t.lower()}Used", default=0)),
                pending_days=_to_float(_ci_get(snapshot, f"{t}Pending", f"{t.lower()}Pending", default=0)),
            ))
    return out


def _parse_snapshot_requests(snapshot: dict) -> list[LeaveRequest]:
    """Pull a list of LeaveRequest from a snapshot payload."""
    items = _ci_get(snapshot, "pendingRequests", "leaveRequests", "requests", "pending_leaves")
    if not isinstance(items, list):
        return []

    def _d(value: Any) -> date:
        if isinstance(value, date):
            return value
        if value is None:
            return date.today()
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
        except ValueError:
            return date.today()

    out: list[LeaveRequest] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        submitted = _ci_get(item, "submittedAt", "createdAt", "submitted_at")
        try:
            submitted_dt = (
                datetime.fromisoformat(str(submitted).replace("Z", "+00:00"))
                if submitted else None
            )
        except ValueError:
            submitted_dt = None
        out.append(LeaveRequest(
            request_id=str(_ci_get(item, "id", "requestId", "request_id", default="")),
            employee_id=str(_ci_get(item, "employeeId", "employee_id", default="")),
            leave_type=str(_ci_get(item, "leaveType", "leave_type", "type", default="Annual")),
            start_date=_d(_ci_get(item, "startDate", "start_date", "from")),
            end_date=_d(_ci_get(item, "endDate", "end_date", "to")),
            days=_to_float(_ci_get(item, "days", "duration", "totalDays")),
            status=str(_ci_get(item, "status", "state", default="pending")).lower(),
            reason=_ci_get(item, "reason", "comments"),
            submitted_at=submitted_dt,
        ))
    return out


# ── Client ─────────────────────────────────────────────────────────────

class LMSClient:
    """Singleton facade for the upstream Leave Management System.

    The active endpoint exposes a single ``LeaveSnapshot`` per email.
    Read accessors (balance / pending) extract from that snapshot;
    write accessors (apply / cancel) and holiday lookups are not yet
    wired and raise ``LMSNotImplementedError``.
    """

    _instance: "LMSClient | None" = None

    def __new__(cls) -> "LMSClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialised", False):
            return
        self._base_url = (os.getenv("LMS_BASE_URL") or "").rstrip("/")
        self._api_key = os.getenv("LMS_API_KEY") or ""
        self._timeout_ms = int(os.getenv("LMS_TIMEOUT_MS", "8000"))
        self._cache_ttl = float(os.getenv("LMS_CACHE_TTL_SECONDS", "60"))
        self._cache = _TTLCache()
        self._breaker = _CircuitBreaker(
            fail_threshold=int(os.getenv("LMS_CIRCUIT_FAILS", "5")),
            cooldown_sec=float(os.getenv("LMS_CIRCUIT_COOLDOWN_SEC", "30")),
        )
        self._stub_mode = not self._base_url
        if self._stub_mode:
            logger.info(
                "LMSClient: LMS_BASE_URL is empty — running in stub mode "
                "(returns deterministic sample data). Set LMS_BASE_URL to "
                "wire the real HR system.",
            )
        self._initialised = True

    # ── Public API ─────────────────────────────────────────────────────

    async def get_leave_snapshot(
        self,
        *,
        session_id: str,
        email: str,
    ) -> dict:
        """Return the raw LeaveSnapshot JSON for an employee email.

        Cached per (session_id, email) for ``LMS_CACHE_TTL_SECONDS``.
        The agent's read tools project from this single payload so we
        only round-trip the upstream once per chat session.
        """
        if not email:
            raise LMSValidationError("email is required for LeaveSnapshot.")

        cache_key = (session_id, "snapshot", email.lower())
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        body = await self._call(
            "GET",
            "/api/LeaveSnapshot",
            params={"email": email},
            stub=self._stub_snapshot,
        )
        # Some servers wrap the payload in {"data": {...}}; flatten when seen.
        if isinstance(body, dict) and isinstance(body.get("data"), dict) and "balances" not in body:
            body = body["data"]

        await self._cache.set(cache_key, body, ttl=self._cache_ttl)
        return body

    async def get_leave_balance(
        self,
        *,
        session_id: str,
        email: str,
        leave_type: str | None = None,
    ) -> list[LeaveBalance]:
        snapshot = await self.get_leave_snapshot(session_id=session_id, email=email)
        balances = _parse_snapshot_balances(snapshot)
        if leave_type:
            wanted = leave_type.strip().lower()
            balances = [b for b in balances if b.leave_type.lower() == wanted]
        return balances

    async def get_pending_leaves(
        self,
        *,
        session_id: str,
        email: str,
    ) -> list[LeaveRequest]:
        snapshot = await self.get_leave_snapshot(session_id=session_id, email=email)
        return _parse_snapshot_requests(snapshot)

    async def get_holiday_calendar(self, **_kwargs) -> list[Holiday]:
        raise LMSNotImplementedError(
            "Holiday calendar lookup is not yet wired — only LeaveSnapshot "
            "is available right now.",
        )

    async def apply_leave(self, **_kwargs) -> LeaveRequest:
        raise LMSNotImplementedError(
            "Leave application via the chatbot is not yet wired — please "
            "submit through the regular HR portal for now.",
        )

    async def cancel_leave(self, **_kwargs) -> bool:
        raise LMSNotImplementedError(
            "Leave cancellation via the chatbot is not yet wired — please "
            "cancel through the regular HR portal for now.",
        )

    # ── Stub (used when LMS_BASE_URL is unset — local/dev rollout) ─────

    @staticmethod
    def _stub_snapshot(method: str, path: str, params: dict | None, **_) -> dict:
        return {
            "email": (params or {}).get("email", ""),
            "balances": [
                {"leaveType": "Annual",  "available": 18.0, "accrued": 25.0, "used": 7.0, "pending": 0.0},
                {"leaveType": "Sick",    "available": 10.0, "accrued": 10.0, "used": 0.0, "pending": 0.0},
                {"leaveType": "Casual",  "available": 5.0,  "accrued": 5.0,  "used": 0.0, "pending": 0.0},
            ],
            "pendingRequests": [],
            "_stub": True,
        }

    # ── Core HTTP call with retries + breaker ──────────────────────────

    async def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        headers: dict | None = None,
        stub=None,
        max_retries: int = 2,
    ) -> dict:
        if self._stub_mode:
            if stub is None:
                raise LMSError(
                    f"No upstream configured and no stub for {method} {path}",
                )
            return stub(method=method, path=path, params=params, json_body=json_body)

        await self._breaker.before_call()

        try:
            import httpx
        except ImportError as exc:
            raise LMSError(
                "httpx is required to call the upstream LMS. "
                "Install it with `pip install httpx`.",
            ) from exc

        request_headers = {"Accept": "application/json"}
        if json_body is not None:
            request_headers["Content-Type"] = "application/json"
        if self._api_key:
            request_headers["X-API-Key"] = self._api_key
        if headers:
            request_headers.update(headers)

        url = f"{self._base_url}{path}"
        timeout = httpx.Timeout(self._timeout_ms / 1000.0)

        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.request(
                        method=method,
                        url=url,
                        params=params,
                        json=json_body,
                        headers=request_headers,
                    )
                if resp.status_code in (401, 403):
                    raise LMSAuthError(f"Auth failed ({resp.status_code}) for {method} {path}.")
                if 400 <= resp.status_code < 500:
                    raise LMSValidationError(
                        f"Upstream rejected {method} {path}: {resp.status_code} {resp.text[:300]}",
                    )
                if resp.status_code >= 500:
                    raise LMSUpstreamError(
                        f"Upstream {resp.status_code} for {method} {path}: {resp.text[:300]}",
                    )
                try:
                    body = resp.json()
                except json.JSONDecodeError as exc:
                    raise LMSUpstreamError(f"Non-JSON response from {url}") from exc
                await self._breaker.on_success()
                return body if isinstance(body, dict) else {"data": body}
            except (LMSValidationError, LMSAuthError):
                raise
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "LMS call failed (attempt %d/%d) %s %s: %s",
                    attempt + 1, max_retries + 1, method, path, exc,
                )
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue

        await self._breaker.on_failure()
        raise LMSUpstreamError(
            f"Upstream call failed after {max_retries + 1} attempts: {last_exc}",
        )


def get_lms_client() -> LMSClient:
    """Convenience accessor — agents and tools should call this, not LMSClient()."""
    return LMSClient()
