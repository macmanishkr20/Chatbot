"""
Chat endpoints: /chat (stream), /chat/cancel, /chat/regenerate, /chat/edit.

Behavior is byte-identical to the pre-split monolithic implementation.
Streaming dereferences ``api._runtime.graph`` at call time.
"""
import logging

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, RemoveMessage

from agents._base.context_manager import trim_messages_to_budget
from api import _runtime
from api.dependencies import (
    _build_initial_state,
    _build_stream_config,
    _init_graph,
    _sanitize_input,
    _validate_user,
)
from api.schemas import (
    CancelRequest,
    EditMessageRequest,
    RegenerateRequest,
    UserChatQuery,
)
from api.streaming import _stream_graph
from core.rbac import resolve_rank_strict
from infrastructure.azure.sql.client import SQLChatClient
from infrastructure.cancel_signals.backend import set_cancel

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat")
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
        checkpoint = await _runtime.graph.checkpointer.aget(config)
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
        current_state["chat_session_id"] = chat_session_id   # always keep in sync
        current_state["function"] = query.function
        current_state["sub_function"] = query.sub_function
        current_state["source_url"] = query.source_url
        current_state["start_date"] = query.start_date
        current_state["end_date"] = query.end_date
        current_state["is_free_form"] = query.is_free_form
        current_state["input_type"] = query.input_type.value
        current_state["content_type"] = query.content_type or "qa_pair"

        # If the previous turn failed to find an answer (error_info set or
        # AI responded with "select the specific function"), clear the stale
        # auto-selected function so the user can pick a new one without conflict.
        # However, if the user explicitly selected a DIFFERENT chip for this turn,
        # respect that selection (don't clear it).
        prev_error = current_state.get("error_info")
        prev_ai = current_state.get("ai_content") or ""
        prev_asked_for_function = "select the specific function" in prev_ai
        if prev_error or prev_asked_for_function:
            prev_function = current_state.get("functions_found") or []
            # If the user's chip matches what was previously auto-selected,
            # it's the frontend echoing back — clear it.
            # If the chip is different, the user actively chose — keep it.
            user_chip_is_new = (
                query.function
                and query.function != prev_function
                and set(query.function) != set(prev_function)
            )
            if not user_chip_is_new:
                current_state["function"] = []
            current_state["functions_found"] = []
        # Reset per-turn transient fields (preserve citation_map for multi-turn)
        current_state["events"] = []
        current_state["error_info"] = None
        current_state["ai_content"] = None
        current_state["prompt_used"] = None
        current_state["response"] = None
        current_state["suggestive_actions"] = None
        current_state["conversation_title"] = None
        current_state["requires_function_selection"] = False
        current_state["function_required_reason"] = None
        current_state["function_hint"] = None
        current_state["plan_type"] = None
        current_state["sub_queries"] = None
        current_state["parallel_results"] = None
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


@router.post("/chat/cancel")
async def cancel_chat(body: CancelRequest):
    """Signal an in-flight generation to stop.

    The stream generator checks the cancel-signal backend before each yield
    and emits a final event with cancelled=True when the signal fires.
    """
    _validate_user(body.user_id)
    thread_id = f"{body.user_id}_{body.chat_session_id}"
    set_cancel(thread_id)
    return {"status": "cancel_requested"}


@router.post("/chat/regenerate")
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
        checkpoint = await _runtime.graph.checkpointer.aget(config)
        if checkpoint:
            current_state = checkpoint.get("channel_values", {})
    except Exception:
        pass

    if current_state and current_state.get("messages"):
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
        current_state["plan_type"] = None
        current_state["sub_queries"] = None
        current_state["parallel_results"] = None
        state = current_state
    else:
        raise HTTPException(status_code=404, detail="No conversation state found")

    return StreamingResponse(
        _stream_graph(state, config, thread_id),
        media_type="text/event-stream",
    )


@router.post("/chat/edit")
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

    # Validate rank early — reject before any graph work
    try:
        edit_rank_info = resolve_rank_strict(body.rank_code, body.rank_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await _init_graph()

    thread_id, config = _build_stream_config(body.user_id, body.chat_session_id)

    # Load current checkpoint
    current_state = None
    try:
        checkpoint = await _runtime.graph.checkpointer.aget(config)
        if checkpoint:
            current_state = checkpoint.get("channel_values", {})
    except Exception as e:
        logger.error("edit: failed to load checkpoint: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to load conversation state")

    def _build_fresh_state_from_edit() -> dict:
        """Treat edit payload as a fresh prompt when no checkpoint history exists."""
        return {
            "messages": [HumanMessage(content=new_input)],
            "input_type": "ask",
            "user_input": new_input,
            "is_free_form": body.is_free_form,
            "user_id": body.user_id,
            "chat_id": None,
            "chat_session_id": body.chat_session_id,
            "message_id": None,
            "function": body.function,
            "sub_function": body.sub_function,
            "source_url": body.source_url,
            "start_date": body.start_date,
            "end_date": body.end_date,
            "preferred_language": body.preferred_language,
            "content_type": body.content_type or "qa_pair",
            # Rank context (mandatory)
            "rank_code": body.rank_code,
            "rank_name": body.rank_name,
            "rank_info": edit_rank_info,
            # Ensure transient fields are reset just like a normal graph entry.
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
            "requires_function_selection": False,
            "function_required_reason": None,
            "function_hint": None,
            "plan_type": None,
            "sub_queries": None,
            "parallel_results": None,
        }
    if not current_state or not current_state.get("messages"):
        logger.warning(
            "edit: no checkpoint messages for thread_id=%s; treating edit as new turn",
            thread_id,
        )
        return StreamingResponse(
            _stream_graph(_build_fresh_state_from_edit(), config, thread_id),
            media_type="text/event-stream",
        )

    messages = current_state["messages"]

    # Find the user messages to determine which one to edit
    user_msg_positions = [
        i for i, m in enumerate(messages) if isinstance(m, HumanMessage)
    ]

    if not user_msg_positions:
        logger.warning(
            "edit: checkpoint has no user messages for thread_id=%s; treating edit as new turn",
            thread_id,
        )
        return StreamingResponse(
            _stream_graph(_build_fresh_state_from_edit(), config, thread_id),
            media_type="text/event-stream",
        )

    if body.message_index < 0 or body.message_index >= len(user_msg_positions):
        raise HTTPException(
            status_code=400,
            detail=f"message_index {body.message_index} out of range "
                   f"(conversation has {len(user_msg_positions)} user messages)",
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
        "content_type": body.content_type or "qa_pair",
        "input_type": "ask",
        # Rank context (mandatory)
        "rank_code": body.rank_code,
        "rank_name": body.rank_name,
        "rank_info": edit_rank_info,
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
        "requires_function_selection": False,
        "function_required_reason": None,
        "function_hint": None,
        "plan_type": None,
        "sub_queries": None,
        "parallel_results": None,
    }

    return StreamingResponse(
        _stream_graph(state, config, thread_id),
        media_type="text/event-stream",
    )
