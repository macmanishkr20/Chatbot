"""
MenaBot Application Entry Point.
FastAPI with LangGraph RAG pipeline.

Endpoints: /health, /chat, /feedback, /conversations

SSE event types emitted by /chat:
  {"type": "thought",  "node": "<node>",  "message": "<step description>"}
  {"type": "content",  "node": "<node>",  "content": "<token>"}
  {"type": "final",    "chat_id": ...,    "message_id": ..., "ai_content": [...]}
"""

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

load_dotenv()

from graph.context_manager import trim_messages_to_budget
from graph.nodes.supervisor import get_graph
from graph.state import RAGState
from models.chat_models import FeedbackRequest, UserChatQuery
from services.sql_client import SQLChatClient

logger = logging.getLogger(__name__)

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

# ── Nodes whose token output is meaningful prose for the end user ──
# - generate    : RAG answer tokens (primary streaming output)
# - Supervisor  : direct RESPOND prose (greetings, clarifications, etc.)
# - search      : ambiguity message — when multiple functions are found and
#                 the score ratio is below the threshold, search returns an
#                 AIMessage asking the user to pick a specific function.
#                 That message must reach the UI exactly like any other reply.
_STREAMABLE_NODES: frozenset[str] = frozenset({"generate", "Supervisor", "search"})

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


# ── Helpers ──

async def _build_initial_state(query: UserChatQuery) -> dict:
    """Convert a UserChatQuery into the initial RAGState dict."""
    return {
        "messages": [HumanMessage(content=query.user_input)],
        "input_type": query.input_type.value,
        "user_input": query.user_input,
        "is_free_form": query.is_free_form,
        "user_id": query.user_id,
        "chat_id": query.chat_id,
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
    return user_id.strip().lower().endswith("@gds.ey.com") or user_id.strip().lower().endswith("@ey.com")


def sse_format(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _init_graph():
    """Initialise the compiled graph (idempotent)."""
    global graph
    if graph is None:
        graph = await get_graph()
    return graph


# ── REST Endpoints ──

@app.get("/health")
async def health():
    return {"status": "running", "engine": "langgraph"}


@app.post("/chat")
async def chat_api(
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
    if not query.user_id:
        raise HTTPException(status_code=400, detail="UserId is not provided")
    if not _has_gds_domain(query.user_id):
        raise HTTPException(status_code=400, detail="UserId must belong to @gds.ey.com")

    await _init_graph()

    user_input = query.user_input.strip()
    chat_session_id = query.chat_session_id or "new"
    thread_id = f"{query.user_id}_{chat_session_id}"

    config: dict = query.config or {}
    config.setdefault("configurable", {})
    config["configurable"]["thread_id"] = thread_id
    config["callbacks"] = [callback_handler] if callback_handler else []

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
        # Token-aware trimming instead of naive [-5:] slice.
        # Keeps as many recent messages as fit within the token budget;
        # the supervisor will further summarise older ones if needed.
        current_state["messages"] = trim_messages_to_budget(
            current_state["messages"]
        )
        current_state["messages"].append(HumanMessage(content=user_input))
        current_state["user_input"] = query.user_input
        current_state["function"] = query.function
        current_state["sub_function"] = query.sub_function
        current_state["source_url"] = query.source_url
        current_state["start_date"] = query.start_date
        current_state["end_date"] = query.end_date
        current_state["is_free_form"] = query.is_free_form
        current_state["input_type"] = query.input_type.value
        # Reset per-turn transient fields (preserve ambiguity state for resolution)
        current_state["events"] = []
        current_state["error_info"] = None
        current_state["ai_content"] = None
        current_state["prompt_used"] = None
        current_state["response"] = None
        current_state["suggestive_actions"] = None
        state = current_state
    else:
        state = await _build_initial_state(query)

    logger.debug("Existing messages: %s", state.get("messages"))

    async def stream_generator():
        # Track which nodes have already emitted a thought event so we fire
        # exactly once per node per request regardless of how many chunks it
        # produces.
        seen_nodes: set[str] = set()

        # ── stream_mode=["messages","updates"] explained ──
        # "messages" : fires one chunk per LLM token — used for content streaming.
        #              Only LLM-backed nodes (Supervisor, generate) produce these.
        # "updates"  : fires once per node when it COMPLETES — fires for ALL
        #              nodes including non-LLM ones (load_memory, rewrite, embed,
        #              search, persist, save_memory). Used to emit thought events
        #              for nodes that never produce "messages" chunks.
        #
        # With subgraphs=True the chunk format is:
        #   (namespace, (mode, data))
        # where:
        #   mode="messages" → data = (AIMessageChunk, metadata_dict)
        #   mode="updates"  → data = {"node_name": state_update_dict}
        async for chunk in graph.astream(
            state,
            config=config,
            stream_mode=["messages", "updates"],
            subgraphs=True,
        ):
            namespace, mode, data = chunk

            if mode == "updates":
                # data = {"node_name": {...}} — fires when the node completes.
                # Emit thought for any node we haven't seen yet (covers all
                # non-LLM nodes that never produce "messages" chunks).
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

            elif mode == "messages":
                chunk_msg, metadata = data
                node = metadata.get("langgraph_node")
                logger.debug("Streaming chunk from node=%s content=%r", node, chunk_msg.content)

                # Emit thought on the FIRST token of an LLM node — this fires
                # before "updates" so the spinner appears while the node streams.
                if node and node not in seen_nodes:
                    seen_nodes.add(node)
                    thought_entry = _NODE_THOUGHT.get(node)
                    if thought_entry:
                        display_name, message = next(iter(thought_entry.items()))
                    else:
                        display_name, message = node, f"Processing {node}..."
                    yield sse_format({"type": "thought", "node": display_name, "message": message})

                # ── Stream LLM tokens as "content" events ──
                # Only forward tokens from nodes that produce user-facing prose.
                # Supervisor produces structured JSON when routing — skip those
                # fragments; only its direct RESPOND prose should reach the UI.
                if chunk_msg.content and node in _STREAMABLE_NODES:
                    yield sse_format({"type": "content", "content": chunk_msg.content, "node": node})

        # ── Final event: emit chat_id / message_id / suggestive_actions ──
        # Use graph.aget_state() — the high-level LangGraph API — instead of
        # the low-level checkpointer.aget() which may not exist on custom savers.
        try:
            state_snapshot = await graph.aget_state(config)
            if state_snapshot:
                final_state = state_snapshot.values
                # Serialise suggestive_actions — may be Pydantic models or plain dicts
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
                })
        except Exception as exc:
            logger.error("Failed to emit final SSE event: %s", exc, exc_info=True)

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


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
    if not user_id:
        raise HTTPException(status_code=400, detail="UserId is required")
    if not _has_gds_domain(user_id):
        raise HTTPException(status_code=400, detail="UserId must belong to @gds.ey.com")

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
    if not user_id:
        raise HTTPException(status_code=400, detail="UserId is required")
    if not _has_gds_domain(user_id):
        raise HTTPException(status_code=400, detail="UserId must belong to @gds.ey.com")

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
