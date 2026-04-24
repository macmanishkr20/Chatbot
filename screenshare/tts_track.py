"""Outbound WebRTC audio track paced at 20 ms / 24 kHz.

Chunks of raw PCM16 fed via :meth:`push` are chopped into 480-sample
frames and emitted on a 20 ms clock; aiortc's Opus encoder upsamples
them to 48 kHz internally.
"""
from __future__ import annotations

import asyncio
import logging
from fractions import Fraction
from typing import Callable, AsyncIterator

try:
    import av  # type: ignore
    from aiortc.mediastreams import MediaStreamTrack
except ImportError:  # pragma: no cover
    av = None  # type: ignore[assignment]
    MediaStreamTrack = object  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 24000
_SAMPLES_PER_FRAME = 480  # 20 ms
_BYTES_PER_FRAME = _SAMPLES_PER_FRAME * 2  # s16 mono


class TTSAudioTrack(MediaStreamTrack):  # type: ignore[misc]
    """Drip-feeds PCM buffer to aiortc; emits silence when empty."""

    kind = "audio"

    def __init__(self) -> None:
        super().__init__()
        self._buf = bytearray()
        self._cond = asyncio.Condition()
        self._pts = 0
        self._time_base = Fraction(1, _SAMPLE_RATE)
        if av is None:  # pragma: no cover
            raise RuntimeError("PyAV not installed")
        # Pre-build a silent frame payload for the idle path.
        self._silence = bytes(_BYTES_PER_FRAME)

    async def push(self, pcm: bytes) -> None:
        async with self._cond:
            self._buf.extend(pcm)
            self._cond.notify_all()

    async def clear(self) -> None:
        async with self._cond:
            self._buf.clear()
            self._cond.notify_all()

    async def stream_from(
        self, iterator_factory: Callable[[], AsyncIterator[bytes]]
    ) -> None:
        async for chunk in iterator_factory():
            await self.push(chunk)

    async def recv(self):  # type: ignore[override]
        # Paced at 20 ms of media time.
        await asyncio.sleep(0.02)

        async with self._cond:
            if len(self._buf) >= _BYTES_PER_FRAME:
                payload = bytes(self._buf[:_BYTES_PER_FRAME])
                del self._buf[:_BYTES_PER_FRAME]
            else:
                payload = self._silence

        frame = av.AudioFrame(
            format="s16", layout="mono", samples=_SAMPLES_PER_FRAME
        )
        frame.planes[0].update(payload)
        frame.sample_rate = _SAMPLE_RATE
        frame.pts = self._pts
        frame.time_base = self._time_base
        self._pts += _SAMPLES_PER_FRAME
        return frame
