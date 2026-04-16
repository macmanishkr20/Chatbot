"""
Unified configuration for MenaBot.
All environment variables consolidated in one place.
"""
import os
import json
from dotenv import load_dotenv

load_dotenv()


# ──────────────────────────── Environment ────────────────────────────

ENVIRONMENT = os.getenv("ENVIRONMENT", "LOCAL")

# ──────────────────────────── SQL Server ─────────────────────────────

MSSQL_CONNECTION_STRING = os.getenv("MSSQL_CONNECTION_STRING", "")
AZURE_SQL_CHECKPOINT_TABLE = os.getenv("AZURE_SQL_CHECKPOINT_TABLE", "langgraph_checkpoints")

# ──────────────────────────── Azure Search ───────────────────────────

AZURE_SEARCH_SERVICE = os.getenv("AZURE_SEARCH_SERVICE", "")
AZURE_SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX", "")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY", "")
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT", "")
AZURE_SEARCH_API_KEY = os.getenv("AZURE_SEARCH_API_KEY", "")
AZURE_SEARCH_INDEX_NAME = os.getenv("AZURE_SEARCH_INDEX_NAME", "")
AZURE_SEARCH_VECTOR_FIELD = os.getenv("AZURE_SEARCH_VECTOR_FIELD", "content_vector")
AZURE_SEARCH_TOP_K = int(os.getenv("AZURE_SEARCH_TOP_K", "3"))
AZURE_SEARCH_VECTOR_COLUMNS = os.getenv("AZURE_SEARCH_VECTOR_COLUMNS", "content_vector")
AZURE_SEARCH_CONTENT_COLUMNS = os.getenv("AZURE_SEARCH_CONTENT_COLUMNS", "content")
# Score threshold for search results.
# When semantic reranker is enabled, scores are on a 0–4 scale; 1.5 is a
# reasonable floor for "clearly relevant" results.
# When semantic reranker is disabled, scores are cosine/BM25 (0–1); 0.5 works.
AZURE_SEARCH_SCORE_THRESHOLD = float(os.getenv("AZURE_SEARCH_SCORE_THRESHOLD", "1.5"))
AZURE_SEARCH_API_VERSION = os.getenv("AZURE_SEARCH_API_VERSION", "2023-11-01")

SELECT_FIELDS = os.getenv(
    "AZURE_SEARCH_SELECT_FIELDS",
    "file_name,page_number,content,source_url",
)
TOP_K = int(os.getenv("TOP_K", "3"))

# ──────────────────────────── Azure OpenAI ───────────────────────────

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", os.getenv("AZURE_OPENAI_API_KEY", ""))
AZURE_OPENAI_EMBED_ENDPOINT = os.getenv("AZURE_OPENAI_EMBED_ENDPOINT", AZURE_OPENAI_ENDPOINT)
AZURE_OPENAI_EMBED_API_KEY = os.getenv("AZURE_OPENAI_EMBED_API_KEY", AZURE_OPENAI_KEY)
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
AZURE_OPENAI_PREVIEW_API_VERSION = os.getenv(
    "AZURE_OPENAI_PREVIEW_API_VERSION",
    os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
)
MINIMUM_SUPPORTED_AZURE_OPENAI_PREVIEW_API_VERSION = os.getenv(
    "MINIMUM_SUPPORTED_AZURE_OPENAI_PREVIEW_API_VERSION", "2024-02-01"
)
AZURE_OPENAI_MODEL = os.getenv("AZURE_OPENAI_MODEL", "")
AZURE_OPENAI_CHAT_DEPLOYMENT = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "")
AZURE_OPENAI_EMBEDDING_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "")

# Secondary endpoint (e.g., GPT-4o specific)
AZURE_OPENAI_ENDPOINT_4o = os.getenv("AZURE_OPENAI_ENDPOINT_4o", AZURE_OPENAI_ENDPOINT)
AZURE_OPENAI_KEY_4o = os.getenv("AZURE_OPENAI_KEY_4o", AZURE_OPENAI_KEY)

