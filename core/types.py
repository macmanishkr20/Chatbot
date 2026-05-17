"""
Shared primitive types used across agents, infrastructure, and API layers.

Kept as plain TypedDicts (not dataclasses / Pydantic models) so they are
JSON-serializable by LangGraph's SQL checkpointer without any custom adapter.
"""
from __future__ import annotations

from typing import TypedDict


class RankInfo(TypedDict):
    """Canonical representation of a user's organisational rank."""
    rank_code: int
    rank_name: str        # e.g. "Manager", "Partner"
    rank_hierarchy: int   # 1 = most senior, 9 = most junior tier
