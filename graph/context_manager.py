"""
Context window management — prevents token-exceeded errors as
conversations grow.

Strategy (same pattern used by Claude / ChatGPT):

  ┌──────────────────────────────────────────────┐
  │  [summary of older messages]                 │ ← condensed
  │  [recent msg -3]  [recent msg -2]            │
  │  [recent msg -1]  [current human message]    │ ← kept in full
  └──────────────────────────────────────────────┘

Older messages beyond MAX_RECENT_MESSAGES are summarised into a short
paragraph so the LLM retains context without blowing the token budget.
"""

import logging
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from config import MAX_RECENT_MESSAGES, SUPERVISOR_HISTORY_TOKEN_BUDGET
from services.openai_client import get_tokens_count, get_llm_model

logger = logging.getLogger(__name__)


def trim_messages_to_budget(
    messages: list[BaseMessage],
    token_budget: int = SUPERVISOR_HISTORY_TOKEN_BUDGET,
    model: str = "",
) -> list[BaseMessage]:
    """Keep the most recent messages that fit within *token_budget*.

    Walks backwards from the newest message, accumulating tokens.
    Stops adding once the budget is exhausted. Returns messages in
    chronological order.
    """
    if not messages:
        return []

    model = model or get_llm_model("events")
    kept: list[BaseMessage] = []
    total = 0

    for msg in reversed(messages):
        if not isinstance(msg, BaseMessage):
            continue
        role = "user" if msg.type == "human" else "assistant"
        content = msg.content or ""
        msg_tokens = get_tokens_count({"role": role, "content": content}, model)
        if total + msg_tokens > token_budget and kept:
            # Budget exhausted — stop adding older messages
            break
        kept.append(msg)
        total += msg_tokens

    kept.reverse()
    return kept


def split_and_summarise(
    messages: list[BaseMessage],
    existing_summary: str = "",
) -> tuple[list[BaseMessage], str]:
    """Split messages into (recent, older) and build a summary prompt
    for the older portion.

    Returns:
        (recent_messages, summary_text)

    If there are fewer than MAX_RECENT_MESSAGES, all messages are
    returned as "recent" with the existing summary unchanged.
    """
    if len(messages) <= MAX_RECENT_MESSAGES:
        return messages, existing_summary

    # Split: keep last N as recent, everything else becomes "older"
    recent = messages[-MAX_RECENT_MESSAGES:]
    older = messages[:-MAX_RECENT_MESSAGES]

    # Build a condensed text from the older messages
    older_lines = []
    for msg in older:
        if not isinstance(msg, BaseMessage):
            continue
        role = "User" if msg.type == "human" else "Assistant"
        content = (msg.content or "")[:500]  # cap each message at 500 chars
        older_lines.append(f"{role}: {content}")

    older_text = "\n".join(older_lines)

    # Combine with any pre-existing summary
    if existing_summary:
        summary = (
            f"Previous conversation summary:\n{existing_summary}\n\n"
            f"Additional conversation that followed:\n{older_text}"
        )
    else:
        summary = f"Earlier conversation:\n{older_text}"

    # Cap the summary so it doesn't grow unbounded across long conversations.
    # ~4 chars per token → 3000 chars ≈ 750 tokens, well within budget.
    MAX_SUMMARY_CHARS = 3000
    if len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[-MAX_SUMMARY_CHARS:]

    return recent, summary


def prepare_supervisor_messages(
    messages: list[BaseMessage],
    existing_summary: str = "",
    token_budget: int = SUPERVISOR_HISTORY_TOKEN_BUDGET,
) -> tuple[list[BaseMessage], str]:
    """Prepare messages for the supervisor chain.

    1. Split into recent + older (summarised as text).
    2. Token-trim the recent messages to fit the budget.
    3. If there's a summary, prepend it as a SystemMessage.

    Returns (trimmed_messages, updated_summary).
    """
    recent, summary = split_and_summarise(messages, existing_summary)

    # Token-trim the recent messages to the supervisor budget
    trimmed = trim_messages_to_budget(recent)

    # Prepend summary as a system message if it exists
    if summary:
        summary_msg = SystemMessage(
            content=f"[Conversation history summary]\n{summary}"
        )
        trimmed = [summary_msg] + trimmed

    # Final safety: if total tokens still exceed budget, drop oldest messages
    # (skip index 0 if it's the summary system message)
    model = get_llm_model("events")
    total_tokens = sum(
        get_tokens_count({"role": "user" if m.type == "human" else "assistant", "content": m.content or ""}, model)
        for m in trimmed
    )
    while total_tokens > token_budget and len(trimmed) > 1:
        # Remove the oldest non-summary message
        drop_idx = 1 if (trimmed[0].type == "system") else 0
        if drop_idx >= len(trimmed):
            break
        dropped = trimmed.pop(drop_idx)
        drop_tokens = get_tokens_count(
            {"role": "user" if dropped.type == "human" else "assistant", "content": dropped.content or ""}, model
        )
        total_tokens -= drop_tokens

    return trimmed, summary