# LLM Parameters
AZURE_OPENAI_MAX_TOKENS = int(os.getenv("AZURE_OPENAI_MAX_TOKENS", "600"))
AZURE_OPENAI_TEMPERATURE = float(os.getenv("AZURE_OPENAI_TEMPERATURE", "0.7"))
AZURE_OPENAI_TOP_P = float(os.getenv("AZURE_OPENAI_TOP_P", "0.95"))
AZURE_OPENAI_STOP_SEQUENCE = os.getenv("AZURE_OPENAI_STOP_SEQUENCE", "")
AZURE_OPENAI_SYSTEM_MESSAGE = os.getenv(
    "AZURE_OPENAI_SYSTEM_MESSAGE",
    "You are a helpful assistant.",
)
SHOULD_STREAM = os.getenv("SHOULD_STREAM", "true").lower() == "true"

# Model registry — JSON-encoded env vars
# Example: AZURE_OPENAI_MODELS='{"events":"gpt-4o","rewrite_query":"gpt-4o-mini","embedding":"text-embedding-3-large"}'
_models_raw = os.getenv("AZURE_OPENAI_MODELS", "{}")
AZURE_OPENAI_MODELS: dict = json.loads(_models_raw) if _models_raw else {}

_prioritized_raw = os.getenv("AZURE_OPENAI_MODELS_PRIORITIZED", "[]")
AZURE_OPENAI_MODELS_PRIORITIZED: list = json.loads(_prioritized_raw) if _prioritized_raw else []

_embed_prioritized_raw = os.getenv("AZURE_OPENAI_EMBEDDING_MODELS_PRIORITIZED", "[]")
AZURE_OPENAI_EMBEDDING_MODELS_PRIORITIZED: list = (
    json.loads(_embed_prioritized_raw) if _embed_prioritized_raw else []
)

_token_limits_raw = os.getenv("AZURE_OPENAI_TOKEN_LIMITS", "{}")
AZURE_OPENAI_TOKEN_LIMITS: dict = json.loads(_token_limits_raw) if _token_limits_raw else {}

# ──────────────────────────── Application ────────────────────────────

USER_AGENT = os.getenv("USER_AGENT", "menabot/1.0")

_biz_exc_raw = os.getenv(
    "BUSINESS_EXCEPTION_DETAILS",
    '{"empty_events": {"error_code": "NO_EVENTS", "text": "No relevant events found for your query."}}',
)
BUSINESS_EXCEPTION_DETAILS: dict = json.loads(_biz_exc_raw) if _biz_exc_raw else {}

MAX_TOKENS = int(os.getenv("MAX_TOKENS", "600"))
SNIPPET_CHARS = int(os.getenv("SNIPPET_CHARS", "800"))



AZURE_OPENAI_CHAT_API_VERSION = os.getenv("AZURE_OPENAI_CHAT_API_VERSION", "2024-10-21")
AMBIGUITY_SCORE_RATIO = float(os.getenv("AMBIGUITY_SCORE_RATIO", "0.6"))
AZURE_SEARCH_SEMANTIC_CONFIG = os.getenv("AZURE_SEARCH_SEMANTIC_CONFIG", "")
DISCOVERY_TOP_K = int(os.getenv("DISCOVERY_TOP_K", "10"))

# ── Context window management ──
# Max recent messages to keep in full before summarising older ones.
# Older messages are condensed into a summary to stay within token limits.
MAX_RECENT_MESSAGES = int(os.getenv("MAX_RECENT_MESSAGES", "6"))
# Max tokens to allocate for conversation history in the supervisor prompt.
SUPERVISOR_HISTORY_TOKEN_BUDGET = int(os.getenv("SUPERVISOR_HISTORY_TOKEN_BUDGET", "3000"))