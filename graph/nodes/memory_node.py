"""
Memory nodes — load and save long-term user memory via LangGraph Store.

These nodes bridge the graph with the **Store** (cross-thread memory).
The Store is injected automatically by LangGraph when the graph is
compiled with ``store=<BaseStore>``.

Namespace convention:
    ("user", user_id, "sessions")  — summarized past conversation records
    ("user", user_id, "profile")   — user preferences / profile facts

load_memory_node
    Runs early in the pipeline (after validate, before rewrite).
    Reads the user's past session summaries from the Store and places
    them in ``state["user_memories"]`` so downstream nodes (generate)
    can use them as additional context.

save_memory_node
    Runs late in the pipeline (after summarize, before END).
    Writes the current conversation's summary + metadata into the
    Store so it is available in future conversations.
"""
from datetime import datetime, timezone

from langgraph.store.base import BaseStore

from graph.state import RAGState

# Maximum number of past session summaries to load as context
_MAX_MEMORY_ITEMS = 5


async def load_memory_node(state: RAGState, *, store: BaseStore) -> dict:
    """Load the user's long-term memories from the LangGraph Store.

    Reads past conversation summaries scoped to this user and makes
    them available in state so the LLM has cross-session context.
    """
    user_id = state.get("user_id", "")
    if not user_id:
        return {}

    # Fetch the most recent session summaries for this user
    namespace = ("user", user_id, "sessions")
    memories = await store.asearch(namespace, limit=_MAX_MEMORY_ITEMS)

    # Also load user profile if it exists
    profile_namespace = ("user", user_id, "profile")
    profile_item = await store.aget(profile_namespace, "preferences")

    user_memories: list[str] = []

    if profile_item and profile_item.value:
        prefs = profile_item.value
        user_memories.append(f"User profile: {prefs}")

    for item in memories:
        summary_text = item.value.get("summary", "")
        ts = item.value.get("timestamp", "")
        if summary_text:
            user_memories.append(f"[{ts}] {summary_text}")

    return {"user_memories": user_memories}


async def save_memory_node(state: RAGState, *, store: BaseStore) -> dict:
    """Persist the current conversation summary to the LangGraph Store.

    Writes the conversation summary (produced by summarize_node) and
    the AI content into the user's long-term memory so that future
    sessions can recall it.

    Also tracks frequently asked topics in the user profile.
    """
    user_id = state.get("user_id", "")
    if not user_id:
        return {}

    chat_id = state.get("chat_id") or "unknown"
    summary = state.get("summary", "")
    ai_content = state.get("ai_content", "")
    user_input = state.get("user_input", "")

    # Only save if there's meaningful content
    if not summary and not ai_content:
        return {}

    now = datetime.now(timezone.utc)
    ts_str = now.isoformat()

    # ── Save session summary ──
    session_namespace = ("user", user_id, "sessions")
    session_key = f"session_{chat_id}_{now.strftime('%Y%m%d%H%M%S')}"

    memory_value = {
        "chat_id": chat_id,
        "summary": summary or ai_content[:500],
        "user_query": user_input,
        "timestamp": ts_str,
    }

    await store.aput(session_namespace, session_key, memory_value)

    # ── Update user profile with topic tracking ──
    profile_namespace = ("user", user_id, "profile")
    profile_item = await store.aget(profile_namespace, "preferences")
    profile = profile_item.value if profile_item else {}

    # Track recent topics (keep last 10)
    recent_topics: list[str] = profile.get("recent_topics", [])
    if user_input:
        recent_topics.insert(0, user_input[:200])
        recent_topics = recent_topics[:10]
    profile["recent_topics"] = recent_topics
    profile["last_active"] = ts_str
    profile["total_sessions"] = profile.get("total_sessions", 0) + 1

    await store.aput(profile_namespace, "preferences", profile)

    return {}
