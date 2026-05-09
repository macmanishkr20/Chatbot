"""HTTP / runtime concerns: rate limit, cancel signal, input validation, business exceptions."""
import json
import os

USER_AGENT = os.getenv("USER-AGENT", "menabot/1.0")

_biz_exc_raw = os.getenv(
    "BUSINESS-EXCEPTION-DETAILS",
    '{"empty_events": {"error_code": "NO_EVENTS", "text": "No relevant events found for your query."}}',
)
BUSINESS_EXCEPTION_DETAILS: dict = json.loads(_biz_exc_raw) if _biz_exc_raw else {}

# ── Rate limiting (slowapi) ──
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))

# ── Input validation ──
MAX_INPUT_LENGTH = int(os.getenv("MAX_INPUT_LENGTH", "10000"))

# ── Cancel-signal backend (multi-worker safe) ──
# "memory" (default, single-process) | "redis" (multi-worker / multi-replica)
CANCEL_SIGNAL_BACKEND = os.getenv("CANCEL_SIGNAL_BACKEND", "memory").lower()
CANCEL_SIGNAL_REDIS_URL = os.getenv("CANCEL_SIGNAL_REDIS_URL", "")
CANCEL_SIGNAL_TTL_SECONDS = int(os.getenv("CANCEL_SIGNAL_TTL_SECONDS", "300"))
