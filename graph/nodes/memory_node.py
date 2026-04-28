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
import logging
from datetime import datetime, timezone

from langgraph.store.base import BaseStore

from graph.state import RAGState
from services.telemetry import get_tracer_span

logger = logging.getLogger(__name__)

# Maximum number of past session summaries to load as context
_MAX_MEMORY_ITEMS = 5


async def load_memory_node(state: RAGState, *, store: BaseStore) -> dict:
    """Load the user's long-term memories from the LangGraph Store.

    Reads past conversation summaries scoped to this user and makes
    them available in state so the LLM has cross-session context.
    """
    with get_tracer_span("load_memory_node"):
        user_id = state.get("user_id", "")
        if not user_id:
            return {}

        try:
            # Fetch the most recent session summaries for this user
            namespace = ("user", user_id, "sessions")
            memories = await store.asearch(namespace, limit=_MAX_MEMORY_ITEMS)

            # Also load user profile if it exists
            profile_namespace = ("user", user_id, "profile")
            profile_item = await store.aget(profile_namespace, "preferences")

            user_memories: list[str] = []

            if profile_item and profile_item.value:
                prefs = profile_item.value
                # Extract structured preferences for clear LLM injection
                pref_parts = []
                recent_topics = prefs.get("recent_topics", [])
                if recent_topics:
                    # Identify most frequent topic themes
                    pref_parts.append(
                        f"recently asked about: {', '.join(recent_topics[:3])}"
                    )
                total = prefs.get("total_sessions", 0)
                if total:
                    pref_parts.append(f"{total} total sessions")
                last_active = prefs.get("last_active", "")
                if last_active:
                    pref_parts.append(f"last active: {last_active[:10]}")

                if pref_parts:
                    user_memories.append(
                        f"User preferences: {'; '.join(pref_parts)}"
                    )

            for item in memories:
                val = item.value if item.value else {}
                summary_text = val.get("summary", "")
                ts = val.get("timestamp", "")
                if summary_text:
                    user_memories.append(f"[{ts}] {summary_text}")

            return {"user_memories": user_memories}
        except Exception as e:
            logger.error("load_memory_node failed: %s", e, exc_info=True)
            return {"user_memories": []}


async def save_memory_node(state: RAGState, *, store: BaseStore) -> dict:
    """Persist the current conversation summary to the LangGraph Store.

    Writes the conversation summary (produced by summarize_node) and
    the AI content into the user's long-term memory so that future
    sessions can recall it.

    Also tracks frequently asked topics in the user profile.
    """
    with get_tracer_span("save_memory_node"):
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

        try:
            now = datetime.now(timezone.utc)
            ts_str = now.isoformat()

            # ── Save session summary ──
            # Key uses chat_id (not timestamp) to prevent duplicate entries
            session_namespace = ("user", user_id, "sessions")
            session_key = f"session_{chat_id}"

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
            profile = (profile_item.value if profile_item and profile_item.value else {})

            # Track recent topics (keep last 10)
            recent_topics: list[str] = profile.get("recent_topics", [])
            if user_input:
                recent_topics.insert(0, user_input[:200])
                recent_topics = recent_topics[:10]
            profile["recent_topics"] = recent_topics
            profile["last_active"] = ts_str

            # Increment total_sessions only for NEW conversations (not every message)
            seen_sessions: list[str] = profile.get("seen_sessions", [])
            if str(chat_id) not in seen_sessions:
                profile["total_sessions"] = profile.get("total_sessions", 0) + 1
                seen_sessions.append(str(chat_id))
                profile["seen_sessions"] = seen_sessions[-50:]

            await store.aput(profile_namespace, "preferences", profile)
        except Exception as e:
            logger.error("save_memory_node failed: %s", e, exc_info=True)

        return {}
