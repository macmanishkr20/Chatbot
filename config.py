"""
Unified configuration for MenaBot.
All environment variables consolidated in one place.
"""
import os
import json
from dotenv import load_dotenv

load_dotenv(override=True)

from helpers.keyvaultmanager import get_secret


ENVIRONMENT = os.getenv("ENVIRONMENT")
print(f"[LOG]----{ENVIRONMENT}---ENVIRONMENT in config.py")


# MSSQL_CONNECTION_STRING = get_secret("MSSQL-CONNECTION-STRING")
ENVIRONMENT_FOR_SQL = os.getenv("ENVIRONMENT_SET_FOR_SQL")
if ENVIRONMENT_FOR_SQL == "LOCAL":
    MSSQL_CONNECTION_STRING = os.getenv("MSSQL_CONNECTION_STRING")
else:
    MSSQL_CONNECTION_STRING = get_secret("MSSQL-CONNECTION-STRING")
AZURE_SQL_CHECKPOINT_TABLE = os.getenv("AZURE_SQL_CHECKPOINT_TABLE", "langgraph_checkpoints")
AZURE_SQL_USE_MANAGED_IDENTITY = os.getenv("AZURE_SQL_USE_MANAGED_IDENTITY", "false").lower() == "true"
AZURE_SQL_SERVER = get_secret("AZURE-SQL-SERVER")
AZURE_SQL_DATABASE = get_secret("AZURE-SQL-DATABASE")
# AZURE_SQL_DATABASE = os.getenv("AZURE_SQL_DATABASE")
AZURE_SQL_DRIVER = os.getenv("AZURE_SQL_DRIVER", "ODBC Driver 18 for SQL Server")
AZURE_SQL_MANAGED_IDENTITY_CLIENT_ID = get_secret("AZURE-SQL-MANAGED-IDENTITY-CLIENT-ID")

# ---------------------------- Azure Search ---------------------------

AZURE_SEARCH_SERVICE = get_secret("AZURE-SEARCH-SERVICE")
AZURE_SEARCH_INDEX = get_secret("AZURE-SEARCH-INDEX")
AZURE_SEARCH_KEY = get_secret("AZURE-SEARCH-KEY")
AZURE_SEARCH_ENDPOINT = get_secret("AZURE-SEARCH-ENDPOINT")
AZURE_SEARCH_API_KEY = get_secret("AZURE-SEARCH-API-KEY")
AZURE_SEARCH_INDEX_NAME = get_secret("AZURE-SEARCH-INDEX-NAME")
AZURE_SEARCH_VECTOR_FIELD = os.getenv("AZURE_SEARCH_VECTOR_FIELD", "content_vector")
AZURE_SEARCH_TOP_K = int(os.getenv("AZURE_SEARCH_TOP_K", "3"))
AZURE_SEARCH_VECTOR_COLUMNS = os.getenv("AZURE_SEARCH_VECTOR_COLUMNS", "content_vector")
AZURE_SEARCH_CONTENT_COLUMNS = os.getenv("AZURE_SEARCH_CONTENT_COLUMNS", "content")
AZURE_SEARCH_SCORE_THRESHOLD = float(os.getenv("AZURE_SEARCH_SCORE_THRESHOLD", "0.5"))
AZURE_SEARCH_API_VERSION = get_secret("AZURE-SEARCH-API-VERSION", "2023-11-01")

SELECT_FIELDS = get_secret(
    "AZURE-SEARCH-SELECT-FIELDS",
    "file_name,page_number,content,source_url",
)
TOP_K = int(get_secret("AZURE-SEARCH-TOP-K", "3"))

# ──────────────────────────── Azure OpenAI ───────────────────────────

AZURE_OPENAI_ENDPOINT = get_secret("AZURE-OPENAI-ENDPOINT")
AZURE_OPENAI_KEY = get_secret("AZURE-OPENAI-KEY")
AZURE_OPENAI_CHAT_DEPLOYMENT = get_secret("AZURE-OPENAI-CHAT-DEPLOYMENT")
AZURE_OPENAI_CHAT_API_VERSION = get_secret("AZURE-OPENAI-CHAT-API-VERSION", "2024-10-21")

AZURE_OPENAI_EMBED_ENDPOINT = get_secret("AZURE-OPENAI-EMBED-ENDPOINT") or AZURE_OPENAI_ENDPOINT
AZURE_OPENAI_EMBED_API_KEY = get_secret("AZURE-OPENAI-EMBED-API-KEY") or AZURE_OPENAI_KEY
AZURE_OPENAI_API_VERSION = get_secret("AZURE-OPENAI-EMBED-API-VERSION", "2024-02-01")
AZURE_OPENAI_EMBEDDING_DEPLOYMENT = get_secret("AZURE-OPENAI-EMBEDDING-DEPLOYMENT")
AZURE_OPENAI_EMBEDDING_DIMENSIONS = int(get_secret("AZURE-OPENAI-EMBEDDING-DIMENSIONS", "3072"))

