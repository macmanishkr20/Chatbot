"""
Summarize node — LangGraph conversation summarization.

When the messages list exceeds a configurable threshold, this node
condenses older messages into a running summary, keeping only the
most recent messages in full.  This reduces token usage while
preserving conversational context across long conversations.

Design:
  ┌─────────────────────────────────────────────────────────┐
  │  [Running summary of older messages]  ← condensed       │
  │  [Recent messages kept verbatim]      ← full fidelity   │
  └─────────────────────────────────────────────────────────┘

- Summary is incremental: each invocation builds on the previous summary
- Only triggers when message count exceeds threshold (avoids latency on short chats)
- Fail-open: if summarization LLM call fails, conversation continues with full history

Reference: https://langchain-ai.github.io/langgraph/how-tos/memory/add-summary-conversation-memory/
"""
import logging

from langchain_core.messages import BaseMessage, RemoveMessage

from graph.state import RAGState
from services.openai_client import (
    create_async_client,
    get_llm_model,
    prepare_model_args,
)
from services.telemetry import get_tracer_span

logger = logging.getLogger(__name__)

# After this many messages in state, trigger summarization.
# 20 messages ≈ 10 user-assistant exchanges — enough context before compression.
_SUMMARIZE_THRESHOLD = 20
# Keep the last N messages verbatim; summarise everything before them.
# 6 messages = last 3 full exchanges — preserves immediate conversational context.
_KEEP_RECENT = 6

_SUMMARIZE_SYSTEM = """\
You are a conversation summarizer for an EY MENA internal chatbot.
Distill the conversation into a structured, concise summary that captures:

1. The user's original questions and stated intents (preserve exact wording where possible)
2. Key facts, data points, and answers the assistant provided
3. Source citations mentioned (document names, URLs, reference IDs)
4. Exact MENA function names (AWS, BMC, C&I, Finance, GCO, Risk, SCS, TME, Talent)
5. Policy reference IDs, procedure codes, document identifiers
6. All dates, deadlines, and time-bound constraints mentioned
7. User selections or disambiguation choices (which option they chose)
8. Any unresolved questions or pending follow-ups

Format: Use a structured format with clear sections. Keep it under 500 words.
Return ONLY the summary — no preamble, no explanation.\
"""


async def summarize_node(state: RAGState) -> dict:
    """Summarize older messages when context grows too large.

    Fail-open: if anything goes wrong, returns {} and the conversation
    continues with full history (same as Claude's behavior — never lose
    context, just accept higher token usage as a fallback).
    """
    with get_tracer_span("summarize_node"):
        messages = state.get("messages", [])

        # Not enough messages to warrant summarization — no-op
        if len(messages) <= _SUMMARIZE_THRESHOLD:
            return {}

        existing_summary = state.get("summary", "")

        # Identify messages to summarize vs keep
        messages_to_summarize = messages[:-_KEEP_RECENT]
        if not messages_to_summarize:
            return {}

        # Build the summarization prompt
        summary_prompt = "Summarize the following conversation"
        if existing_summary:
            summary_prompt += f", building on this existing summary:\n\n---\n{existing_summary}\n---\n\nNew messages to incorporate:\n\n"
        else:
            summary_prompt += ":\n\n"

        for msg in messages_to_summarize:
            if not isinstance(msg, BaseMessage):
                continue
            role = "User" if msg.type == "human" else "Assistant"
            content = (msg.content or "").strip()
            if content:
                # Cap individual messages to prevent prompt explosion
                if len(content) > 1000:
                    content = content[:1000] + "…"
                summary_prompt += f"{role}: {content}\n\n"

        try:
            llm_model = get_llm_model("rewrite_query")
            client = create_async_client(llm_model=llm_model)

            llm_messages = [
                {"role": "system", "content": _SUMMARIZE_SYSTEM},
                {"role": "user", "content": summary_prompt},
            ]
            model_args = prepare_model_args(
                llm_messages, False, False, None, None, "text", llm_model
            )
            response = await client.chat.completions.create(**model_args)
            new_summary = response.choices[0].message.content.strip()

            if not new_summary:
                logger.warning("summarize_node: LLM returned empty summary, skipping")
                return {}

        except Exception as exc:
            # Fail-open: log and continue without summarization
            logger.warning("summarize_node: summarization failed: %s", exc, exc_info=True)
            return {}

        # Remove old messages from state using LangGraph's RemoveMessage reducer.
        # Only remove messages that have a valid id (safety check).
        delete_messages = []
        for m in messages_to_summarize:
            if isinstance(m, BaseMessage) and getattr(m, "id", None):
                delete_messages.append(RemoveMessage(id=m.id))

        if not delete_messages:
            # Messages lack IDs — can't use RemoveMessage, just update summary
            logger.info("summarize_node: messages lack IDs, updating summary only")
            return {"summary": new_summary}

        logger.info(
            "summarize_node: condensed %d messages into summary (%d chars), keeping %d recent",
            len(delete_messages), len(new_summary), _KEEP_RECENT,
        )

        return {
            "summary": new_summary,
            "messages": delete_messages,
        }
