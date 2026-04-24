"""aiortc peer orchestration for a screenshare session.

Owns the :class:`RTCPeerConnection`, wires:
  • inbound mic audio → :class:`AudioPipeline` → Realtime STT
  • inbound screen video → :class:`FrameSampler` → ``session.latest_frame_jpeg``
  • outbound TTS audio ← :class:`TTSAudioTrack`
  • Realtime events → control-WS events on ``session.events`` and, on
    final user transcript, invokes the LangGraph bridge.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Dict

try:
    from aiortc import RTCPeerConnection, RTCSessionDescription
except ImportError:  # pragma: no cover
    RTCPeerConnection = None  # type: ignore[assignment]
    RTCSessionDescription = None  # type: ignore[assignment]

from screenshare.audio_pipeline import AudioPipeline
from screenshare.chat_bridge import bridge_transcript_to_graph
from screenshare.frame_sampler import FrameSampler
from screenshare.realtime_client import RealtimeClient
from screenshare.session import ScreenShareSession
from screenshare.tts_track import TTSAudioTrack

logger = logging.getLogger(__name__)

_peers: Dict[str, RTCPeerConnection] = {}


async def create_peer(
    session: ScreenShareSession,
    offer_sdp: str,
    offer_type: str,
) -> tuple[str, "RTCSessionDescription"]:
    """Handle a WebRTC offer; return ``(pc_id, answer)``."""
    if RTCPeerConnection is None:
        raise RuntimeError(
            "aiortc not installed — add 'aiortc' to requirements.txt"
        )

    # Tear down a prior peer for this session (reconnect case).
    if session.pc_id and session.pc_id in _peers:
        await _drop(session.pc_id)

    pc = RTCPeerConnection()
    pc_id = uuid.uuid4().hex[:8]
    _peers[pc_id] = pc
    session.pc_id = pc_id

    # Outbound TTS track (always added so the answer SDP advertises it).
    tts_track = TTSAudioTrack()
    pc.addTrack(tts_track)

    # Realtime STT client.
    rt = RealtimeClient()
    await rt.connect()
    session.realtime = rt

    # Pump Realtime → UI events + graph bridge.
    asyncio.create_task(_events_loop(session, rt, tts_track))

    @pc.on("track")
    def on_track(track):  # noqa: D401
        if track.kind == "audio":
            logger.info(
                "screenshare: audio track received (session=%s)", session.id
            )
            ap = AudioPipeline(session, track, rt)
            ap.start()
        elif track.kind == "video":
            logger.info(
                "screenshare: video track received (session=%s)", session.id
            )
            fs = FrameSampler(session, track)
            fs.start()

        @track.on("ended")
        async def on_ended():  # noqa: D401
            logger.info(
                "screenshare: %s track ended (session=%s)", track.kind, session.id
            )

    @pc.on("connectionstatechange")
    async def on_state_change():  # noqa: D401
        logger.info(
            "screenshare: pc=%s state=%s", pc_id, pc.connectionState
        )
        if pc.connectionState in ("failed", "closed"):
            await _drop(pc_id)

    await pc.setRemoteDescription(
        RTCSessionDescription(sdp=offer_sdp, type=offer_type)
    )
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return pc_id, pc.localDescription


async def _events_loop(
    session: ScreenShareSession,
    rt: RealtimeClient,
    tts_track: TTSAudioTrack,
) -> None:
    """Translate Realtime events into control-WS events and drive the bridge."""
    partial_buf: list[str] = []

    async for evt in rt.iter_events():
        etype = evt.get("type", "")

        if etype == "input_audio_buffer.speech_started":
            await session.emit(type="speaking", state="start", role="user")
            # If a previous assistant reply was being spoken, cancel it
            # so the user can barge in cleanly.
            await tts_track.clear()

        elif etype == "input_audio_buffer.speech_stopped":
            await session.emit(type="speaking", state="end", role="user")

        elif etype == "conversation.item.input_audio_transcription.delta":
            # Partial user transcript (accumulate but also forward so the
            # UI can show live captions in the chat window).
            delta = evt.get("delta", "")
            if delta:
                partial_buf.append(delta)
                await session.emit(
                    type="transcript",
                    role="user",
                    text="".join(partial_buf),
                    final=False,
                )

        elif etype == "conversation.item.input_audio_transcription.completed":
            final_text = (evt.get("transcript") or "").strip()
            partial_buf.clear()
            if not final_text:
                continue

            # Emit the finalised user transcript so the frontend can drop
            # it into the chat window as the user message.
            await session.emit(
                type="transcript",
                role="user",
                text=final_text,
                final=True,
            )

            # Bridge to the existing LangGraph pipeline. Fire-and-forget
            # so the Realtime WS stays responsive while the graph runs.
            asyncio.create_task(
                bridge_transcript_to_graph(session, final_text, tts_track)
            )

        elif etype == "error":
            msg = (evt.get("error") or {}).get("message", "realtime error")
            logger.error("screenshare.realtime: %s", msg)
            await session.emit(type="error", message=msg)


async def _drop(pc_id: str) -> None:
    pc = _peers.pop(pc_id, None)
    if pc is None:
        return
    try:
        await pc.close()
    except Exception:  # pragma: no cover
        pass


async def close_all_peers() -> None:
    for pc_id in list(_peers.keys()):
        await _drop(pc_id)
