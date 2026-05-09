"""Feedback endpoint."""
import logging

from fastapi import APIRouter, HTTPException

from api.schemas import FeedbackRequest
from infrastructure.azure.sql.client import SQLChatClient

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/feedback")
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
