"""Retrieval / search configuration."""
import os

from infrastructure.azure.keyvault import get_secret

# ── Azure Search behavior ──
AZURE_SEARCH_TOP_K = int(os.getenv("AZURE_SEARCH_TOP_K", "3"))
AZURE_SEARCH_SCORE_THRESHOLD = float(os.getenv("AZURE_SEARCH_SCORE_THRESHOLD", "1.5"))
SELECT_FIELDS = get_secret(
    "AZURE-SEARCH-SELECT-FIELDS",
    "file_name,page_number,content,source_url",
)
TOP_K = int(get_secret("AZURE-SEARCH-TOP-K", "5"))

# ── Discovery / ambiguity routing ──
AMBIGUITY_SCORE_RATIO = float(os.getenv("AMBIGUITY_SCORE_RATIO", "0.6"))
DISCOVERY_TOP_K = int(os.getenv("DISCOVERY_TOP_K", "10"))

# ── Dual content-type search ──
DUAL_CONTENT_SEARCH_ENABLED = os.getenv("DUAL_CONTENT_SEARCH_ENABLED", "true").lower() == "true"

# ── Azure Search retry (transient errors only) ──
AZURE_SEARCH_MAX_RETRIES = int(os.getenv("AZURE_SEARCH_MAX_RETRIES", "3"))

# ── Parallel search / planner (multi-function path) ──
PARALLEL_SEARCH_TIMEOUT = int(os.getenv("PARALLEL_SEARCH_TIMEOUT", "10000"))  # ms per function
MAX_PARALLEL_SEARCHES = int(os.getenv("MAX_PARALLEL_SEARCHES", "3"))  # max concurrent Azure Search calls
MAX_SUB_QUERIES = int(os.getenv("MAX_SUB_QUERIES", "5"))  # max sub-queries from planner
PLANNER_MAX_TOKENS = int(os.getenv("PLANNER_MAX_TOKENS", "200"))
PLANNER_TEMPERATURE = float(os.getenv("PLANNER_TEMPERATURE", "0.0"))
