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

# ── Per-agent data-source selection ─────────────────────────────────────────
# Each data agent (LMS, future Expense, Scorecard) talks to a downstream
# system through a pluggable DataSource. The same agent code works for any
# backend — choosing one is a config decision.
#
#   "stub" — canned in-memory responses (default; safe for dev / CI)
#   "http" — HTTP REST API client (production)
#   "sql"  — direct SQL queries (when downstream is a DB)
#
# Adding a new backend = adding one file under agents/<agent>/data_sources/.
LMS_DATA_SOURCE_KIND = os.getenv("LMS_DATA_SOURCE_KIND", "http").lower()
LMS_HTTP_BASE_URL = os.getenv("LMS_HTTP_BASE_URL", "http://10.151.110.162:8087")
LMS_HTTP_TIMEOUT_SECONDS = float(os.getenv("LMS_HTTP_TIMEOUT_SECONDS", "10"))
