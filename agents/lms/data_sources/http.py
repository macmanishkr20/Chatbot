"""
HTTP LMS data source — calls the production LMS REST API.

Skeleton implementation. The shape is final; only the URLs / auth scheme /
JSON-to-dict mapping need to be filled in once the LMS API contract is
confirmed by the LMS team.

When endpoints are known, replace the NotImplementedError stubs with httpx
calls; do not change the method signatures. The agent code does not care
which backend it is talking to.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp

from agents.lms.data_source import (
    LMSDataSource,
    LMSDataSourceError,
    make_source_block,
)
from core.config import LMS_HTTP_BASE_URL, LMS_HTTP_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class HTTPLMSDataSource(LMSDataSource):
    """HTTP REST client for the LMS API.

    Configured via ``LMS_HTTP_BASE_URL`` and ``LMS_HTTP_TIMEOUT_SECONDS``.
    Auth headers and retry strategy will be added when the contract is
    finalised. Keep the public methods aligned with the Protocol.
    """

    backend_name: str = "http"

    def __init__(self) -> None:
        if not LMS_HTTP_BASE_URL:
            logger.warning(
                "HTTPLMSDataSource constructed without LMS_HTTP_BASE_URL — "
                "calls will fail until the env var is set."
            )
        self._base_url = LMS_HTTP_BASE_URL
        self._timeout = LMS_HTTP_TIMEOUT_SECONDS

    async def get_leave_balance(
        self,
        employee_id: str,
        leave_type: str | None = None,
    ) -> dict:
        """Fetch the leave snapshot for the given user.

        The LMS API expects an *email* as the lookup key. We pass
        ``employee_id`` through directly — upstream code uses the user's
        email as their employee identifier.

        Endpoint:
            GET {base}/api/LeaveSnapshot?email=<employee_id>
        """
        if not self._base_url:
            raise LMSDataSourceError(
                code="CONFIG_MISSING",
                detail="LMS_HTTP_BASE_URL is not configured.",
                retriable=False,
            )
        if not employee_id:
            raise LMSDataSourceError(
                code="BAD_INPUT",
                detail="employee_id (email) is required for LeaveSnapshot.",
                retriable=False,
            )

        endpoint = "/api/LeaveSnapshot"
        url = f"{self._base_url.rstrip('/')}{endpoint}"
        params = {"email": employee_id}

        raw = await self._get_json(url, params=params, endpoint=endpoint)
        balances = _normalize_balances(raw)

        if leave_type:
            wanted = leave_type.strip().lower()
            balances = [b for b in balances if b.get("leave_type", "").lower() == wanted]

        payload: dict = {
            "employee_id": employee_id,
            "as_of_year": datetime.now(timezone.utc).year,
            "balances": balances,
        }
        return self._attach_source(payload, endpoint=endpoint)

    async def get_leave_applications(
        self,
        employee_id: str,
        status: str | None = None,
        limit: int = 10,
    ) -> dict:
        # TODO(LMS-INTEGRATION):
        #   GET {base}/employees/{employee_id}/leave-applications?status=...&limit=N
        raise LMSDataSourceError(
            code="NOT_IMPLEMENTED",
            detail="HTTP LMS backend wiring pending; set LMS_DATA_SOURCE_KIND=stub.",
            retriable=False,
        )

    async def get_pending_approvals(self, manager_id: str) -> dict:
        # TODO(LMS-INTEGRATION):
        #   GET {base}/managers/{manager_id}/pending-approvals
        raise LMSDataSourceError(
            code="NOT_IMPLEMENTED",
            detail="HTTP LMS backend wiring pending; set LMS_DATA_SOURCE_KIND=stub.",
            retriable=False,
        )

    # Helper to keep future implementations consistent.
    def _attach_source(self, payload: dict, *, endpoint: str) -> dict:
        payload["source"] = make_source_block(
            self.backend_name,
            base_url=self._base_url or None,
            endpoint=endpoint,
        )
        return payload

    async def _get_json(
        self,
        url: str,
        *,
        params: dict | None = None,
        endpoint: str,
    ) -> Any:
        """Issue a GET and decode JSON, mapping transport errors to LMSDataSourceError."""
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status >= 500:
                        body = (await resp.text())[:500]
                        raise LMSDataSourceError(
                            code=f"HTTP_{resp.status}",
                            detail=f"{endpoint} upstream error: {body}",
                            retriable=True,
                        )
                    if resp.status == 404:
                        raise LMSDataSourceError(
                            code="HTTP_404",
                            detail=f"{endpoint} not found.",
                            retriable=False,
                        )
                    if resp.status >= 400:
                        body = (await resp.text())[:500]
                        raise LMSDataSourceError(
                            code=f"HTTP_{resp.status}",
                            detail=f"{endpoint} client error: {body}",
                            retriable=False,
                        )
                    try:
                        return await resp.json(content_type=None)
                    except (aiohttp.ContentTypeError, ValueError) as e:
                        raise LMSDataSourceError(
                            code="BAD_JSON",
                            detail=f"{endpoint} returned non-JSON body: {e}",
                            retriable=False,
                        ) from e
        except LMSDataSourceError:
            raise
        except aiohttp.ClientConnectorError as e:
            raise LMSDataSourceError(
                code="CONNECT_FAILED",
                detail=f"Cannot reach LMS at {url}: {e}",
                retriable=True,
            ) from e
        except (aiohttp.ServerTimeoutError, TimeoutError) as e:
            raise LMSDataSourceError(
                code="TIMEOUT",
                detail=f"{endpoint} timed out after {self._timeout}s",
                retriable=True,
            ) from e
        except aiohttp.ClientError as e:
            raise LMSDataSourceError(
                code="HTTP_CLIENT_ERROR",
                detail=f"{endpoint} transport error: {e}",
                retriable=True,
            ) from e


def _coerce_float(value: Any) -> float:
    """Best-effort numeric coercion. Returns 0.0 on failure."""
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_balances(raw: Any) -> list[dict]:
    """Map an LMS LeaveSnapshot payload into the contract's ``balances`` shape.

    The upstream LMS may return either a list of entries or an object that
    wraps a list under common keys (``balances``, ``data``, ``snapshot``).
    Each entry is normalised to::

        {leave_type, entitled, used, remaining, unit}

    Unknown fields are preserved verbatim under ``extra`` so callers can
    surface them if needed without losing information.
    """
    if isinstance(raw, dict):
        items = (
            raw.get("balances")
            or raw.get("data")
            or raw.get("snapshot")
            or raw.get("LeaveSnapshot")
            or raw.get("result")
        )
        if items is None:
            # Single-record shape — wrap so the loop below handles it.
            items = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        return []

    if not isinstance(items, list):
        return []

    normalised: list[dict] = []
    field_map = {
        "leave_type": ("leave_type", "leaveType", "LeaveType", "type", "Type", "name", "Name"),
        "entitled":   ("entitled",  "Entitled",  "entitlement", "Entitlement", "allocated", "Allocated", "total", "Total"),
        "used":       ("used",      "Used",      "consumed",    "Consumed",    "taken",     "Taken"),
        "remaining":  ("remaining", "Remaining", "balance",     "Balance",     "available", "Available"),
        "unit":       ("unit",      "Unit",      "uom",         "UOM"),
    }

    for entry in items:
        if not isinstance(entry, dict):
            continue
        record: dict[str, Any] = {}
        consumed_keys: set[str] = set()
        for target, candidates in field_map.items():
            for key in candidates:
                if key in entry and entry[key] is not None:
                    record[target] = entry[key]
                    consumed_keys.add(key)
                    break

        leave_type = str(record.get("leave_type") or "").strip()
        if not leave_type:
            continue

        entitled = _coerce_float(record.get("entitled"))
        used = _coerce_float(record.get("used"))
        remaining_raw = record.get("remaining")
        remaining = _coerce_float(remaining_raw) if remaining_raw is not None else max(entitled - used, 0.0)
        unit = str(record.get("unit") or "days")

        extra = {k: v for k, v in entry.items() if k not in consumed_keys}
        balance: dict[str, Any] = {
            "leave_type": leave_type,
            "entitled": entitled,
            "used": used,
            "remaining": remaining,
            "unit": unit,
        }
        if extra:
            balance["extra"] = extra
        normalised.append(balance)

    return normalised
