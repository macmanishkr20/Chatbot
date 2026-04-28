"""
Function-gate node — runs at the top of the RAG sub-graph and decides
how to use the user's MENA function selection together with what the
query itself says.

Routing principles (UI selection is authoritative):

1. The user's UI selection is trusted. The LLM never overrides a
   selection — it only reports what the query mentions / is plausibly
   about.
2. The query can also carry a function (e.g. "AWS purchase requisitions"
   with no chip selected). In that case the gate auto-selects it and
   writes it back to state["function"] so the rest of the graph treats
   it like a UI selection.
3. The only blocking case when the user has already selected a function
   is when the query *explicitly* names a different function — then we
   ask the user to pick one of the two.
4. With no selection: a single explicit mention or a single confident
   candidate is auto-selected; multiple explicit mentions block for
   disambiguation; otherwise the search proceeds without a filter and
   a non-blocking hint is shown suggesting the user select a function.

Greetings / unrelated knowledge questions skip the gate entirely.
"""
from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import AzureChatOpenAI
from pydantic import BaseModel, Field

from config import AZURE_OPENAI_API_VERSION, AZURE_OPENAI_KEY
from graph.state import RAGState
from prompts.function_gate import FUNCTION_GATE_PROMPT
from prompts._functions import CHIP_TO_SEARCH, SEARCH_TO_CHIP
from services.openai_client import get_llm_model

logger = logging.getLogger(__name__)


class FunctionGateVerdict(BaseModel):
    verdict: Literal["match", "ambiguous", "unclassified", "not_applicable"] = Field(
        description="Routing verdict for the query."
    )
    function: str | None = Field(
        default=None, description="Function code when verdict='match'."
    )
    mentioned_functions: list[str] = Field(
        default_factory=list,
        description="Function codes the query explicitly names.",
    )
    candidates: list[str] = Field(
        default_factory=list,
        description="Plausible function codes when nothing is explicitly mentioned.",
    )
    reason: str = Field(default="", description="Short justification.")


_llm: AzureChatOpenAI | None = None


def _get_llm() -> AzureChatOpenAI:
    global _llm
    if _llm is None:
        _llm = AzureChatOpenAI(
            azure_deployment=get_llm_model("function_gate"),
            api_key=AZURE_OPENAI_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
            temperature=0.0,
            max_retries=2,
            streaming=False,
        )
    return _llm


_FIRST_TURN_MESSAGE = (
    "Please select the MENA function this question relates to so I can "
    "give you an accurate answer. Pick one of the highlighted functions "
    "below the chat box."
)

_AMBIGUOUS_MESSAGE_TEMPLATE = (
    "This question could fit more than one MENA function ({candidates}). "
    "Please select the function you mean from the chips below."
)

_CONFLICT_MESSAGE_TEMPLATE = (
    "Your question mentions {mentioned} but you've selected {selected}. "
    "Please pick the single function you want to ask about."
)

_HINT_MESSAGE = (
    "Tip: Selecting a MENA function will help me give you a more accurate "
    "and focused answer."
)

_HINT_AMBIGUOUS_TEMPLATE = (
    "Tip: This question could relate to multiple functions ({candidates}). "
    "Selecting a specific MENA function will help me give you a more "
    "accurate answer."
)


def _norm(code: str | None) -> str:
    return (code or "").strip().lower()


def _eq(a: str | None, b: str | None) -> bool:
    """Compare two function identifiers that may be in different formats
    (chip code vs search value). E.g. _eq("Risk", "Risk Management") → True.
    """
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # Check if one is a chip code and the other is its search value
    search_a = _norm(CHIP_TO_SEARCH.get(a or "", ""))
    search_b = _norm(CHIP_TO_SEARCH.get(b or "", ""))
    chip_a = _norm(SEARCH_TO_CHIP.get(a or "", ""))
    chip_b = _norm(SEARCH_TO_CHIP.get(b or "", ""))
    return na == search_b or na == chip_b or nb == search_a or nb == chip_a


