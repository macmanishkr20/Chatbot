"""
Role-Based Access Control (RBAC) for MenaBot.

Defines the organisation's rank registry and per-agent access rules.
All data is static (no DB call) and resolved at request time by
api/dependencies._build_initial_state → rank_info added to RAGState.

Usage:
    from core.rbac import resolve_rank, is_rank_allowed

    rank_info = resolve_rank(rank_code)   # Optional[RankInfo]
    allowed   = is_rank_allowed("scorecard_agent", rank_code)  # bool
"""
from __future__ import annotations

from typing import Optional

from core.types import RankInfo


# ── Organisation rank registry ────────────────────────────────────────────────
# rank_hierarchy: 1 = most senior tier, higher number = more junior.
# Note: some rank_codes share the same int value (e.g. 11 → Partner & Principal,
# 56 → Administrative Advanced & Administrative Entry). resolve_rank() returns
# the first match; the caller uses rank_name for display.
RANKS: list[RankInfo] = [
    {"rank_code": 11, "rank_name": "Partner",                    "rank_hierarchy": 1},
    {"rank_code": 11, "rank_name": "Principal",                  "rank_hierarchy": 1},
    {"rank_code": 13, "rank_name": "Executive Manager",          "rank_hierarchy": 2},
    {"rank_code": 21, "rank_name": "Senior Manager",             "rank_hierarchy": 3},
    {"rank_code": 32, "rank_name": "Manager",                    "rank_hierarchy": 4},
    {"rank_code": 42, "rank_name": "Senior",                     "rank_hierarchy": 5},
    {"rank_code": 44, "rank_name": "Staff/Assistant",            "rank_hierarchy": 6},
    {"rank_code": 51, "rank_name": "Intern",                     "rank_hierarchy": 7},
    {"rank_code": 55, "rank_name": "Administrative Lead",        "rank_hierarchy": 9},
    {"rank_code": 56, "rank_name": "Administrative Advanced",    "rank_hierarchy": 9},
    {"rank_code": 57, "rank_name": "Administrative Intermediate","rank_hierarchy": 9},
    {"rank_code": 56, "rank_name": "Administrative Entry",       "rank_hierarchy": 9},
]

# Build a fast lookup: rank_code → first matching RankInfo
_RANK_BY_CODE: dict[int, RankInfo] = {}
for _r in RANKS:
    _RANK_BY_CODE.setdefault(_r["rank_code"], _r)


# ── Per-agent access lists ────────────────────────────────────────────────────
# Value = None  → all ranks permitted (open access).
# Value = list  → only those rank_codes are permitted.
# When a new agent is added to MEMBERS in orchestrator/supervisor.py,
# add its entry here before wiring it in — the gate in _get_next will
# activate automatically.
AGENT_ALLOWED_RANK_CODES: dict[str, list[int] | None] = {
    "rag_graph":       None,          # All ranks — knowledge base is open
    "lms_agent":       None,          # All ranks — every employee owns their leave data
    "expense_agent":   None,          # All ranks — RLS clamps non-admins to own GUI
    "scorecard_agent": None,          # All ranks — RLS clamps non-admins to own GUI
}


# Ranks with cross-GUI / aggregate-across-employees privileges on
# the Expense and Scorecard agents. All other ranks are scoped to their
# own GUI by row-level security in the SQL compiler.
FULL_DATA_ACCESS_RANK_CODES: frozenset[int] = frozenset({11, 13})


def can_query_other_gui(rank_code: Optional[int]) -> bool:
    """Return True when the rank is allowed to read another employee's data.

    Partners (11) / Principals (11) / Executive Managers (13) can run
    aggregate / cross-employee analytics. Everyone else is automatically
    restricted to their own GUI at SQL-compile time.
    """
    if rank_code is None:
        return False
    return rank_code in FULL_DATA_ACCESS_RANK_CODES


# ── Public API ────────────────────────────────────────────────────────────────

def resolve_rank(rank_code: Optional[int]) -> Optional[RankInfo]:
    """Return RankInfo for rank_code, or None when rank_code is unknown/None.

    Example:
        resolve_rank(32)  → {"rank_code": 32, "rank_name": "Manager", "rank_hierarchy": 4}
        resolve_rank(99)  → None   (unknown code)
        resolve_rank(None)→ None   (not provided)
    """
    if rank_code is None:
        return None
    return _RANK_BY_CODE.get(rank_code)


def resolve_rank_strict(rank_code: int, rank_name: str) -> RankInfo:
    """Disambiguate and validate a (rank_code, rank_name) pair from the frontend.

    Resolution order:
      1. Exact (rank_code, rank_name) match — preferred (handles rank_code 11
         which maps to both Partner and Principal).
      2. First rank_code match — accept if name differs but code is valid.
         The supplied rank_name is preserved in the returned dict for display.
      3. Raise ValueError when rank_code is not in the registry.

    Returned RankInfo always uses the frontend-supplied rank_name when the
    (code, name) pair is a valid registry entry, otherwise the canonical
    name for that code.
    """
    # Strategy 1: exact (code, name) match
    for r in RANKS:
        if r["rank_code"] == rank_code and r["rank_name"] == rank_name:
            return r
    # Strategy 2: code match only — known code, unknown name
    canonical = _RANK_BY_CODE.get(rank_code)
    if canonical is not None:
        return canonical
    # Strategy 3: unknown code → caller-facing error
    raise ValueError(
        f"Unknown rank_code={rank_code} (rank_name={rank_name!r}). "
        f"Valid codes: {sorted(_RANK_BY_CODE.keys())}"
    )


def is_rank_allowed(agent_name: str, rank_code: Optional[int]) -> bool:
    """Return True if rank_code is permitted to access agent_name.

    Rules:
      - If allowed list is None → all ranks pass (open access).
      - If rank_code is None and agent has restrictions → deny (fail-safe).
      - Otherwise → membership check against the allowed rank_code list.

    Example:
        is_rank_allowed("rag_graph", 51)        → True  (open)
        is_rank_allowed("scorecard_agent", 32)  → False (Managers excluded)
        is_rank_allowed("scorecard_agent", 11)  → True  (Partners allowed)
        is_rank_allowed("scorecard_agent", None)→ False (no rank = deny)
    """
    allowed = AGENT_ALLOWED_RANK_CODES.get(agent_name)
    if allowed is None:
        return True
    if rank_code is None:
        return False
    return rank_code in allowed


def get_rank_display(rank_info: Optional[RankInfo | dict]) -> str:
    """Return a human-readable display string for a rank, or empty string."""
    if not rank_info:
        return ""
    return rank_info.get("rank_name", "")  # type: ignore[union-attr]
