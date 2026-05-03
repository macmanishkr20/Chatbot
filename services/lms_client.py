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

Configuration (env or Key Vault, all optional during early rollout):

  LMS_BASE_URL              base URL, e.g. https://hr.example.com/api/v1
  LMS_API_KEY               API key sent as ``X-API-Key``
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


# ── Circuit breaker ────────────────────────────────────────────────────

@dataclass
class _CircuitBreaker:
    """Simple async-safe failure-window breaker.

    Closed → calls flow.
    Open   → calls fail fast with LMSCircuitOpen for ``cooldown_sec``.
    Half-open probe → first call after cooldown is allowed; on success
                      the breaker closes; on failure it re-opens.
    """
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
                # half-open — let one call through
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
    """Tiny async-safe TTL cache keyed by (session_id, op_name, args_hash)."""

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
        """Drop all entries whose key starts with ``prefix`` — used on writes."""
        async with self._lock:
            keys = [k for k in self._data if k[:len(prefix)] == prefix]
            for k in keys:
                self._data.pop(k, None)


# ── Client ─────────────────────────────────────────────────────────────

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


class LMSClient:
    """Singleton facade for the upstream Leave Management System.

    Read methods are cached per chat-session. Write methods invalidate the
    relevant cache slice and bypass the cache.
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
        self._leave_snapshot_url = (os.getenv("LMS_LEAVE_SNAPSHOT_URL") or "").rstrip("/")
        self._api_key = os.getenv("LMS_API_KEY") or ""
        self._timeout_ms = int(os.getenv("LMS_TIMEOUT_MS", "8000"))
        self._cache_ttl = float(os.getenv("LMS_CACHE_TTL_SECONDS", "60"))
        self._cache = _TTLCache()
        self._breaker = _CircuitBreaker(
            fail_threshold=int(os.getenv("LMS_CIRCUIT_FAILS", "5")),
            cooldown_sec=float(os.getenv("LMS_CIRCUIT_COOLDOWN_SEC", "30")),
        )
        self._stub_mode = not self._base_url and not self._leave_snapshot_url
        if self._stub_mode:
            logger.info(
                "LMSClient: LMS_BASE_URL and LMS_LEAVE_SNAPSHOT_URL are empty — "
                "running in stub mode (returns deterministic sample data). "
                "Set LMS_LEAVE_SNAPSHOT_URL to wire the real LeaveSnapshot API.",
            )
        self._initialised = True

    # ── Public API ─────────────────────────────────────────────────────

    async def get_leave_balance(
        self,
        *,
        session_id: str,
        employee_id: str,
        leave_type: str | None = None,
    ) -> list[LeaveBalance]:
        cache_key = (session_id, "balance", employee_id, leave_type or "")
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        # ── LeaveSnapshot API (preferred when configured) ──
        if self._leave_snapshot_url:
            items = await self._call_leave_snapshot(employee_id)
            result = [self._parse_snapshot_balance(item) for item in items]
            if leave_type:
                lt = leave_type.lower()
                result = [b for b in result if lt in b.leave_type.lower()]
            await self._cache.set(cache_key, result, ttl=self._cache_ttl)
            return result

        # ── Fallback: generic LMS endpoint or stub ──
        body = await self._call(
            "GET",
            f"/employees/{employee_id}/leave-balances",
            params={"type": leave_type} if leave_type else None,
            stub=self._stub_balance,
        )
        result = [self._parse_balance(item) for item in body.get("balances", [])]
        await self._cache.set(cache_key, result, ttl=self._cache_ttl)
        return result

    async def get_pending_leaves(
        self,
        *,
        session_id: str,
        employee_id: str,
    ) -> list[LeaveRequest]:
        cache_key = (session_id, "pending", employee_id)
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached
        body = await self._call(
            "GET",
            f"/employees/{employee_id}/leave-requests",
            params={"status": "pending"},
            stub=self._stub_pending,
        )
        result = [self._parse_request(item) for item in body.get("requests", [])]
        await self._cache.set(cache_key, result, ttl=self._cache_ttl)
        return result

    async def get_holiday_calendar(
        self,
        *,
        session_id: str,
        location: str,
        year: int,
        month: int | None = None,
    ) -> list[Holiday]:
        cache_key = (session_id, "holidays", location.lower(), year, month or 0)
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached
        params = {"location": location, "year": year}
        if month:
            params["month"] = month
        body = await self._call(
            "GET",
            "/holidays",
            params=params,
            stub=self._stub_holidays,
        )
        result = [self._parse_holiday(item) for item in body.get("holidays", [])]
        await self._cache.set(cache_key, result, ttl=self._cache_ttl * 4)
        return result

    async def apply_leave(
        self,
        *,
        session_id: str,
        employee_id: str,
        start_date: date,
        end_date: date,
        leave_type: str,
        reason: str | None = None,
        idempotency_key: str | None = None,
    ) -> LeaveRequest:
        if end_date < start_date:
            raise LMSValidationError("end_date must be on or after start_date.")
        # Idempotency: include session_id so retries within a chat don't duplicate.
        idem = idempotency_key or f"{session_id}:{employee_id}:{start_date}:{end_date}:{leave_type}"
        body = await self._call(
            "POST",
            f"/employees/{employee_id}/leave-requests",
            json_body={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "leave_type": leave_type,
                "reason": reason,
            },
            headers={"Idempotency-Key": idem},
            stub=self._stub_apply,
        )
        await self._cache.invalidate((session_id, "balance"))
        await self._cache.invalidate((session_id, "pending"))
        return self._parse_request(body.get("request", body))

    async def cancel_leave(
        self,
        *,
        session_id: str,
        employee_id: str,
        request_id: str,
    ) -> bool:
        await self._call(
            "DELETE",
            f"/employees/{employee_id}/leave-requests/{request_id}",
            stub=self._stub_cancel,
        )
        await self._cache.invalidate((session_id, "balance"))
        await self._cache.invalidate((session_id, "pending"))
        return True

    # ── LeaveSnapshot API call ──────────────────────────────────────────

    async def _call_leave_snapshot(self, employee_email: str) -> list[dict]:
        """Call the 3rd-party LeaveSnapshot API and return the raw list.

        Endpoint: GET /api/LeaveSnapshot?email={employee_email}
        Returns a JSON array of leave-type objects directly (not wrapped).
        """
        if not self._leave_snapshot_url:
            return self._stub_balance().get("balances", [])

        await self._breaker.before_call()

        try:
            import httpx
        except ImportError as exc:
            raise LMSError(
                "httpx is required to call the LeaveSnapshot API. "
                "Install it with `pip install httpx`.",
            ) from exc

        url = f"{self._leave_snapshot_url}/api/LeaveSnapshot"
        timeout = httpx.Timeout(self._timeout_ms / 1000.0)

        last_exc: Exception | None = None
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    # employee_email_Test
                    resp = await client.get(url, params={"email": "testNazih.Borghol@lb.ey.com"})
                if resp.status_code == 401 or resp.status_code == 403:
                    raise LMSAuthError(
                        f"Auth failed ({resp.status_code}) for LeaveSnapshot."
                    )
                if 400 <= resp.status_code < 500:
                    raise LMSValidationError(
                        f"LeaveSnapshot rejected request: {resp.status_code} "
                        f"{resp.text[:300]}"
                    )
                if resp.status_code >= 500:
                    raise LMSUpstreamError(
                        f"LeaveSnapshot {resp.status_code}: {resp.text[:300]}"
                    )
                try:
                    body = resp.json()
                except json.JSONDecodeError as exc:
                    raise LMSUpstreamError(
                        f"Non-JSON response from LeaveSnapshot"
                    ) from exc
                await self._breaker.on_success()
                return body if isinstance(body, list) else []
            except (LMSValidationError, LMSAuthError):
                raise
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "LeaveSnapshot call failed (attempt %d/%d): %s",
                    attempt + 1, max_retries + 1, exc,
                )
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue

        await self._breaker.on_failure()
        raise LMSUpstreamError(
            f"LeaveSnapshot call failed after {max_retries + 1} attempts: "
            f"{last_exc}",
        )

    # ── Stubs (used when LMS_BASE_URL is unset — early rollout) ─────────

    @staticmethod
    def _stub_balance(*_args, **_kwargs) -> dict:
        return {
            "balances": [
                {"leave_type": "Annual",  "available": 18.0, "accrued": 25.0, "used": 7.0, "pending": 0.0},
                {"leave_type": "Sick",    "available": 10.0, "accrued": 10.0, "used": 0.0, "pending": 0.0},
                {"leave_type": "Casual",  "available": 5.0,  "accrued": 5.0,  "used": 0.0, "pending": 0.0},
            ],
        }

    @staticmethod
    def _stub_pending(*_args, **_kwargs) -> dict:
        return {"requests": []}

    @staticmethod
    def _stub_holidays(*_args, **_kwargs) -> dict:
        # Generic placeholder — real HR system returns location-specific dates.
        return {
            "holidays": [
                {"name": "New Year's Day", "date": "2026-01-01", "location": "ALL", "optional": False},
                {"name": "National Day",   "date": "2026-12-02", "location": "AE", "optional": False},
            ],
        }

    @staticmethod
    def _stub_apply(method: str, path: str, json_body: dict | None, **_) -> dict:
        body = json_body or {}
        return {
            "request": {
                "id": f"stub-{int(time.time())}",
                "employee_id": path.split("/")[2] if "employees" in path else "unknown",
                "leave_type": body.get("leave_type", "Annual"),
                "start_date": body.get("start_date"),
                "end_date": body.get("end_date"),
                "days": 1.0,
                "status": "pending",
                "reason": body.get("reason"),
                "submitted_at": datetime.utcnow().isoformat(),
            },
        }

    @staticmethod
    def _stub_cancel(*_args, **_kwargs) -> dict:
        return {"status": "cancelled"}

    # ── Parsers ────────────────────────────────────────────────────────

    @staticmethod
    def _parse_snapshot_balance(item: dict) -> LeaveBalance:
        """Map a LeaveSnapshot API item to the internal LeaveBalance model.

        API fields: leaveType, balanceCount, leaveAsonDate, leavesTaken,
                    balanceHours, leaveEntitlement, etc.
        """
        return LeaveBalance(
            leave_type=str(item.get("leaveType") or "Unknown"),
            available_days=float(item.get("balanceCount") or 0),
            accrued_days=float(item.get("leaveAsonDate") or 0),
            used_days=float(item.get("leavesTaken") or 0),
            pending_days=0.0,
        )

    @staticmethod
    def _parse_balance(item: dict) -> LeaveBalance:
        return LeaveBalance(
            leave_type=str(item.get("leave_type", "Annual")),
            available_days=float(item.get("available", 0) or 0),
            accrued_days=float(item.get("accrued", 0) or 0),
            used_days=float(item.get("used", 0) or 0),
            pending_days=float(item.get("pending", 0) or 0),
        )

    @staticmethod
    def _parse_request(item: dict) -> LeaveRequest:
        def _d(v: Any) -> date:
            if isinstance(v, date):
                return v
            return datetime.fromisoformat(str(v)).date()
        submitted = item.get("submitted_at")
        return LeaveRequest(
            request_id=str(item.get("id") or item.get("request_id") or ""),
            employee_id=str(item.get("employee_id") or ""),
            leave_type=str(item.get("leave_type") or "Annual"),
            start_date=_d(item.get("start_date")),
            end_date=_d(item.get("end_date")),
            days=float(item.get("days") or 0),
            status=str(item.get("status") or "pending"),
            reason=item.get("reason"),
            submitted_at=datetime.fromisoformat(submitted) if submitted else None,
        )

    @staticmethod
    def _parse_holiday(item: dict) -> Holiday:
        d = item.get("date")
        if isinstance(d, str):
            d = datetime.fromisoformat(d).date()
        return Holiday(
            name=str(item.get("name") or "Holiday"),
            holiday_date=d if isinstance(d, date) else date.today(),
            location=str(item.get("location") or "ALL"),
            is_optional=bool(item.get("optional", False)),
        )

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
            return stub(method=method, path=path, json_body=json_body)

        await self._breaker.before_call()

        try:
            import httpx  # local import — keeps the dep optional during installs
        except ImportError as exc:
            raise LMSError(
                "httpx is required to call the upstream LMS. "
                "Install it with `pip install httpx`.",
            ) from exc

        request_headers = {"Content-Type": "application/json"}
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
                if resp.status_code == 401 or resp.status_code == 403:
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
                # 4xx — don't retry, don't trip the breaker
                raise
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "LMS call failed (attempt %d/%d) %s %s: %s",
                    attempt + 1, max_retries + 1, method, path, exc,
                )
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (2 ** attempt))  # 0.5, 1.0
                    continue

        await self._breaker.on_failure()
        raise LMSUpstreamError(
            f"Upstream call failed after {max_retries + 1} attempts: {last_exc}",
        )


def get_lms_client() -> LMSClient:
    """Convenience accessor — agents and tools should call this, not LMSClient()."""
    return LMSClient()
