"""
MenaBot Application Entry Point.
FastAPI with LangGraph RAG pipeline.

Endpoints: /health, /chat, /chat/cancel, /chat/regenerate,
           /feedback, /conversations (CRUD)

SSE event types emitted by /chat:
  {"type": "thought",  "node": "<node>",  "message": "<step description>"}
  {"type": "content",  "node": "<node>",  "content": "<token>"}
  {"type": "final",    "chat_id": ...,    "message_id": ..., "ai_content": [...]}
"""

import json
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

load_dotenv()

from config import MAX_INPUT_LENGTH, RATE_LIMIT_PER_MINUTE
from graph.context_manager import trim_messages_to_budget
from graph.nodes.supervisor import get_graph
from graph.state import RAGState
from langchain_core.messages import RemoveMessage
from models.chat_models import (
    CancelRequest,
    EditMessageRequest,
    FeedbackRequest,
    RegenerateRequest,
    RenameConversationRequest,
    UserChatQuery,
)
from services.sql_client import SQLChatClient

logger = logging.getLogger(__name__)

# ── Optional rate limiting (graceful if slowapi not installed) ──
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address

    limiter = Limiter(key_func=get_remote_address)
    _rate_limiting_available = True
except ImportError:
    limiter = None
    _rate_limiting_available = False

# ── Optional Langfuse observability ──
try:
    from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler
    _langfuse_available = True
except ImportError:
    _langfuse_available = False
    LangfuseCallbackHandler = None

callback_handler = (
    LangfuseCallbackHandler()
    if os.getenv("ENABLE_LANGFUSE") == "true" and _langfuse_available
    else None
)

# Global compiled graph instance (initialised once at startup)
graph = None

# ── In-memory cancel signals (keyed by thread_id) ──
# For multi-worker deployments, replace with Redis.
_cancel_signals: dict[str, bool] = {}

# ── Nodes whose LLM token output is meaningful prose for the end user ──
# NOTE: "Supervisor" is intentionally excluded. Its LLM uses
# with_structured_output(RouteResponse) which streams JSON fragments,
# not user-facing prose. Supervisor's RESPOND content is delivered via
# the "updates" mode instead (see stream_generator).
_STREAMABLE_NODES: frozenset[str] = frozenset({"generate", "search"})

# ── Chain-of-thought step labels shown in the UI ──
# Emitted as {"type": "thought"} SSE events when each node first starts.

