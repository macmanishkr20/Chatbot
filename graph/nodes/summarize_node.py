"""
Summarize node — LangGraph conversation summarization.

When the messages list exceeds a configurable threshold, this node
condenses older messages into a running summary, keeping only the
most recent messages in full.  This reduces token usage while
preserving conversational context.

Reference: https://langchain-ai.github.io/langgraph/how-tos/memory/add-summary-conversation-memory/
"""
from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage

from graph.state import RAGState
from services.openai_client import (
    create_async_client,
    get_llm_model,
    prepare_model_args,
)

# After this many messages in state, trigger summarization.
_SUMMARIZE_THRESHOLD = 10
# Keep the last N messages verbatim; summarise everything before them.
_KEEP_RECENT = 4

_SUMMARIZE_SYSTEM = (
    "You are a conversation summarizer. "
    "Distill the conversation into a concise summary that captures: "
    "1) the user's original questions and intents, "
    "2) the key facts and data points the assistant provided, "
    "3) any source citations mentioned. "
    "Return ONLY the summary, no preamble."
)


async def summarize_node(state: RAGState) -> dict:
    """Summarize older messages when context grows too large."""
    messages = state.get("messages", [])

    # Not enough messages to warrant summarization
    if len(messages) <= _SUMMARIZE_THRESHOLD:
        return {}

    existing_summary = state.get("summary", "")

    # Build the prompt for summarization
    messages_to_summarize = messages[:-_KEEP_RECENT]
    summary_prompt = "Summarize the following conversation"
    if existing_summary:
        summary_prompt += f", building on this existing summary:\n{existing_summary}\n\n"
    else:
        summary_prompt += ":\n\n"

    for msg in messages_to_summarize:
        role = getattr(msg, "type", "unknown")
        content = getattr(msg, "content", str(msg))
        summary_prompt += f"{role}: {content}\n"

    # Call LLM to produce summary
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

    # Remove old messages from state, keep only recent ones.
    # LangGraph's RemoveMessage tells the add_messages reducer to drop them.
    delete_messages = [RemoveMessage(id=m.id) for m in messages_to_summarize]

    return {
        "summary": new_summary,
        "messages": delete_messages,
    }
