"""Inbound WebRTC audio → 24 kHz PCM → Realtime STT.

aiortc delivers Opus frames at 48 kHz; Realtime requires ``pcm16`` at
24 kHz mono. A PyAV ``AudioResampler`` handles the conversion in-process.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

try:
    import av  # type: ignore
    from aiortc.mediastreams import MediaStreamError
except ImportError:  # pragma: no cover
    av = None  # type: ignore[assignment]

    class MediaStreamError(Exception):  # type: ignore[no-redef]
        pass


if TYPE_CHECKING:  # pragma: no cover
    from aiortc.mediastreams import MediaStreamTrack

    from screenshare.realtime_client import RealtimeClient
    from screenshare.session import ScreenShareSession

logger = logging.getLogger(__name__)


class AudioPipeline:
    """Drain one remote audio track into the Realtime client."""

    def __init__(
        self,
        session: "ScreenShareSession",
        track: "MediaStreamTrack",
        client: "RealtimeClient",
    ) -> None:
        self._session = session
        self._track = track
        self._client = client
        self._task: asyncio.Task | None = None
        if av is None:
            raise RuntimeError(
                "PyAV not installed — add 'av' to requirements.txt to "
                "enable the screenshare feature."
            )
        self._resampler = av.AudioResampler(
            format="s16", layout="mono", rate=24000
        )

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        try:
            while True:
                frame = await self._track.recv()
                resampled_frames = self._resampler.resample(frame)
                # PyAV >=12 returns a list; older versions return a single
                # frame. Normalise to a list.
                if not isinstance(resampled_frames, (list, tuple)):
                    resampled_frames = [resampled_frames]
                for rf in resampled_frames:
                    if rf is None:
                        continue
                    pcm = bytes(rf.planes[0])
                    await self._client.push_audio(pcm)
        except MediaStreamError:
            logger.info("screenshare.audio: remote track ended")
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # pragma: no cover
            logger.exception("screenshare.audio: pipeline crashed: %s", exc)
