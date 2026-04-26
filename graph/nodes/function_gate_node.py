"""
Function-gate node — runs at the top of the RAG sub-graph and decides
whether the user's selected MENA function actually matches the function
the query is about. Three short-circuit cases:

1. No function selected yet (new chat / first turn) → ask the user to
   pick one from the chips.
2. Selected function does not match the query intent → ask the user to
   re-select the right function.
3. Query plausibly maps to multiple functions → ask the user to
   disambiguate.

In all three cases the node sets ``requires_function_selection=True``,
emits an ``AIMessage`` with the short prompt, and lets the graph route
straight to ``persist`` so the SSE final event surfaces the flag.
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
from services.openai_client import get_llm_model

logger = logging.getLogger(__name__)


class FunctionGateVerdict(BaseModel):
    verdict: Literal["match", "ambiguous", "unclassified", "not_applicable"] = Field(
        description="Routing verdict for the query."
    )
    function: str | None = Field(
        default=None, description="Function code when verdict='match'."
    )
    candidates: list[str] = Field(
        default_factory=list,
        description="Candidate function codes when verdict='ambiguous'.",
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

_MISMATCH_MESSAGE_TEMPLATE = (
    "It seems like this query belongs to a different function "
    "({suggested}). Please select the function from mentioned MENA "
    "functions."
)

_AMBIGUOUS_MESSAGE_TEMPLATE = (
    "It seems like this query belongs to multiple functions: "
    "{candidates}. Please select the function from mentioned MENA "
    "functions."
)


async def function_gate_node(state: RAGState) -> dict:
    """Validate the selected MENA function before search."""
    user_input = (state.get("user_input") or "").strip()
    if not user_input:
        return {"requires_function_selection": False}

    selected = state.get("function") or []
    selected_code = selected[0] if selected else None

    prompt = ChatPromptTemplate.from_messages(
        [("system", FUNCTION_GATE_PROMPT), ("human", "{query}")]
    )
    chain = prompt | _get_llm().with_structured_output(FunctionGateVerdict)

    try:
        verdict: FunctionGateVerdict = await chain.ainvoke({"query": user_input})
    except Exception as exc:
        logger.warning("function_gate: classifier failed: %s", exc, exc_info=True)
        # Fail-open if a function was already chosen; otherwise force selection.
        if selected_code:
            return {"requires_function_selection": False}
        return _block_for_selection(_FIRST_TURN_MESSAGE)

    logger.info(
        "function_gate verdict=%s selected=%s suggested=%s candidates=%s",
        verdict.verdict, selected_code, verdict.function, verdict.candidates,
    )

    if verdict.verdict == "not_applicable":
        return {"requires_function_selection": False}

    if verdict.verdict == "ambiguous":
        if selected_code and selected_code in (verdict.candidates or []):
            return {"requires_function_selection": False}
        return _block_for_selection(
            _AMBIGUOUS_MESSAGE_TEMPLATE.format(
                candidates=", ".join(verdict.candidates or [])
            ),
            candidates=verdict.candidates or [],
        )

    if verdict.verdict == "unclassified":
        return {"requires_function_selection": False}

    # verdict == "match"
    suggested = (verdict.function or "").strip()
    if not selected_code:
        return _block_for_selection(_FIRST_TURN_MESSAGE)
    if suggested and suggested.lower() != selected_code.lower():
        return _block_for_selection(
            _MISMATCH_MESSAGE_TEMPLATE.format(suggested=suggested),
            candidates=[suggested],
        )
    return {"requires_function_selection": False}


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
