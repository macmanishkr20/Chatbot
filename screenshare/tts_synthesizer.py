"""Azure Speech → 24 kHz / 16-bit / mono PCM chunks.

Used to speak the assistant reply back to the user through the outbound
WebRTC audio track (see :mod:`screenshare.tts_track`). Runs the blocking
Azure Speech SDK call inside a default-executor thread.
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

try:
    import azure.cognitiveservices.speech as speechsdk  # type: ignore
except ImportError:  # pragma: no cover
    speechsdk = None  # type: ignore[assignment]

from screenshare.config import (
    AZURE_SPEECH_KEY,
    AZURE_SPEECH_REGION,
    AZURE_SPEECH_VOICE,
)

logger = logging.getLogger(__name__)

# 20 ms frames @ 24 kHz / s16 mono → 960 bytes per frame.
_CHUNK_BYTES = 24000 * 2 // 50


async def synthesize(text: str) -> AsyncIterator[bytes]:
    """Yield raw PCM16 24 kHz chunks for ``text`` (silent no-op if unconfigured)."""
    if not text.strip():
        return
    if speechsdk is None or not AZURE_SPEECH_KEY or not AZURE_SPEECH_REGION:
        logger.debug(
            "screenshare.tts: Azure Speech not configured; skipping TTS"
        )
        return

    loop = asyncio.get_event_loop()

    def _run_sync() -> bytes:
        cfg = speechsdk.SpeechConfig(
            subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION
        )
        cfg.speech_synthesis_voice_name = AZURE_SPEECH_VOICE
        cfg.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm
        )
        synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
        result = synth.speak_text_async(text).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            logger.warning(
                "screenshare.tts: synthesis failed reason=%s", result.reason
            )
            return b""
        return bytes(result.audio_data)

    pcm = await loop.run_in_executor(None, _run_sync)

    for i in range(0, len(pcm), _CHUNK_BYTES):
        yield pcm[i : i + _CHUNK_BYTES]
