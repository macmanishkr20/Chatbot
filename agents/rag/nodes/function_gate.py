"""
Function-gate node — lightweight, rule-based routing with NO LLM call.

Routing principles (checked in order):
  1. User selected a chip → trust it (hard filter).
  2. Query explicitly contains a function code/chip name (e.g. "TME",
     "Risk Management") → trust it (hard filter). Closed-vocabulary,
     word-boundary match → effectively zero false-positive risk.
  3. Query contains a KNOWN TERM — an unambiguous proper noun that maps
     1:1 to a function (e.g. "PCIP" → Risk, "Concur" → TME). These are
     named systems/processes/tools, NOT generic keywords. Used as hard
     filter because a user mentioning "PCIP" can only mean Risk.
  4. Otherwise → NO filter. Let search_node's score-based routing decide
     based on reranker scores across all functions. Generic keyword matches
     are surfaced as a soft hint only and never injected as a filter,
     because a wrong keyword guess would hide the correct answer entirely
     (e.g. "nda" inside "mandatory" once routed an ABC/PACE question to GCO).
"""
from __future__ import annotations

import logging
import re

from agents.rag.state import RAGState
from agents.rag.prompts.functions import CHIP_TO_SEARCH

logger = logging.getLogger(__name__)


# ── KNOWN TERMS — unambiguous proper nouns (HARD FILTER) ──
# Named systems, tools, processes, or acronyms that map 1:1 to exactly one
# function. These are safe to hard-filter because a user mentioning them
# can only mean that specific function. Word-boundary regex prevents
# substring false-positives.
_KNOWN_TERMS: dict[str, str] = {
    # Risk — named tools/processes under Independence
    "pcip": "Risk",
    "pace submission": "Risk",
    "pace form": "Risk",
    "pace assessment": "Risk",
    "bridge assessment": "Risk",
    "abc assessment": "Risk",
    "abc tool": "Risk",
    "abc qrc": "Risk",
    # C&I — named system
    "gcsp": "C&I",
    # SCS — named tool
    "smart intake": "SCS",
    # TME — named systems
    "concur": "TME",
    "dnata": "TME",
    # Talent — named system
    "successfactors": "Talent",
    "paternity": "Talent",
    "maternity": "Talent",
    "parental": "Talent",
    "family leave": "Talent",
    "learning badge": "Talent",
    "Leave policy": "Talent",
    "Leave": "Talent",
}


# ── Soft keyword → function map (HINTS ONLY — never used as a filter) ──
# Generic terms that often relate to a function but CAN appear in other
# contexts. Misclassifications here are harmless because they only suggest
# a chip — they never narrow the search.
_KEYWORD_TO_FUNCTION: dict[str, str] = {
    # AWS
    "purchase requisition": "AWS",
    "shopping cart": "AWS",
    "facilities management": "AWS",
    "meeting room booking": "AWS",
    "office equipment": "AWS",
    "access card": "AWS",
    # BMC
    "score approval": "BMC",
    "social media": "BMC",
    "brand identity": "BMC",
    "event branding": "BMC",
    # C&I
    "rfp": "C&I",
    "proposal": "C&I",
    "credentials": "C&I",
    "pursuit": "C&I",
    # Finance
    "billing": "Finance",
    "invoice": "Finance",
    "engagement economics": "Finance",
    "etc budget": "Finance",
    "credit note": "Finance",
    # GCO
    "non-disclosure agreement": "GCO",
    "contract template": "GCO",
    "data protection": "GCO",
    "professional indemnity": "GCO",
    # Risk
    "independence": "Risk",
    "conflicts of interest": "Risk",
    # SCS
    "vendor onboarding": "SCS",
    "supplier sourcing": "SCS",
    "procurement": "SCS",
    "subcontractor": "SCS",
    # TME
    "travel booking": "TME",
    "business travel": "TME",
    # Talent
    "immigration": "Talent",
    "visa": "Talent",
    "leave policy": "Talent",
    "learning badge": "Talent",
}