async def function_gate_node(state: RAGState) -> dict:
    """Validate / derive the MENA function selection before search."""
    user_input = (state.get("user_input") or "").strip()
    if not user_input:
        return {"requires_function_selection": False}

    selected = state.get("function") or []
    selected_code = selected[0] if selected else None

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", FUNCTION_GATE_PROMPT),
            (
                "human",
                "User's currently selected function: {selected}\n\n"
                "Query: {query}",
            ),
        ]
    )
    chain = prompt | _get_llm().with_structured_output(FunctionGateVerdict)

    try:
        verdict: FunctionGateVerdict = await chain.ainvoke(
            {"query": user_input, "selected": selected_code or "(none)"}
        )
    except Exception as exc:
        logger.warning("function_gate: classifier failed: %s", exc, exc_info=True)
        # Fail-open if a function was already chosen; otherwise force selection.
        if selected_code:
            return {"requires_function_selection": False}
        return _block_for_selection(_FIRST_TURN_MESSAGE)

    mentioned = [m for m in (verdict.mentioned_functions or []) if m]
    candidates = [c for c in (verdict.candidates or []) if c]
    suggested = (verdict.function or "").strip() or None

    logger.info(
        "function_gate verdict=%s selected=%s suggested=%s mentioned=%s candidates=%s",
        verdict.verdict, selected_code, suggested, mentioned, candidates,
    )

    # Greeting / chit-chat — bypass the gate entirely.
    if verdict.verdict == "not_applicable":
        return {"requires_function_selection": False}

    # Knowledge question unrelated to any MENA function — let downstream
    # nodes handle (search will likely return empty and the supervisor
    # will respond accordingly). Trust the user's selection if any.
    if verdict.verdict == "unclassified":
        return {"requires_function_selection": False}

    # ── Branch A: user has already selected a function ──
    if selected_code:
        # The only blocking case: the query *explicitly* names a different
        # function than the one selected. Ambiguous guesses do NOT block —
        # the user has already chosen.
        conflicting = [m for m in mentioned if not _eq(m, selected_code)]
        if mentioned and conflicting and not any(_eq(m, selected_code) for m in mentioned):
            return _block_for_selection(
                _CONFLICT_MESSAGE_TEMPLATE.format(
                    mentioned=", ".join(conflicting),
                    selected=selected_code,
                ),
                candidates=[selected_code, *conflicting],
            )
        return {"requires_function_selection": False}

    # ── Branch B: no UI selection — derive from query when possible ──

    # Exactly one explicit mention → auto-select.
    if len(mentioned) == 1:
        return _auto_select(mentioned[0])

    # Multiple explicit mentions → still block (genuine conflict in query).
    if len(mentioned) > 1:
        return _block_for_selection(
            _AMBIGUOUS_MESSAGE_TEMPLATE.format(candidates=", ".join(mentioned)),
            candidates=mentioned,
        )

    # No explicit mention — fall back to verdict.
    if verdict.verdict == "match" and suggested:
        return _auto_select(suggested)

    # Ambiguous or undetected — proceed with search (no filter) but hint
    # the user that selecting a function would improve results.
    if verdict.verdict == "ambiguous" and candidates:
        return _hint_and_proceed(
            _HINT_AMBIGUOUS_TEMPLATE.format(candidates=", ".join(candidates)),
            candidates=candidates,
        )

    return _hint_and_proceed(_HINT_MESSAGE)


def _auto_select(code: str) -> dict:
    """Auto-select a function derived from the query and proceed.

    ``code`` is the search-index value output by the LLM (e.g. "Risk", "C&I").
    state["function"] stores the search value for OData filter correctness.
    """
    # Resolve to search value if a chip code was somehow passed
    search_val = CHIP_TO_SEARCH.get(code, code)
    return {
        "function": [search_val],
        "functions_found": [search_val],
        "requires_function_selection": False,
    }


def _block_for_selection(message: str, candidates: list[str] | None = None) -> dict:
    return {
        "messages": [AIMessage(content=message)],
        "ai_content": message,
        "is_free_form": True,
        "requires_function_selection": True,
        "function_required_reason": message,
        "functions_found": candidates or [],
        "response": {"message": message, "intent": "FUNCTION_SELECT"},
    }


def _hint_and_proceed(hint: str, candidates: list[str] | None = None) -> dict:
    """Non-blocking: let the search proceed without a function filter,
    but signal the frontend to highlight chips and show a hint."""
    return {
        "requires_function_selection": False,
        "function_hint": hint,
        "functions_found": candidates or [],
    }
