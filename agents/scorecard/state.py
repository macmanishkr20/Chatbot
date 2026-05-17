"""Scorecard agent re-exports the shared RAGState (no separate state class)."""
from agents.rag.state import RAGState

__all__ = ["RAGState"]
