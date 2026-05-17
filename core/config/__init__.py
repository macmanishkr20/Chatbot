"""
Configuration package — split into domain modules for maintainability.

Backward-compatible: every symbol previously exposed by ``core.config``
remains importable from ``core.config`` via re-export from this package.

Sub-modules:
    azure   — Azure SQL / Search / OpenAI / App Insights connection details
    llm     — model behavior (deployments, temps, max_tokens, model maps)
    search  — retrieval thresholds, top-k, dual mode, planner/parallel-search
    memory  — conversation context (summarize, keep-recent, checkpoint cap)
    runtime — HTTP / runtime concerns (rate limit, cancel, input length)

Loading order matters: `_bootstrap` runs `load_dotenv` before any sub-module
imports `get_secret` so KV-fallback to env vars works correctly.
"""
from . import _bootstrap  # noqa: F401  (must run first)
from ._bootstrap import ENVIRONMENT  # noqa: F401  (preserve top-level symbol)

from .azure import *  # noqa: F401, F403
from .llm import *  # noqa: F401, F403
from .search import *  # noqa: F401, F403
from .memory import *  # noqa: F401, F403
from .runtime import *  # noqa: F401, F403
