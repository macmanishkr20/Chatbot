"""Control / event endpoint: ``/ws/screenshare/control``.

The signaling channel is one-shot (offer → answer). Everything that the
frontend needs **during** a session — live captions, speaking-state
indicators, and the assistant's streamed reply (which is rendered as a
chat message just like a typed response) — arrives here.

Event shapes emitted to the client:
  {"type": "hello",      "sessionId": "..."}
  {"type": "transcript", "role": "user", "text": "...", "final": bool}
  {"type": "assistant",  "text": "...", "final": bool, "node": "..."}
  {"type": "speaking",   "state": "start"|"end", "role": "user"|"assistant"}
  {"type": "final",      "chat_id": ..., "message_id": ..., ...}
  {"type": "error",      "message": "..."}

Inbound events accepted from the client:
  {"type": "ping"}
  {"type": "text", "text": "..."}  ← fallback typed input that still
                                    runs through the same LangGraph
                                    bridge as spoken input.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from screenshare.chat_bridge import bridge_transcript_to_graph
from screenshare.config import SCREENSHARE_SESSION_TOKEN
from screenshare.session import get_or_create

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/screenshare/control")
async def control(
    ws: WebSocket,
    token: str = Query(...),
    sessionId: str = Query(...),
    userId: str = Query(...),
    chatSessionId: str = Query(...),
) -> None:
    if token != SCREENSHARE_SESSION_TOKEN:
        await ws.close(code=4401)
        return

    await ws.accept()

    session = get_or_create(
        sessionId,
        user_id=userId,
        chat_session_id=chatSessionId,
    )
    await ws.send_text(
        json.dumps({"type": "hello", "sessionId": session.id})
    )

    # Pump queued events → client.
    async def _pump() -> None:
        try:
            while True:
                evt = await session.events.get()
                await ws.send_text(json.dumps(evt))
        except Exception as exc:
            logger.debug("screenshare.control: pump stopped (%s)", exc)

    pump_task = asyncio.create_task(_pump())

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            mtype = msg.get("type")
            if mtype == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))

            elif mtype in ("text", "speak"):
                text = (msg.get("text") or "").strip()
                if not text:
                    continue
                # Mirror as a user message in the chat window, then run
                # through the exact same LangGraph pipeline as voice.
                await session.emit(
                    type="transcript",
                    role="user",
                    text=text,
                    final=True,
                )
                asyncio.create_task(
                    bridge_transcript_to_graph(session, text, None)
                )

    except WebSocketDisconnect:
        logger.info("screenshare.control: client disconnected %s", session.id)
    finally:
        pump_task.cancel()
