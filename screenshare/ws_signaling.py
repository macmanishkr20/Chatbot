"""WebRTC signaling endpoint: ``/ws/screenshare/signaling``.

Single frame per session (offer → answer). Audio + video flow over the
WebRTC data path; transcripts + assistant events flow over the separate
``/ws/screenshare/control`` channel so the browser can render them in
the chat window as normal messages.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from screenshare.config import SCREENSHARE_SESSION_TOKEN
from screenshare.rtc_peer import create_peer
from screenshare.session import get_or_create

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/screenshare/signaling")
async def signaling(
    ws: WebSocket,
    token: str = Query(...),
    sessionId: str | None = Query(None),
    userId: str = Query(...),
    chatSessionId: str = Query(...),
    # Optional RAG filter context (same semantics as /chat).
    function: str = Query(""),
    subFunction: str = Query(""),
    sourceUrl: str = Query(""),
    startDate: str = Query(""),
    endDate: str = Query(""),
    isFreeForm: bool = Query(True),
    preferredLanguage: str | None = Query(None),
) -> None:
    if token != SCREENSHARE_SESSION_TOKEN:
        await ws.close(code=4401)
        return

    await ws.accept()

    def _split(csv: str) -> list[str]:
        return [x.strip() for x in csv.split(",") if x.strip()]

    session = get_or_create(
        sessionId,
        user_id=userId,
        chat_session_id=chatSessionId,
        function=_split(function),
        sub_function=_split(subFunction),
        source_url=_split(sourceUrl),
        start_date=startDate,
        end_date=endDate,
        is_free_form=isFreeForm,
        preferred_language=preferredLanguage,
    )
    await ws.send_text(json.dumps({"type": "ready", "sessionId": session.id}))

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(
                    json.dumps({"type": "error", "message": "invalid JSON"})
                )
                continue

            mtype = msg.get("type")
            if mtype == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))

            elif mtype == "offer":
                sdp = msg.get("sdp") or ""
                sdp_type = msg.get("sdpType") or "offer"
                try:
                    pc_id, answer = await create_peer(session, sdp, sdp_type)
                except Exception as exc:
                    logger.exception(
                        "screenshare.signaling: create_peer failed: %s", exc
                    )
                    await ws.send_text(
                        json.dumps({"type": "error", "message": str(exc)})
                    )
                    continue
                await ws.send_text(
                    json.dumps(
                        {
                            "type": "answer",
                            "pcId": pc_id,
                            "sdp": answer.sdp,
                            "sdpType": answer.type,
                        }
                    )
                )

            else:
                await ws.send_text(
                    json.dumps(
                        {"type": "error", "message": f"unknown type {mtype!r}"}
                    )
                )

    except WebSocketDisconnect:
        logger.info("screenshare.signaling: client disconnected %s", session.id)