# Function codes/labels that can appear literally in user input.
# Closed vocabulary — used as a HARD signal (filter) when matched with
# word boundaries. Safe because a user typing "TME" or "Risk Management"
# in their question is an unambiguous intent signal.
_FUNCTION_CODES: dict[str, str] = {code.lower(): code for code in CHIP_TO_SEARCH.values()}
# Also match chip labels (e.g. "Risk Management" → "Risk")
for chip_label, search_val in CHIP_TO_SEARCH.items():
    _FUNCTION_CODES[chip_label.lower()] = search_val


_HINT_MESSAGE = (
    "Tip: Selecting a MENA function will help me give you a more accurate "
    "and focused answer."
)


def _detect_explicit_function(query: str) -> str | None:
    """HARD signal: query literally contains a function code or chip name.

    Word-boundary match on a closed 9-item vocabulary. Returns the function
    code only if exactly one is mentioned; ambiguous queries fall through
    to score-based routing in search_node.
    """
    query_lower = query.lower()
    detected: set[str] = set()
    for code_lower, code in _FUNCTION_CODES.items():
        if re.search(rf"\b{re.escape(code_lower)}\b", query_lower):
            detected.add(code)
    return detected.pop() if len(detected) == 1 else None


def _detect_known_term(query: str) -> str | None:
    """HARD signal: query contains a known proper noun (system/tool/process).

    These are unambiguous named entities that map 1:1 to a function.
    Word-boundary match prevents substring false-positives.
    Returns the function code only if all matched terms agree on the same
    function; conflicting terms fall through to search_node.
    """
    query_lower = query.lower()
    detected: set[str] = set()
    for term, fn_code in _KNOWN_TERMS.items():
        if re.search(rf"\b{re.escape(term)}\b", query_lower):
            detected.add(fn_code)
    return detected.pop() if len(detected) == 1 else None


def _suggest_function_from_keywords(query: str) -> str | None:
    """SOFT signal: best-guess function from keyword phrases.

    Used only to surface a UX hint. NEVER injected as a filter — a wrong
    guess here would hide the correct answer entirely.
    """
    query_lower = query.lower()
    detected: set[str] = set()
    for keyword, fn_code in _KEYWORD_TO_FUNCTION.items():
        if re.search(rf"\b{re.escape(keyword)}\b", query_lower):
            detected.add(fn_code)
    return detected.pop() if len(detected) == 1 else None


async def function_gate_node(state: RAGState) -> dict:
    """Lightweight function gate — no LLM call.

    1. User selected a chip → trust it.
    2. Query contains explicit function code/name → trust it.
    3. Query contains a known proper noun (PCIP, Concur, etc.) → trust it.
    4. Otherwise → no filter; search_node routes by reranker scores.
    """
    user_input = (state.get("user_input") or "").strip()
    if not user_input:
        return {"requires_function_selection": False}

    selected = state.get("function") or []
    selected_code = selected[0] if selected else None

    # ── (1) User already selected a chip → trust it ──
    if selected_code:
        logger.info("function_gate: trusting user chip selection: %s", selected_code)
        return {"requires_function_selection": False}

    # ── (2) Explicit function code/name typed in the query → hard filter ──
    explicit = _detect_explicit_function(user_input)
    if explicit:
        search_val = CHIP_TO_SEARCH.get(explicit, explicit)
        logger.info("function_gate: explicit function code in query: %s", search_val)
        return {
            "function": [search_val],
            "functions_found": [search_val],
            "requires_function_selection": False,
        }

    # ── (3) Known proper noun in query → hard filter ──
    known = _detect_known_term(user_input)
    if known:
        search_val = CHIP_TO_SEARCH.get(known, known)
        logger.info("function_gate: known term in query → hard filter: %s", search_val)
        return {
            "function": [search_val],
            "functions_found": [search_val],
            "requires_function_selection": False,
        }

    # ── (4) No hard signal → proceed without filter, attach soft hint ──
    suggested = _suggest_function_from_keywords(user_input)
    if suggested:
        logger.info(
            "function_gate: keyword suggests %s (soft hint only, not filtering)",
            suggested,
        )

    return {
        "requires_function_selection": False,
        "function_hint": _HINT_MESSAGE,
    }