_NODE_THOUGHT: dict[str, dict[str, str]] = {
    "Supervisor": {
        "Intent": "Aligning intent…"
    },
    "load_memory": {
        "Recall": "Reconnecting context…"
    },
    "rewrite": {
        "Focus": "Clarifying focus…"
    },
    "embed": {
        "Meaning": "Interpreting meaning…"
    },
    "search": {
        "Relevance": "Finding relevance…"
    },
    "generate": {
        "Response": "Forming response…"
    },
    "persist": {
        "Flow": "Maintaining continuity…"
    },
    "save_memory": {
        "Memory": "Storing insight…"
    }
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    await _init_graph()
    yield


# ── FastAPI App ──

app = FastAPI(
    lifespan=lifespan,
    title="MenaBot RAG Service - M365 Agents SDK + LangGraph",
    description=(
        "Backend service for MenaBot using LangGraph for RAG orchestration. "
        "Endpoints: /health, /chat, /feedback, /conversations."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

_ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=("*" not in _ALLOWED_ORIGINS),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register rate limiter if available
if _rate_limiting_available and limiter:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Helpers ──

def _ensure_base_messages(messages: list) -> list[BaseMessage]:
    """Reconstruct proper BaseMessage objects from checkpoint deserialization output.

    The custom AzureSQLCheckpointSaver previously used ``json.dumps(..., default=str)``
    which stringified BaseMessage objects into their repr (e.g. "HumanMessage(content='hi')").
    Newer checkpoints use the LangGraph serde and come back correctly deserialized, but we
    keep this helper so old checkpoints in the DB still work gracefully.

    Three possible input formats:
    - Already-proper BaseMessage objects  → pass through as-is
    - Dicts with a 'type'/'role' key      → reconstruct via LangChain types
    - Repr strings                         → regex-parse type + content
    """
    result: list[BaseMessage] = []
    for m in messages:
        if isinstance(m, BaseMessage):
            result.append(m)
            continue

        if isinstance(m, dict):
            # ── Format A: simple {"type": "human", "content": "..."} ──
            role = (m.get("type") or m.get("role") or "").lower()
            content = m.get("content", "")
            msg_id = m.get("id")

            # ── Format B: LangChain serde {"lc":1,"type":"constructor","id":[...,"HumanMessage"],"kwargs":{...}} ──
            if not role and m.get("lc") == 1 and m.get("type") == "constructor":
                id_path = m.get("id", [])  # e.g. ["langchain","schema","messages","HumanMessage"]
                class_name = id_path[-1] if id_path else ""
                role = "human" if "Human" in class_name else "ai"
                kwargs = m.get("kwargs", {})
                content = kwargs.get("content", "")
                msg_id = kwargs.get("id")

            msg = HumanMessage(content=content) if role in ("human", "user") else AIMessage(content=content)
            if msg_id:
                try:
                    object.__setattr__(msg, "id", msg_id)
                except Exception:
                    pass
            result.append(msg)
            continue

        if isinstance(m, str):
            # Legacy repr: "HumanMessage(content='...' ...)" or "AIMessage(...)"
            is_human = m.startswith("HumanMessage") or bool(re.search(r"type=['\"]human['\"]", m))
            content_match = re.search(r"content='((?:[^'\\]|\\.)*)'", m) or re.search(r'content="((?:[^"\\]|\\.)*)"', m)
            content = content_match.group(1) if content_match else ""
            result.append(HumanMessage(content=content) if is_human else AIMessage(content=content))
            continue

        logger.warning(
            "_ensure_base_messages: unexpected type %s value=%r — skipping",
            type(m).__name__, str(m)[:200],
        )

    return result


async def _build_initial_state(query: UserChatQuery) -> dict:
    """Convert a UserChatQuery into the initial RAGState dict."""
    return {
        "messages": [HumanMessage(content=query.user_input)],
        "input_type": query.input_type.value,
        "user_input": query.user_input,
        "is_free_form": query.is_free_form,
        "user_id": query.user_id,
        "chat_id": query.chat_id,
        "chat_session_id": query.chat_session_id,
        "message_id": query.message_id,
        "function": query.function,
        "sub_function": query.sub_function,
        "source_url": query.source_url,
        "start_date": query.start_date,
        "end_date": query.end_date,
        "preferred_language": query.preferred_language,
    }


def _has_gds_domain(user_id: str) -> bool:
    """Validate that the incoming user ID belongs to the GDS domain."""
    return (
        user_id.strip().lower().endswith("@gds.ey.com")
        or user_id.strip().lower().endswith("@ey.com")
    )


def _validate_user(user_id: str) -> None:
    """Common user validation — raises HTTPException on failure."""
    if not user_id:
        raise HTTPException(status_code=400, detail="UserId is not provided")
    if not _has_gds_domain(user_id):
        raise HTTPException(status_code=400, detail="UserId must belong to @gds.ey.com")


def _sanitize_input(text: str) -> str:
    """Sanitize user input — strip null bytes, validate length."""
    cleaned = text.replace("\x00", "").strip()
    if len(cleaned) > MAX_INPUT_LENGTH:
        raise HTTPException(status_code=400, detail="Input too long")
    if not cleaned:
        raise HTTPException(status_code=400, detail="Empty input")
    return cleaned


def sse_format(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _init_graph():
    """Initialise the compiled graph (idempotent)."""
    global graph
    if graph is None:
        graph = await get_graph()
    return graph


def _build_stream_config(user_id: str, chat_session_id: str) -> tuple[str, dict]:
    """Build LangGraph config for streaming. Returns (thread_id, config)."""
    thread_id = f"{user_id}_{chat_session_id}"
    config: dict = {"configurable": {"thread_id": thread_id}}
    config["callbacks"] = [callback_handler] if callback_handler else []
    return thread_id, config


async def _stream_graph(state: dict, config: dict, thread_id: str):
    """Core streaming generator shared by /chat and /chat/regenerate.

    Yields SSE events: thought → content → final.
    Supports cancellation via _cancel_signals[thread_id].
    """
    seen_nodes: set[str] = set()

    async for chunk in graph.astream(
        state,
        config=config,
        stream_mode=["messages", "updates"],
        subgraphs=True,
    ):
        # ── Check cancellation ──
        if _cancel_signals.pop(thread_id, False):
            yield sse_format({"type": "final", "cancelled": True})
            return

        namespace, mode, data = chunk

        if mode == "updates":
            for node in data.keys():
                if node and node not in seen_nodes:
                    seen_nodes.add(node)
                    thought_entry = _NODE_THOUGHT.get(node)
                    if thought_entry:
                        display_name, message = next(iter(thought_entry.items()))
                    else:
                        display_name, message = node, f"Processing {node}..."
                    logger.debug("thought (updates) node=%s", node)
                    yield sse_format({"type": "thought", "node": display_name, "message": message})

                    # ── Supervisor RESPOND prose delivery ──
                    # Supervisor uses with_structured_output so its LLM tokens
                    # are JSON fragments (not prose). When next==RESPOND, the
                    # completed update contains ai_content with the actual reply.
                    # Deliver it as a single content event via "updates" mode.
                    if node == "Supervisor":
                        node_data = data.get("Supervisor", {})
                        respond_content = node_data.get("ai_content")
                        if respond_content:
                            yield sse_format({
                                "type": "content",
                                "content": respond_content,
                                "node": "Supervisor",
                            })

        elif mode == "messages":
            chunk_msg, metadata = data
            node = metadata.get("langgraph_node")
            logger.debug("Streaming chunk from node=%s content=%r", node, chunk_msg.content)

            if node and node not in seen_nodes:
                seen_nodes.add(node)
                thought_entry = _NODE_THOUGHT.get(node)
                if thought_entry:
                    display_name, message = next(iter(thought_entry.items()))
                else:
                    display_name, message = node, f"Processing {node}..."
                yield sse_format({"type": "thought", "node": display_name, "message": message})

            if chunk_msg.content and node in _STREAMABLE_NODES:
                yield sse_format({"type": "content", "content": chunk_msg.content, "node": node})

    # ── Final event ──
    try:
        state_snapshot = await graph.aget_state(config)
        if state_snapshot:
            final_state = state_snapshot.values
            raw_actions = final_state.get("suggestive_actions") or []
            actions = []
            for a in raw_actions:
                if hasattr(a, "model_dump"):
                    actions.append(a.model_dump())
                elif isinstance(a, dict):
                    actions.append(a)
                else:
                    actions.append({"short_title": str(a)})
            yield sse_format({
                "type": "final",
                "chat_id": final_state.get("chat_id"),
                "message_id": final_state.get("message_id"),
                "ai_content": final_state.get("ai_content", []),
                "suggestive_actions": actions,
                "conversation_title": final_state.get("conversation_title"),
            })
    except Exception as exc:
        logger.error("Failed to emit final SSE event: %s", exc, exc_info=True)


# ── REST Endpoints ──

@app.get("/health")
async def health():
    return {"status": "running", "engine": "langgraph"}


@app.post("/chat")
async def chat_api(
    request: Request,
    query: UserChatQuery,
    xcorrelationid: str = Header(None),
):
    """Main RAG endpoint — streams graph execution via SSE.

    Three event types are emitted in order:
      1. thought  — one per pipeline node; shows the UI what step is running.
      2. content  — token-by-token LLM output from the active node.
      3. final    — sent once after the stream ends; carries chat_id,
                    message_id, and the consolidated ai_content payload.
    """
    _validate_user(query.user_id)
    user_input = _sanitize_input(query.user_input)

    await _init_graph()

    chat_session_id = query.chat_session_id or "new"
    thread_id, config = _build_stream_config(query.user_id, chat_session_id)

    # Merge any client-provided config
    if query.config and query.config.get("configurable"):
        config["configurable"].update(query.config["configurable"])
    config["configurable"]["thread_id"] = thread_id

    # Attempt to restore existing checkpoint state
    current_state = None
    try:
        checkpoint = await graph.checkpointer.aget(config)
        if checkpoint:
            current_state = checkpoint.get("channel_values", {})
    except Exception:
        pass

    # Build or update state for this turn
    if current_state and current_state.get("messages"):
        # Ensure messages are proper BaseMessage objects (handles legacy checkpoints)
        current_state["messages"] = _ensure_base_messages(current_state["messages"])
        # Token-aware trimming instead of naive [-5:] slice.
        # Keeps as many recent messages as fit within the token budget;
        # the supervisor will further summarise older ones if needed.
        current_state["messages"] = trim_messages_to_budget(
            current_state["messages"]
        )
        current_state["messages"].append(HumanMessage(content=user_input))
        current_state["user_input"] = query.user_input
        current_state["chat_session_id"] = chat_session_id   # always keep in sync
        current_state["function"] = query.function
        current_state["sub_function"] = query.sub_function
        current_state["source_url"] = query.source_url
        current_state["start_date"] = query.start_date
        current_state["end_date"] = query.end_date
        current_state["is_free_form"] = query.is_free_form
        current_state["input_type"] = query.input_type.value
        # Reset per-turn transient fields (preserve citation_map for multi-turn)
        current_state["events"] = []
        current_state["error_info"] = None
        current_state["ai_content"] = None
        current_state["prompt_used"] = None
        current_state["response"] = None
        current_state["suggestive_actions"] = None
        current_state["conversation_title"] = None
        state = current_state
    else:
        state = await _build_initial_state(query)
        # Ensure the computed chat_session_id (defaulted to "new" if absent) is stored
        # so persist_node can save it to SQL for future edit/regenerate lookups.
        state["chat_session_id"] = chat_session_id

    logger.debug("Existing messages: %s", state.get("messages"))

    return StreamingResponse(
        _stream_graph(state, config, thread_id),
        media_type="text/event-stream",
    )


# ── Stop Generation ──

@app.post("/chat/cancel")
async def cancel_chat(body: CancelRequest):
    """Signal an in-flight generation to stop.

    The stream generator checks _cancel_signals before each yield
    and emits a final event with cancelled=True when the signal fires.

    NOTE: This works for single-process deployments. For multi-worker
    deployments behind a load balancer, replace _cancel_signals with
    a shared store (e.g. Redis pub/sub).
    """
    _validate_user(body.user_id)
    thread_id = f"{body.user_id}_{body.chat_session_id}"
    _cancel_signals[thread_id] = True
    return {"status": "cancel_requested"}


# ── Regenerate Last Response ──

@app.post("/chat/regenerate")
async def regenerate_chat(
    request: Request,
    body: RegenerateRequest,
):
    """Re-run the last turn in a conversation — same UX as Claude's 'Retry'.

    Fetches the last user message from SQL, rebuilds the state,
    and streams a fresh response.
    """
    _validate_user(body.user_id)
    await _init_graph()

    thread_id, config = _build_stream_config(body.user_id, body.chat_session_id)

    # Fetch last user message from SQL
    try:
        scc = SQLChatClient()
        await scc.connect()
        last_msg = await scc.get_last_user_message(int(body.chat_id), body.user_id)
    except Exception as e:
        logger.error("regenerate: failed to fetch last message: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve last message")

    if not last_msg or not last_msg.get("UserPrompt"):
        raise HTTPException(status_code=404, detail="No user message found to regenerate")

    user_input = last_msg["UserPrompt"]

    # Restore checkpoint and rebuild state
    current_state = None
    try:
        checkpoint = await graph.checkpointer.aget(config)
        if checkpoint:
            current_state = checkpoint.get("channel_values", {})
    except Exception:
        pass

    if current_state and current_state.get("messages"):
        # Ensure messages are proper BaseMessage objects (handles legacy checkpoints)
        current_state["messages"] = _ensure_base_messages(current_state["messages"])
        current_state["messages"] = trim_messages_to_budget(
            current_state["messages"]
        )
        # Don't append a new HumanMessage — we're replaying the existing one
        current_state["user_input"] = user_input
        current_state["events"] = []
        current_state["error_info"] = None
        current_state["ai_content"] = None
        current_state["prompt_used"] = None
        current_state["response"] = None
        current_state["suggestive_actions"] = None
        current_state["conversation_title"] = None
        state = current_state
    else:
        raise HTTPException(status_code=404, detail="No conversation state found")

    return StreamingResponse(
        _stream_graph(state, config, thread_id),
        media_type="text/event-stream",
    )


# ── Edit Message Mid-Thread (Branching) ──

@app.post("/chat/edit")
async def edit_message(
    request: Request,
    body: EditMessageRequest,
):
    """Edit a message mid-thread and re-run the graph from that point.

    This is the Claude/ChatGPT "edit" feature. When a user edits a prior
    message, everything after that message is discarded (branch) and the
    graph re-runs with the edited text.

    How it works:
      1. Load the current checkpoint's full message list.
      2. Truncate messages to keep only those BEFORE the edited message.
      3. Append the new edited message as a HumanMessage.
      4. Reset all transient state fields.
      5. Re-run the graph and stream the new response.

    The old messages after the edit point are effectively "branched off" —
    they remain in checkpoint history but the active thread moves forward
    with the edited version.
    """
    _validate_user(body.user_id)
    new_input = _sanitize_input(body.new_input)

    await _init_graph()

    thread_id, config = _build_stream_config(body.user_id, body.chat_session_id)

    # Load current checkpoint
    current_state = None
    try:
        checkpoint = await graph.checkpointer.aget(config)
        if checkpoint:
            current_state = checkpoint.get("channel_values", {})
    except Exception as e:
        logger.error("edit: failed to load checkpoint: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to load conversation state")

    logger.info(
        "edit: thread_id=%s checkpoint_found=%s state_keys=%s raw_msg_count=%s raw_msg_types=%s",
        thread_id,
        checkpoint is not None,
        list(current_state.keys()) if current_state else [],
        len(current_state.get("messages", [])) if current_state else 0,
        [type(m).__name__ for m in current_state.get("messages", [])] if current_state else [],
    )

    if not current_state or not current_state.get("messages"):
        raise HTTPException(status_code=404, detail="No conversation state found")

    # Ensure messages are proper BaseMessage objects (handles legacy checkpoints
    # that were serialised with default=str, coming back as repr strings or dicts)
    messages = _ensure_base_messages(current_state["messages"])

    logger.info(
        "edit: after _ensure_base_messages count=%s types=%s",
        len(messages),
        [type(m).__name__ for m in messages],
    )

    # Identify user-message positions — use both isinstance and .type attribute
    # for maximum compatibility across LangChain versions.
    def _is_human(m: BaseMessage) -> bool:
        if isinstance(m, HumanMessage):
            return True
        return getattr(m, "type", None) in ("human", "user")

    user_msg_positions = [i for i, m in enumerate(messages) if _is_human(m)]

    logger.info("edit: user_msg_positions=%s requested_index=%s", user_msg_positions, body.message_index)

    if body.message_index < 0 or body.message_index >= len(user_msg_positions):
        raise HTTPException(
            status_code=400,
            detail=(
                f"message_index {body.message_index} out of range "
                f"(conversation has {len(user_msg_positions)} user messages). "
                f"Message types in checkpoint: {[type(m).__name__ for m in messages]}"
            ),
        )

    # The absolute position in the messages list of the message being edited
    edit_pos = user_msg_positions[body.message_index]

    # ── Branch: keep messages BEFORE the edit point, discard the rest ──
    # Use RemoveMessage to tell the add_messages reducer to drop them.
    messages_to_remove = [
        RemoveMessage(id=m.id) for m in messages[edit_pos:]
    ]

    # Apply removals to get the truncated history
    kept_messages = messages[:edit_pos]

    # Token-trim the kept messages
    kept_messages = trim_messages_to_budget(kept_messages)

    # Append the new edited message
    kept_messages.append(HumanMessage(content=new_input))

    # Build the new state — truncated history + fresh transient fields
    state = {
        **current_state,
        "messages": kept_messages,
        "user_input": new_input,
        "is_free_form": body.is_free_form,
        "function": body.function,
        "sub_function": body.sub_function,
        "source_url": body.source_url,
        "start_date": body.start_date,
        "end_date": body.end_date,
        "preferred_language": body.preferred_language,
        "input_type": "ask",
        # Reset all transient fields
        "events": [],
        "error_info": None,
        "ai_content": None,
        "prompt_used": None,
        "response": None,
        "suggestive_actions": None,
        "conversation_title": None,
        "citation_map": None,
        "is_ambiguous": False,
        "pending_ambiguous_query": None,
    }

    return StreamingResponse(
        _stream_graph(state, config, thread_id),
        media_type="text/event-stream",
    )


@app.post("/feedback")
async def save_feedback(payload: FeedbackRequest):
    """Store user feedback for a message."""
    try:
        scc = SQLChatClient()
        await scc.connect()
        await scc.save_feedback(payload)
        return {"status": "feedback stored"}
    except Exception as e:
        logger.error("save_feedback failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save feedback")


# ── Chat History Endpoints ──

@app.get("/conversations/{user_id}")
async def get_conversations(user_id: str):
    """
    Return all conversation sessions for a user (left-panel chat history).
    Each item includes id, title, type, and timestamps.
    """
    _validate_user(user_id)

    try:
        scc = SQLChatClient()
        await scc.connect()
        conversations = await scc.get_conversations_by_user(user_id)

        for conv in conversations:
            for key in ("CreatedAt", "ModifiedAt"):
                if isinstance(conv.get(key), datetime):
                    conv[key] = conv[key].isoformat()

        return {"data": conversations}
    except Exception as e:
        logger.error("get_conversations failed for user=%s: %s", user_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve conversations")


@app.get("/conversations/{user_id}/{chat_id}/messages")
async def get_conversation_messages(user_id: str, chat_id: int):
    """
    Return all messages in a specific conversation session.
    Used by frontend to reload a past conversation.
    """
    _validate_user(user_id)

    try:
        scc = SQLChatClient()
        await scc.connect()
        messages = await scc.get_messages_by_conversation(chat_id, user_id)

        for msg in messages:
            if isinstance(msg.get("CreatedAt"), datetime):
                msg["CreatedAt"] = msg["CreatedAt"].isoformat()

        return {"data": messages}
    except Exception as e:
        logger.error("get_conversation_messages failed for user=%s chat=%s: %s", user_id, chat_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve messages")


# ── Conversation Management (Claude-parity) ──

@app.delete("/conversations/{user_id}/{chat_id}")
async def delete_conversation(user_id: str, chat_id: int):
    """Soft-delete a conversation (marks as deleted, not physically removed)."""
    _validate_user(user_id)

    try:
        scc = SQLChatClient()
        await scc.connect()
        success = await scc.soft_delete_conversation(chat_id, user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_conversation failed for user=%s chat=%s: %s", user_id, chat_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete conversation")


@app.patch("/conversations/{user_id}/{chat_id}/rename")
async def rename_conversation(user_id: str, chat_id: int, body: RenameConversationRequest):
    """Rename a conversation (user-initiated title change)."""
    _validate_user(user_id)

    try:
        scc = SQLChatClient()
        await scc.connect()
        success = await scc.rename_conversation(chat_id, user_id, body.title)
        if not success:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"status": "renamed", "title": body.title}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("rename_conversation failed for user=%s chat=%s: %s", user_id, chat_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to rename conversation")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
