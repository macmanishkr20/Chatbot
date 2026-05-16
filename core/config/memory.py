"""Conversation context: summarize / keep-recent / checkpoint cap / title length."""
import os

# Max recent messages to keep in full before summarising older ones.
MAX_RECENT_MESSAGES = int(os.getenv("MAX_RECENT_MESSAGES", "6"))

# Hard cap on messages retained in checkpoint state (prevents unbounded growth).
MAX_CHECKPOINT_MESSAGES = int(os.getenv("MAX_CHECKPOINT_MESSAGES", "20"))

# Max tokens to allocate for conversation history in the supervisor prompt.
SUPERVISOR_HISTORY_TOKEN_BUDGET = int(os.getenv("SUPERVISOR_HISTORY_TOKEN_BUDGET", "3000"))

# ── summarize_node ──
# After this many messages in state, trigger summarization.
SUMMARIZE_THRESHOLD = int(os.getenv("SUMMARIZE_THRESHOLD", "20"))
# Keep the last N messages verbatim; summarise everything before them.
SUMMARIZE_KEEP_RECENT = int(os.getenv("SUMMARIZE_KEEP_RECENT", "6"))

# ── Title generation ──
TITLE_MAX_LENGTH = int(os.getenv("TITLE_MAX_LENGTH", "60"))
