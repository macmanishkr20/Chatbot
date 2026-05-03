"""
Per-agent state for the LMS agent.

The supervisor stamps these fields once via ``enrich_context`` so every
tool call has consistent identity / locale / temporal context — the LLM
should never have to ask the user "where do you work?" or "what's the
date?".
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from graph.state import RAGState


class LMSAgentState(RAGState, total=False):
    # ── Identity / locale ──
    employee_id: str
    employee_name: Optional[str]
    office_location: Optional[str]
    country: Optional[str]
    timezone: Optional[str]
    manager_id: Optional[str]

    # ── Temporal context ──
    current_date_iso: Optional[str]
    current_date_readable: Optional[str]
    fiscal_year: Optional[str]

    # ── HITL confirmation flow ──
    pending_write_action: Optional[dict]
    user_confirmed_write: bool

    # ── Tool trace (for the synthesize step + UI thinking panel) ──
    tool_trace: list[dict[str, Any]]
