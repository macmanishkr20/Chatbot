"""Screen-share + voice assistance backend (feature module).

Adds a WebRTC + Azure OpenAI Realtime pipeline that lets a user share
their screen and speak to MenaBot from the "Ask me anything" bar.

The module is self-contained: user speech → transcript (STT via Realtime)
→ existing LangGraph RAG pipeline (same memory, checkpointer, SQL path as
the REST ``/chat`` endpoint). The assistant's text reply is streamed back
over a control WebSocket and, when TTS is configured, spoken back through
the outbound WebRTC audio track.

Nothing in this package mutates the existing chat logic — it consumes the
compiled graph via :func:`graph.nodes.supervisor.get_graph`.
"""

from screenshare.ws_signaling import router as signaling_router
from screenshare.ws_control import router as control_router

__all__ = ["signaling_router", "control_router"]
