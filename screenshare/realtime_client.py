"""Thin async client for Azure OpenAI Realtime (STT-only usage).

The upstream reference repo uses Realtime as both STT **and** LLM. For
MenaBot we only want the speech-to-text + VAD capability: the final
transcript is fed into the existing LangGraph RAG pipeline so the answer
respects our documents, citations, and persistence model.

Accordingly, ``session.update`` is sent with::

    "turn_detection": {"type": "server_vad", "create_response": false}
    "modalities": ["text"]

which tells the service to transcribe user audio and emit VAD / transcript
events but **never** to generate an assistant response itself.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import AsyncIterator, Optional
from urllib.parse import urlencode

try:
    from websockets.asyncio.client import ClientConnection, connect
    from websockets.exceptions import ConnectionClosed
except ImportError:  # pragma: no cover
    connect = None  # type: ignore[assignment]
    ClientConnection = None  # type: ignore[assignment]

    class ConnectionClosed(Exception):  # type: ignore[no-redef]
        pass


from screenshare.config import (
    AZURE_OPENAI_REALTIME_API_KEY,
    AZURE_OPENAI_REALTIME_API_VERSION,
    AZURE_OPENAI_REALTIME_DEPLOYMENT,
    AZURE_OPENAI_REALTIME_ENDPOINT,
)

logger = logging.getLogger(__name__)

# STT-focused instructions: we'd rather the service stay quiet even if
# someone mistakenly triggers a response — but with create_response:false
# this is belt-and-braces.
_STT_INSTRUCTIONS = (
    "You are a silent transcription service. Do not produce any audio or "
    "text responses; your only job is to transcribe the user's speech."
)


class RealtimeClient:
    """Async WS client for Azure OpenAI Realtime (STT mode)."""

    def __init__(self) -> None:
        self._ws: Optional[ClientConnection] = None
        self._recv_task: Optional[asyncio.Task] = None
        self._events: asyncio.Queue[Optional[dict]] = asyncio.Queue()
        self._closed = False

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def connect(self) -> None:
        if connect is None:
            raise RuntimeError(
                "websockets package not installed — add 'websockets' to "
                "requirements.txt to enable the screenshare feature."
            )
        if not AZURE_OPENAI_REALTIME_ENDPOINT or not AZURE_OPENAI_REALTIME_API_KEY:
            raise RuntimeError(
                "AZURE_OPENAI_REALTIME_ENDPOINT / _API_KEY not configured"
            )

        host = (
            AZURE_OPENAI_REALTIME_ENDPOINT
            .replace("https://", "")
            .replace("http://", "")
            .rstrip("/")
        )
        qs = urlencode(
            {
                "api-version": AZURE_OPENAI_REALTIME_API_VERSION,
                "deployment": AZURE_OPENAI_REALTIME_DEPLOYMENT,
            }
        )
        url = f"wss://{host}/openai/realtime?{qs}"

        logger.info("screenshare.realtime: connecting to %s", url)
        self._ws = await connect(
            url,
            additional_headers={"api-key": AZURE_OPENAI_REALTIME_API_KEY},
            max_size=16 * 1024 * 1024,
        )

        # Configure: STT only, no assistant response generation.
        await self._send(
            {
                "type": "session.update",
                "session": {
                    "modalities": ["text"],
                    "instructions": _STT_INSTRUCTIONS,
                    "input_audio_format": "pcm16",
                    "input_audio_transcription": {"model": "whisper-1"},
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.8,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 500,
                        "create_response": False,
                    },
                    "input_audio_noise_reduction": {"type": "near_field"},
                },
            }
        )

        self._recv_task = asyncio.create_task(self._recv_loop())

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._recv_task:
            self._recv_task.cancel()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # pragma: no cover
                pass
        await self._events.put(None)  # sentinel

    # ── Producers ─────────────────────────────────────────────────────

    async def push_audio(self, pcm24k: bytes) -> None:
        """Append a 24 kHz / 16-bit / mono PCM chunk to the input buffer."""
        if self._ws is None or self._closed:
            return
        await self._send(
            {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm24k).decode("ascii"),
            }
        )

    # ── Consumer ──────────────────────────────────────────────────────

    async def iter_events(self) -> AsyncIterator[dict]:
        """Yield every Realtime server event (transcripts, VAD, errors)."""
        while True:
            evt = await self._events.get()
            if evt is None:
                return
            yield evt

    # ── Internals ─────────────────────────────────────────────────────

    async def _send(self, payload: dict) -> None:
        assert self._ws is not None
        await self._ws.send(json.dumps(payload))

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    evt = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("realtime: non-JSON frame skipped")
                    continue
                await self._events.put(evt)
        except ConnectionClosed:
            logger.info("realtime: connection closed")
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # pragma: no cover
            logger.exception("realtime: recv loop crashed: %s", exc)
        finally:
            await self._events.put(None)
