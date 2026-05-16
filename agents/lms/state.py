"""
LMS state — re-export shared :class:`RAGState`.

We deliberately do NOT define a separate state class. The supervisor
dispatches via a single RAGState; sub-graphs that maintain their own state
would force serialise/deserialise on every hop and complicate the
checkpointer.

LMS-specific fields live on RAGState as optional members (see
``agents/rag/state.py``). They are namespaced (``lms_result``,
``lms_sub_intent``) so other agents can coexist.
"""
from agents.rag.state import RAGState

__all__ = ["RAGState"]
