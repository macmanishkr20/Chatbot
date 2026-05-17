"""
Module-level mutable runtime state for the API layer.

Holds the compiled LangGraph singleton (set once at app startup by the
lifespan handler) plus optional callback handlers and shared SSE constants.

Other API modules import THIS module (not its symbols) so they always read
the current ``graph`` reference rather than a stale snapshot from import time.
"""
import logging
import os

logger = logging.getLogger(__name__)

# ── Compiled graph singleton (set by app.py lifespan) ──
graph = None  # type: ignore[assignment]


# ── Optional Langfuse observability ──
try:
    from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler
    _langfuse_available = True
except ImportError:
    _langfuse_available = False
    LangfuseCallbackHandler = None  # type: ignore[misc, assignment]

callback_handler = (
    LangfuseCallbackHandler()
    if os.getenv("ENABLE_LANGFUSE") == "true" and _langfuse_available
    else None
)


# ── Streaming constants ──
# Nodes whose LLM token output is meaningful prose for the end user.
# Supervisor is intentionally excluded — its tokens are JSON fragments.
# lms_format streams the LMS agent's final answer to the user.
STREAMABLE_NODES: frozenset[str] = frozenset({
    "generate", "lms_format", "expense_format", "scorecard_format",
})

# Chain-of-thought step labels shown in the UI
NODE_THOUGHT: dict[str, dict[str, str]] = {
    "Supervisor": {
        "display": "Intent",
        "message": "Aligning intent…",
        "group": "preparation",
        "icon": "assistant",
    },
    "load_memory": {
        "display": "Recall",
        "message": "Reconnecting context…",
        "group": "preparation",
        "icon": "history",
    },
    "function_gate": {
        "display": "Routing",
        "message": "Confirming MENA function…",
        "group": "preparation",
        "icon": "route",
    },
    "rewrite": {
        "display": "Focus",
        "message": "Clarifying focus…",
        "group": "understanding",
        "icon": "edit_note",
    },
    "search": {
        "display": "Relevance",
        "message": "Finding relevance…",
        "group": "retrieval",
        "icon": "search",
    },
    "multi_function_search": {
        "display": "Deep Search",
        "message": "Searching across multiple functions…",
        "group": "retrieval",
        "icon": "manage_search",
    },
    "planner": {
        "display": "Planning",
        "message": "Analyzing query complexity…",
        "group": "retrieval",
        "icon": "account_tree",
    },
    "parallel_search": {
        "display": "Searching",
        "message": "Searching multiple functions in parallel…",
        "group": "retrieval",
        "icon": "manage_search",
    },
    "synthesize": {
        "display": "Combining",
        "message": "Merging results…",
        "group": "retrieval",
        "icon": "merge",
    },
    "generate": {
        "display": "Response",
        "message": "Forming response…",
        "group": "response",
        "icon": "auto_fix_high",
    },
    "persist": {
        "display": "Flow",
        "message": "Maintaining continuity…",
        "group": "response",
        "icon": "save",
    },
    "save_memory": {
        "display": "Memory",
        "message": "Storing insight…",
        "group": "response",
        "icon": "bookmark",
    },
    "summarize": {
        "display": "Context",
        "message": "Condensing conversation…",
        "group": "response",
        "icon": "compress",
    },
    # ── LMS agent ──
    "lms_classify": {
        "display": "Leave Intent",
        "message": "Identifying your leave request…",
        "group": "understanding",
        "icon": "route",
    },
    "lms_fetch": {
        "display": "HRIS Lookup",
        "message": "Fetching your leave data…",
        "group": "retrieval",
        "icon": "cloud_download",
    },
    "lms_format": {
        "display": "Response",
        "message": "Preparing your answer…",
        "group": "response",
        "icon": "auto_fix_high",
    },
    # ── Expense agent ──
    "expense_planner": {
        "display": "Expense Plan",
        "message": "Planning your expense query…",
        "group": "understanding",
        "icon": "edit_note",
    },
    "expense_executor": {
        "display": "Expense DB",
        "message": "Fetching expense data…",
        "group": "retrieval",
        "icon": "database",
    },
    "expense_format": {
        "display": "Response",
        "message": "Preparing your answer…",
        "group": "response",
        "icon": "auto_fix_high",
    },
    # ── Scorecard agent ──
    "scorecard_planner": {
        "display": "Scorecard Plan",
        "message": "Planning your scorecard query…",
        "group": "understanding",
        "icon": "edit_note",
    },
    "scorecard_executor": {
        "display": "Scorecard DB",
        "message": "Fetching scorecard KPIs…",
        "group": "retrieval",
        "icon": "database",
    },
    "scorecard_format": {
        "display": "Response",
        "message": "Preparing your answer…",
        "group": "response",
        "icon": "auto_fix_high",
    },
}
