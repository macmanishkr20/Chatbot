"""
Shared request helpers used by every route: validators, sanitizers, SSE
formatter, state builders, and config wiring.
"""
import json
import re

from fastapi import HTTPException
from langchain_core.messages import HumanMessage

from agents.rag.prompts.functions import SEARCH_TO_CHIP
from api import _runtime
from api.schemas import UserChatQuery
from core.config import MAX_INPUT_LENGTH

# Accept any EY regional subdomain: name@{region}.ey.com (gds, ae, bh, sa, …) or name@ey.com
_EY_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)?ey\.com$")


def validate_domain(user_id: str) -> bool:
    """Validate that the incoming user ID belongs to an EY domain."""
    return bool(_EY_EMAIL_RE.match(user_id.strip().lower()))


def _validate_user(user_id: str) -> None:
    """Common user validation — raises HTTPException on failure."""
    if not user_id:
        raise HTTPException(status_code=400, detail="UserId is not provided")
    if not validate_domain(user_id):
        raise HTTPException(status_code=400, detail="UserId must be an EY email (e.g. @gds.ey.com, @ae.ey.com)")


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


def _to_chip_code(value: str | None) -> str | None:
    """Convert a search-index function value to its frontend chip code.
    E.g. "Risk" → "Risk Management", "Finance" → "Finance".
    Returns as-is if already a chip code or unknown.
    """
    if not value:
        return value
    return SEARCH_TO_CHIP.get(value, value)


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
        "content_type": query.content_type or "qa_pair",
        "requires_function_selection": False,
    }


def _build_stream_config(user_id: str, chat_session_id: str) -> tuple[str, dict]:
    """Build LangGraph config for streaming. Returns (thread_id, config)."""
    thread_id = f"{user_id}_{chat_session_id}"
    config: dict = {"configurable": {"thread_id": thread_id}}
    config["callbacks"] = [_runtime.callback_handler] if _runtime.callback_handler else []
    return thread_id, config


async def _init_graph():
    """Initialise the compiled graph singleton (idempotent)."""
    if _runtime.graph is None:
        from orchestrator.supervisor import get_graph
        _runtime.graph = await get_graph()
    return _runtime.graph
