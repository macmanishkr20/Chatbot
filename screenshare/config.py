"""Environment-backed settings for the screenshare feature.

Kept deliberately separate from the main ``config.py`` so that the rest of
the chatbot runs unchanged when these env vars are absent (feature simply
refuses to start a session and logs a clear error).
"""
from __future__ import annotations

import os


# ── Azure OpenAI Realtime (STT + server-side VAD) ──
# Often deployed in a different region than the chat resource, so we keep
# separate endpoint/key pairs with a fallback to the shared ones used by
# the rest of the app.
from config import AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY  # fallback

AZURE_OPENAI_REALTIME_ENDPOINT = os.getenv(
    "AZURE_OPENAI_REALTIME_ENDPOINT", AZURE_OPENAI_ENDPOINT
)
AZURE_OPENAI_REALTIME_API_KEY = os.getenv(
    "AZURE_OPENAI_REALTIME_API_KEY", AZURE_OPENAI_KEY
)
AZURE_OPENAI_REALTIME_DEPLOYMENT = os.getenv(
    "AZURE_OPENAI_REALTIME_DEPLOYMENT", "gpt-4o-realtime-preview"
)
AZURE_OPENAI_REALTIME_API_VERSION = os.getenv(
    "AZURE_OPENAI_REALTIME_API_VERSION", "2024-10-01-preview"
)

# ── Azure Speech (TTS for speaking the assistant reply) ──
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY", "")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "eastus")
AZURE_SPEECH_VOICE = os.getenv(
    "AZURE_SPEECH_VOICE", "en-US-AvaMultilingualNeural"
)

# ── Session token (shared secret on WS query string) ──
SCREENSHARE_SESSION_TOKEN = os.getenv(
    "SCREENSHARE_SESSION_TOKEN", "local-dev-token"
)

# ── Frame sampling knobs ──
FRAME_FPS_MAX = float(os.getenv("SCREENSHARE_FRAME_FPS_MAX", "1.0"))
FRAME_DIFF_THRESHOLD = float(
    os.getenv("SCREENSHARE_FRAME_DIFF_THRESHOLD", "0.05")
)
FRAME_MAX_SIDE_PX = int(os.getenv("SCREENSHARE_FRAME_MAX_SIDE_PX", "1280"))
FRAME_JPEG_QUALITY = int(os.getenv("SCREENSHARE_FRAME_JPEG_QUALITY", "88"))


def realtime_is_configured() -> bool:
    """Return True if the Azure OpenAI Realtime endpoint + key are set."""
    return bool(AZURE_OPENAI_REALTIME_ENDPOINT and AZURE_OPENAI_REALTIME_API_KEY)


def tts_is_configured() -> bool:
    """Return True if Azure Speech TTS credentials are set."""
    return bool(AZURE_SPEECH_KEY and AZURE_SPEECH_REGION)