AZURE_OPENAI_MODEL = get_secret("AZURE-OPENAI-MODEL", "")

AZURE_OPENAI_MAX_TOKENS = int(get_secret("AZURE-OPENAI-MAX-TOKENS", "600"))
AZURE_OPENAI_TEMPERATURE = float(get_secret("AZURE-OPENAI-TEMPERATURE", "0.7"))
AZURE_OPENAI_TOP_P = float(get_secret("AZURE-OPENAI-TOP-P", "0.95"))
AZURE_OPENAI_STOP_SEQUENCE = os.getenv("AZURE-OPENAI-STOP-SEQUENCE", "")
AZURE_OPENAI_SYSTEM_MESSAGE = os.getenv(
    "AZURE-OPENAI-SYSTEM-MESSAGE",
    "You are a helpful assistant.",
)
SHOULD_STREAM = os.getenv("SHOULD-STREAM", "true").lower() == "true"

_models_raw = get_secret("AZURE-OPENAI-MODELS", "{}")
AZURE_OPENAI_MODELS: dict = json.loads(_models_raw) if _models_raw else {}

_prioritized_raw = get_secret("AZURE-OPENAI-MODELS-PRIORITIZED", "[]")
AZURE_OPENAI_MODELS_PRIORITIZED: list = json.loads(_prioritized_raw) if _prioritized_raw else []

_embed_prioritized_raw = get_secret("AZURE-OPENAI-EMBEDDING-MODELS-PRIORITIZED", "[]")
AZURE_OPENAI_EMBEDDING_MODELS_PRIORITIZED: list = (
    json.loads(_embed_prioritized_raw) if _embed_prioritized_raw else []
)

_token_limits_raw = get_secret("AZURE-OPENAI-TOKEN-LIMITS", "{}")
AZURE_OPENAI_TOKEN_LIMITS: dict = json.loads(_token_limits_raw) if _token_limits_raw else {}

# ──────────────────────────── Application ────────────────────────────

USER_AGENT = os.getenv("USER-AGENT", "menabot/1.0")

_biz_exc_raw = os.getenv(
    "BUSINESS-EXCEPTION-DETAILS",
    '{"empty_events": {"error_code": "NO_EVENTS", "text": "No relevant events found for your query."}}',
)
BUSINESS_EXCEPTION_DETAILS: dict = json.loads(_biz_exc_raw) if _biz_exc_raw else {}

MAX_TOKENS = int(os.getenv("MAX-TOKENS", "600"))
SNIPPET_CHARS = int(os.getenv("SNIPPET-CHARS", "800"))


AZURE_OPENAI_CHAT_API_VERSION = os.getenv("AZURE_OPENAI_CHAT_API_VERSION", "2024-10-21")
AMBIGUITY_SCORE_RATIO = float(os.getenv("AMBIGUITY_SCORE_RATIO", "0.6"))
AZURE_SEARCH_SEMANTIC_CONFIG = get_secret("AZURE-SEARCH-SEMANTIC-CONFIG", "")
DISCOVERY_TOP_K = int(os.getenv("DISCOVERY_TOP_K", "10"))

# InsightsConnectionString
APPLICATIONINSIGHTS_CONNECTION_STRING = get_secret("APPLICATIONINSIGHTS-CONNECTION-STRING")

# ── Context window management ──
# Max recent messages to keep in full before summarising older ones.
# Older messages are condensed into a summary to stay within token limits.
MAX_RECENT_MESSAGES = int(os.getenv("MAX_RECENT_MESSAGES", "6"))
# Max tokens to allocate for conversation history in the supervisor prompt.
SUPERVISOR_HISTORY_TOKEN_BUDGET = int(os.getenv("SUPERVISOR_HISTORY_TOKEN_BUDGET", "3000"))

# ── Rate limiting ──
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))

# ── Title generation ──
TITLE_MAX_LENGTH = int(os.getenv("TITLE_MAX_LENGTH", "60"))

# ── Input validation ──
MAX_INPUT_LENGTH = int(os.getenv("MAX_INPUT_LENGTH", "10000"))

# ── Retrieval grading (CRAG — Corrective RAG) ──
GRADER_RELEVANCE_THRESHOLD = float(os.getenv("GRADER_RELEVANCE_THRESHOLD", "0.5"))
GRADER_MAX_RETRIES = int(os.getenv("GRADER_MAX_RETRIES", "1"))
GRADER_MAX_TOKENS = int(os.getenv("GRADER_MAX_TOKENS", "150"))
GRADER_TEMPERATURE = float(os.getenv("GRADER_TEMPERATURE", "0.0"))

# ── Parallel search / Planner (Phase 2) ──
PARALLEL_SEARCH_TIMEOUT = int(os.getenv("PARALLEL_SEARCH_TIMEOUT", "10000"))  # ms per function
PLANNER_MAX_TOKENS = int(os.getenv("PLANNER_MAX_TOKENS", "200"))
PLANNER_TEMPERATURE = float(os.getenv("PLANNER_TEMPERATURE", "0.0"))