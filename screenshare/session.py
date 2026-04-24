"""Per-connection screenshare session state.

One :class:`ScreenShareSession` exists per ``sessionId`` query parameter
exchanged between the frontend and the two screenshare WebSocket routes
(signaling + control). It owns the outbound event queue consumed by the
control WS and the reference to the Realtime client.

The session is intentionally cheap to create; it holds no database
resources. LangGraph persistence (checkpointer + long-term store + SQL
history) is reached through the compiled graph during transcript bridging
— see :mod:`screenshare.chat_bridge`.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from screenshare.realtime_client import RealtimeClient

logger = logging.getLogger(__name__)


@dataclass
class ScreenShareSession:
    id: str
    user_id: str
    chat_session_id: str
    # Routing / RAG filter context carried over from the UI (same shape
    # the REST /chat endpoint accepts).
    function: list[str] = field(default_factory=list)
    sub_function: list[str] = field(default_factory=list)
    source_url: list[str] = field(default_factory=list)
    start_date: str = ""
    end_date: str = ""
    is_free_form: bool = True
    preferred_language: Optional[str] = None

    # Runtime
    pc_id: Optional[str] = None
    events: asyncio.Queue = field(default_factory=asyncio.Queue)
    latest_frame_jpeg: Optional[bytes] = None
    latest_frame_hash: Optional[int] = None
    realtime: Optional["RealtimeClient"] = None

    # Guards against firing the LangGraph bridge more than once per
    # finalised utterance (Realtime can emit the completion event twice
    # on race conditions).
    _bridge_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _is_bridging: bool = False

    async def emit(self, **event: Any) -> None:
        """Push an event dict onto the outbound queue."""
        await self.events.put(event)


_sessions: dict[str, ScreenShareSession] = {}


def get_or_create(
    session_id: Optional[str],
    *,
    user_id: str,
    chat_session_id: str,
    function: Optional[list[str]] = None,
    sub_function: Optional[list[str]] = None,
    source_url: Optional[list[str]] = None,
    start_date: str = "",
    end_date: str = "",
    is_free_form: bool = True,
    preferred_language: Optional[str] = None,
) -> ScreenShareSession:
    """Return the existing session for ``session_id`` or create a new one."""
    sid = session_id or uuid.uuid4().hex[:10]
    sess = _sessions.get(sid)
    if sess is None:
        sess = ScreenShareSession(
            id=sid,
            user_id=user_id,
            chat_session_id=chat_session_id,
            function=function or [],
            sub_function=sub_function or [],
            source_url=source_url or [],
            start_date=start_date,
            end_date=end_date,
            is_free_form=is_free_form,
            preferred_language=preferred_language,
        )
        _sessions[sid] = sess
        logger.info("screenshare: created session %s for user=%s", sid, user_id)
    return sess


def get(session_id: str) -> Optional[ScreenShareSession]:
    return _sessions.get(session_id)


def drop(session_id: str) -> None:
    _sessions.pop(session_id, None)
