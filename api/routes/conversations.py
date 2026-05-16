"""
Conversation history & management endpoints (Claude-parity):

  GET    /conversations/{user_id}                       — list user conversations
  GET    /conversations/{user_id}/{chat_id}/messages    — fetch messages in a conversation
  DELETE /conversations/{user_id}/{chat_id}             — soft-delete conversation
  PATCH  /conversations/{user_id}/{chat_id}/rename      — rename conversation
"""
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException

from api.dependencies import _validate_user
from api.schemas import RenameConversationRequest, TogglePinRequest
from infrastructure.azure.sql.client import SQLChatClient

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/conversations/{user_id}")
async def get_conversations(user_id: str):
    """Return all conversation sessions for a user (left-panel chat history).

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


@router.get("/conversations/{user_id}/{chat_id}/messages")
async def get_conversation_messages(user_id: str, chat_id: int):
    """Return all messages in a specific conversation session.

    Used by the frontend to reload a past conversation.
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


@router.delete("/conversations/{user_id}/{chat_id}")
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


@router.patch("/conversations/{user_id}/{chat_id}/rename")
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


@router.patch("/conversations/{user_id}/{chat_id}/toggle-pin")
async def toggle_pin_conversation(user_id: str, chat_id: int, payload: TogglePinRequest):
    """Toggle the pin status of a conversation (pin/unpin)."""
    _validate_user(user_id)

    try:
        scc = SQLChatClient()
        await scc.connect()
        success = await scc.toggle_pin_conversation(chat_id, user_id, payload.is_pinned)
        if not success:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("toggle_pin_conversation failed for user=%s conversation=%s: %s", user_id, chat_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to toggle pin status")