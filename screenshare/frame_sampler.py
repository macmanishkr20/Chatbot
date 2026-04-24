"""Inbound WebRTC video → dedup-sampled JPEG on the session.

We don't push frames into the LLM (MenaBot's answer comes from Azure AI
Search, not from vision). The latest frame is still captured so future
extensions — e.g. attaching a screenshot to the transcript for audit —
can pick it up from ``session.latest_frame_jpeg``.
"""
from __future__ import annotations

import asyncio
import logging
import time
from io import BytesIO
from typing import TYPE_CHECKING

try:
    import imagehash  # type: ignore
    from PIL import Image  # type: ignore
    from aiortc.mediastreams import MediaStreamError
except ImportError:  # pragma: no cover
    imagehash = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]

    class MediaStreamError(Exception):  # type: ignore[no-redef]
        pass


from screenshare.config import (
    FRAME_DIFF_THRESHOLD,
    FRAME_FPS_MAX,
    FRAME_JPEG_QUALITY,
    FRAME_MAX_SIDE_PX,
)

if TYPE_CHECKING:  # pragma: no cover
    from aiortc.mediastreams import MediaStreamTrack

    from screenshare.session import ScreenShareSession

logger = logging.getLogger(__name__)


class FrameSampler:
    """Throttle + dedup video frames; store the latest JPEG on the session."""

    def __init__(
        self,
        session: "ScreenShareSession",
        track: "MediaStreamTrack",
    ) -> None:
        self._session = session
        self._track = track
        self._task: asyncio.Task | None = None
        self._min_gap = 1.0 / max(FRAME_FPS_MAX, 0.1)
        self._last_ts = 0.0

    def start(self) -> None:
        if Image is None or imagehash is None:
            logger.warning(
                "screenshare.frame: Pillow/imagehash not installed — "
                "frame sampling disabled"
            )
            return
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        try:
            while True:
                frame = await self._track.recv()
                now = time.monotonic()
                if now - self._last_ts < self._min_gap:
                    continue
                self._last_ts = now
                self._process(frame)
        except MediaStreamError:
            logger.info("screenshare.frame: remote track ended")
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # pragma: no cover
            logger.exception("screenshare.frame: sampler crashed: %s", exc)

    def _process(self, frame) -> None:
        img = frame.to_image()  # PIL RGB
        img.thumbnail((FRAME_MAX_SIDE_PX, FRAME_MAX_SIDE_PX), Image.LANCZOS)
        h = int(str(imagehash.average_hash(img, hash_size=16)), 16)

        if self._session.latest_frame_hash is not None:
            diff_bits = bin(h ^ self._session.latest_frame_hash).count("1")
            if diff_bits / 256.0 < FRAME_DIFF_THRESHOLD:
                return  # near-duplicate, skip

        buf = BytesIO()
        img.save(buf, "JPEG", quality=FRAME_JPEG_QUALITY)
        self._session.latest_frame_jpeg = buf.getvalue()
        self._session.latest_frame_hash = h
