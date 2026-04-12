"""
MenaBot Application Entry Point.
FastAPI with LangGraph RAG pipeline.

Endpoints: /health, /rag, /feedback, /conversations
"""

from contextlib import asynccontextmanager
from datetime import datetime
import os
from typing import Any, Dict

from fastapi.middleware.cors import CORSMiddleware
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
import json
from langchain_core.messages import HumanMessage
from langfuse.langchain import CallbackHandler
from graph.nodes.supervisor import get_graph
from graph.state import RAGState

load_dotenv()

from models.chat_models import (
    FeedbackRequest,
    UserChatQuery,
)
from services.sql_client import SQLChatClient

# Employee data cache 
employee_cache: Dict[str, Dict[str, Any]] = {}

initial_state_cache: Dict[str, RAGState] = {}

# Global graph instance
graph = None

if os.getenv("ENABLE_LANGFUSE") == "true":
    callback_handler = CallbackHandler()
else:
    callback_handler = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    # Startup
    await init_graph()
    yield
    # Shutdown (if needed)


# ------------------- FastAPI App -------------------

app = FastAPI(
    lifespan=lifespan,
    title="MenaBot RAG Service - M365 Agents SDK + LangGraph",
    description="Backend service for MenaBot using LangGraph for RAG orchestration. Endpoints: /health, /chat, /feedback, /conversations.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------- Helper -------------------

async def _build_initial_state(query: UserChatQuery) -> RAGState:
    """Convert a UserChatQuery into the initial RAGState dict."""
    state = {
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
        "preferred_language": query.preferred_language
    }
    return RAGState(state)

def _has_gds_domain(user_id: str) -> bool:
    """Validate that the incoming user ID belongs to the GDS domain."""
    return user_id.strip().lower().endswith("@gds.ey.com")

def _build_frontend_query_payload(state: RAGState) -> dict[str, Any]:
    """Return only the fields frontend needs from RAGState."""
    message_id = state.get("message_id")
    chat_id = state.get("chat_id")
    print(f"[LOG] message_id (from top-level state): {message_id}")
    print(f"[LOG] chat_id (from top-level state): {chat_id}")
    allowed_keys = (
        "user_input",
        "is_free_form",
        "user_id",
        "chat_id",
        "message_id",
        "ai_content",
        "source_prompt",
        "function",
        "sub_function",
        "source_url",
    )

    payload: dict[str, Any] = {}
    for key in allowed_keys:
        if key in state and state[key] is not None:
            payload[key] = state[key]

    print(f"[LOG] Payload for frontend: {payload}")
    response = state.get("response") or {}
    if payload.get("chat_id") is None and response.get("chat_id") is not None:
        payload["chat_id"] = response.get("chat_id")
    if payload.get("message_id") is None and response.get("message_id") is not None:
        payload["message_id"] = response.get("message_id")
    
    print(f"[LOG] Final Payload for frontend after adding from response: {payload}")
    return payload

#---------------------Methods-------------------------

async def init_graph():
    """Initialize the graph on startup."""
    global graph
    if graph is None:
        graph = await get_graph()
    return graph

def sse_format(payload):
    return f"data: {json.dumps(payload)}\n\n"
# ------------------- REST Endpoints -------------------

@app.get("/health")
async def health():
    return {"status": "running", "engine": "langgraph"}


@app.post("/chat")
async def chat_api(
    query: UserChatQuery,
    background_tasks: BackgroundTasks,
    xcorrelationid: str = Header(None),
):
    """Main RAG endpoint — streams the graph response via SSE."""
    if not query.user_id:
        raise HTTPException(status_code=400, detail="UserId is not provided")
    if not _has_gds_domain(query.user_id):
        raise HTTPException(status_code=400, detail="UserId must belong to @gds.ey.com")
    
    await init_graph()

    user_input = query.user_input.strip()
    user_id = query.user_id.strip()
    chat_id = query.chat_id or "new"
    chat_session_id = query.chat_session_id or "new"
    thread_id = f"{query.user_id}_{chat_session_id}"
    config = query.config or {}
    config.setdefault("configurable", {})
    config["configurable"]["thread_id"] = thread_id
    config['callbacks'] = [callback_handler] if callback_handler else []

    current_state = None
    try:
        checkpoint = await graph.checkpointer.aget(config)
        if checkpoint:
            current_state = checkpoint.get("channel_values", {})
    except Exception:
        pass

    # Create or update state
    if current_state and current_state.get("messages"):
        from langchain_core.messages import HumanMessage
        if len(current_state["messages"]) > 5:
            current_state["messages"] = current_state["messages"][-5:]
        current_state["messages"].append(HumanMessage(content=user_input))
        # Update input fields from the new request
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
        state = current_state
    else:
        state = await _build_initial_state(query)

    print("***existing_messages***",state["messages"])
    # Build the LangGraph thread_id for checkpoint persistence.
    # Format: "{user_id}_{chat_id}" — each user+conversation gets its own thread.
    async def stream_generator():
        buffer = ""
        final_result: dict[str, Any] = {}
        streamed_content = True

        async for chunk in graph.astream(
            state,
            config=config,
            stream_mode="messages",
            subgraphs=True
        ):
            namespace, (chunk_msg, metadata) = chunk
            node = metadata.get("langgraph_node")
            print(f"Streaming chunk from node: {node} with content: {chunk_msg.content}")
            if chunk_msg.content:
                if '{"next":"RESPOND","response":"' in buffer:
                    cleaned_chunk = chunk_msg.content.replace('":"',"").replace('"}',"").replace('"',"")
                    yield sse_format({"content": cleaned_chunk, "node": node})
                else:
                    yield sse_format({"content": chunk_msg.content, "node": node})

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
        raise HTTPException(status_code=500, detail=str(e))


# ------------------- Chat History Endpoints -------------------


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

        # Serialise datetimes to ISO strings for JSON
        for conv in conversations:
            for key in ("CreatedAt", "ModifiedAt"):
                if isinstance(conv.get(key), datetime):
                    conv[key] = conv[key].isoformat()

        return {"data": conversations}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
            for key in ("CreatedAt",):
                if isinstance(msg.get(key), datetime):
                    msg[key] = msg[key].isoformat()

        return {"data": messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)



