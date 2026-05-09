"""
Function-gate node — lightweight, rule-based routing with NO LLM call.

Follows the Claude/Copilot pattern: trust the user's selection. If no
selection was made, let search_node handle function detection via
score-based routing (multi-function detection from search results).

Routing principles:
  1. User selected a function → trust it, proceed immediately.
  2. No selection → proceed without a function filter. Show a non-blocking
     hint suggesting the user select a function for better results.
  3. Keyword matching for obvious cases (e.g. query explicitly says "TME"
     or "purchase requisition") → auto-select without an LLM call.
"""
from __future__ import annotations

import logging
import re

from langchain_core.messages import AIMessage

from agents.rag.state import RAGState
from agents.rag.prompts.functions import CHIP_TO_SEARCH, SEARCH_TO_CHIP

logger = logging.getLogger(__name__)


# ── Keyword → function mapping for obvious cases ──
# Only map unambiguous keywords that belong to exactly one function.
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
    "gcsp": "C&I",
    # Finance
    "billing": "Finance",
    "invoice": "Finance",
    "engagement economics": "Finance",
    "etc budget": "Finance",
    "credit note": "Finance",
    # GCO
    "nda": "GCO",
    "contract template": "GCO",
    "data protection": "GCO",
    "professional indemnity": "GCO",
    # Risk
    "independence": "Risk",
    "pace submission": "Risk",
    "bridge assessment": "Risk",
    "conflicts of interest": "Risk",
    # SCS
    "vendor onboarding": "SCS",
    "supplier sourcing": "SCS",
    "procurement": "SCS",
    "subcontractor": "SCS",
    "smart intake": "SCS",
    # TME
    "travel booking": "TME",
    "concur": "TME",
    "dnata": "TME",
    "business travel": "TME",
    # Talent
    "immigration": "Talent",
    "visa": "Talent",
    "leave policy": "Talent",
    "successfactors": "Talent",
    "learning badge": "Talent",
}

# Function codes that can appear directly in user input
_FUNCTION_CODES = {code.lower(): code for code in CHIP_TO_SEARCH.values()}
# Also match chip labels (e.g. "Risk Management" → "Risk")
for chip_label, search_val in CHIP_TO_SEARCH.items():
    _FUNCTION_CODES[chip_label.lower()] = search_val


_HINT_MESSAGE = (
    "Tip: Selecting a MENA function will help me give you a more accurate "
    "and focused answer."
)


def _detect_function_from_query(query: str) -> str | None:
    """Detect function from query text using keyword matching.

    Returns the function code if exactly one function is detected,
    None otherwise (ambiguous or no match).
    """
    query_lower = query.lower()
    detected: set[str] = set()

    # Check for explicit function codes/names in the query
    for code_lower, code in _FUNCTION_CODES.items():
        # Word boundary match to avoid partial matches
        if re.search(rf"\b{re.escape(code_lower)}\b", query_lower):
            detected.add(code)

    # Check keyword mappings
    for keyword, fn_code in _KEYWORD_TO_FUNCTION.items():
        if keyword in query_lower:
            detected.add(fn_code)

    # Only auto-select if exactly one function detected
    if len(detected) == 1:
        return detected.pop()

    return None


async def function_gate_node(state: RAGState) -> dict:
    """Lightweight function gate — no LLM call.

    1. User selected a function → trust it, proceed.
    2. No selection → try keyword detection, else proceed without filter.
    """
    user_input = (state.get("user_input") or "").strip()
    if not user_input:
        return {"requires_function_selection": False}

    selected = state.get("function") or []
    selected_code = selected[0] if selected else None

    # ── User already selected a function → trust it ──
    if selected_code:
        logger.info("function_gate: trusting user selection: %s", selected_code)
        return {"requires_function_selection": False}

    # ── No selection → try lightweight keyword detection ──
    detected = _detect_function_from_query(user_input)

    if detected:
        search_val = CHIP_TO_SEARCH.get(detected, detected)
        logger.info("function_gate: auto-detected function from keywords: %s", search_val)
        return {
            "function": [search_val],
            "functions_found": [search_val],
            "requires_function_selection": False,
        }

    # ── No detection → proceed without filter, show hint ──
    logger.info("function_gate: no function detected, proceeding without filter")
    return {
        "requires_function_selection": False,
        "function_hint": _HINT_MESSAGE,
    }
