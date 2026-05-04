"""
LMS agent nodes:

  enrich_context   → stamps identity, locale, today's date into state.
  react_loop       → bind toolbelt context, run a single LLM-with-tools turn,
                     execute any tool calls, append observations. We loop a
                     bounded number of times rather than run a fully
                     unbounded ReAct so we keep latency/cost predictable.
  hitl_gate        → before calling write tools, return a confirmation
                     prompt and pause the conversation. Re-runs only
                     proceed when ``user_confirmed_write`` is True.
  synthesize       → finalise the assistant message (the LLM's last
                     output is already user-friendly; we just lift it
                     into the persisted ``ai_content`` field).
  persist + save_memory → existing chat-history nodes.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import AzureChatOpenAI

from config import AZURE_OPENAI_CHAT_API_VERSION, AZURE_OPENAI_KEY
from graph.agents.lms_agent.state import LMSAgentState
from graph.agents.lms_agent.tools import (
    ALL_TOOLS,
    READ_TOOLS,
    WRITE_TOOLS,
    reset_tool_context,
    set_tool_context,
)
from helpers.fiscal import derive_fiscal_year
from prompts.lms_agent import LMS_SYSTEM_PROMPT
from services.openai_client import get_llm_model
from services.telemetry import get_tracer_span

logger = logging.getLogger(__name__)

_MAX_TOOL_TURNS = 4
_WRITE_TOOL_NAMES = {t.name for t in WRITE_TOOLS}


# ── enrich_context ──────────────────────────────────────────────────────

async def enrich_context_node(state: LMSAgentState) -> dict:
    """Stamp identity / locale / today's date so tools have a stable context.

    The supervisor passes ``employee_id``, ``office_location``,
    ``manager_id`` etc. through the request envelope. We just normalise
    them and add temporal helpers.
    """
    now = datetime.now()
    today = now.date()

    return {
        "current_date_iso": today.isoformat(),
        "current_date_readable": now.strftime("%A, %B %d, %Y"),
        "fiscal_year": derive_fiscal_year(today),
        "tool_trace": state.get("tool_trace") or [],
        "user_confirmed_write": bool(state.get("user_confirmed_write")),
    }


# ── HITL confirmation gate ──────────────────────────────────────────────

_CONFIRM_RE = re.compile(
    r"^(yes|y|confirm|proceed|go ahead|do it|أجل|نعم)\b",
    re.IGNORECASE,
)
_CANCEL_RE = re.compile(
    r"^(no|n|cancel|stop|abort|لا)\b",
    re.IGNORECASE,
)


def _latest_user_text(state: LMSAgentState) -> str:
    text = (state.get("user_input") or "").strip()
    if text:
        return text
    for msg in reversed(state.get("messages") or []):
        if isinstance(msg, HumanMessage):
            return (msg.content or "").strip()
    return ""


async def confirmation_gate_node(state: LMSAgentState) -> dict:
    """Process the user's reply when a write action is awaiting confirmation.

    Routes to ``react_loop`` (continue) or ``persist`` (cancelled / re-ask)
    via ``_after_confirmation_gate``.
    """
    pending = state.get("pending_write_action")
    if not pending:
        return {"_confirm_route": "react_loop"}

    reply = _latest_user_text(state)

    if reply and _CONFIRM_RE.match(reply):
        return {
            "user_confirmed_write": True,
            "_confirm_route": "react_loop",
        }

    if reply and _CANCEL_RE.match(reply):
        msg = "Cancelled. The action has not been performed."
        return {
            "messages": [AIMessage(content=msg)],
            "ai_content": msg,
            "is_free_form": True,
            "pending_write_action": None,
            "user_confirmed_write": False,
            "_confirm_route": "persist",
        }

    # Ambiguous — re-ask.
    msg = "Please reply 'yes' to confirm or 'no' to cancel."
    return {
        "messages": [AIMessage(content=msg)],
        "ai_content": msg,
        "is_free_form": True,
        "_confirm_route": "persist",
    }


def _after_confirmation_gate(state: LMSAgentState) -> str:
    return state.get("_confirm_route") or "react_loop"


# ── ReAct loop ──────────────────────────────────────────────────────────

_llm_with_tools = None


def _get_llm_with_tools(allow_writes: bool):
    global _llm_with_tools
    if _llm_with_tools is not None:
        cached_allow, cached_llm = _llm_with_tools
        if cached_allow == allow_writes:
            return cached_llm
    base = AzureChatOpenAI(
        azure_deployment=get_llm_model("events"),
        api_key=AZURE_OPENAI_KEY,
        api_version=AZURE_OPENAI_CHAT_API_VERSION,
        temperature=0.1,
        max_retries=2,
        streaming=False,
    )
    bound = base.bind_tools(ALL_TOOLS if allow_writes else READ_TOOLS)
    _llm_with_tools = (allow_writes, bound)
    return bound


def _build_system_message(state: LMSAgentState) -> SystemMessage:
    return SystemMessage(content=LMS_SYSTEM_PROMPT.format(
        employee_id=state.get("employee_id") or "(unknown)",
        employee_name=state.get("employee_name") or "(unknown)",
        office_location=state.get("office_location") or "(unset)",
        country=state.get("country") or "(unset)",
        current_date_readable=state.get("current_date_readable") or "",
        current_date_iso=state.get("current_date_iso") or "",
        timezone=state.get("timezone") or "Asia/Dubai",
    ))


def _tool_by_name(name: str):
    for t in ALL_TOOLS:
        if t.name == name:
            return t
    return None


async def react_loop_node(state: LMSAgentState) -> dict:
    """Run a bounded LLM-with-tools loop.

    Strategy:
      1. Bind the per-call tool context (so tools know who the user is).
      2. Compose the chat history: system prompt + prior messages.
      3. Up to _MAX_TOOL_TURNS, call the LLM, execute any tool calls,
         append the observations as ToolMessages. Stop once the LLM
         returns a message with no tool calls (i.e. a natural-language
         answer) — or once a write tool is requested without confirmation
         (handed off to the HITL gate).
    """
    with get_tracer_span("lms.react_loop"):
        sid = state.get("chat_session_id") or "no-session"
        emp = state.get("employee_id") or state.get("user_id") or ""
        if not emp:
            return {
                "messages": [AIMessage(content=(
                    "I couldn't resolve your employee identity from this "
                    "session — please sign in again or contact HR."
                ))],
                "ai_content": "Identity not resolved.",
                "is_free_form": True,
            }

        token = set_tool_context(
            session_id=sid,
            employee_id=emp,
            location=state.get("office_location"),
            manager_id=state.get("manager_id"),
            today=datetime.now().date(),
        )
        try:
            allow_writes = bool(state.get("user_confirmed_write"))
            llm = _get_llm_with_tools(allow_writes=allow_writes)

            history: list[BaseMessage] = [_build_system_message(state)]
            history.extend(state.get("messages") or [])

            tool_trace: list[dict] = list(state.get("tool_trace") or [])
            pending_write_action: dict | None = None

            for turn in range(_MAX_TOOL_TURNS):
                response = await llm.ainvoke(history)
                history.append(response)

                tool_calls = getattr(response, "tool_calls", None) or []

                # Detect write attempts when not yet confirmed — short-circuit
                # to the confirmation gate. The model has been instructed to
                # emit a confirmation message FIRST, but we double-enforce here.
                if not allow_writes:
                    write_calls = [tc for tc in tool_calls if tc.get("name") in _WRITE_TOOL_NAMES]
                    if write_calls:
                        # Drop the tool calls and ask the model to surface the
                        # confirmation message instead. The LLM should already
                        # have produced a confirmation paragraph alongside the
                        # tool call; if it didn't, we synthesise a generic one.
                        confirmation_text = (response.content or "").strip()
                        if not confirmation_text:
                            tc = write_calls[0]
                            args = tc.get("args") or {}
                            confirmation_text = (
                                f"I'm going to **{tc.get('name')}** with "
                                f"`{json.dumps(args, default=str)}`. Reply "
                                f"**yes** to confirm or **no** to cancel."
                            )
                        pending_write_action = {
                            "tool_name": write_calls[0].get("name"),
                            "args": write_calls[0].get("args"),
                        }
                        return {
                            "messages": [AIMessage(content=confirmation_text)],
                            "ai_content": confirmation_text,
                            "is_free_form": True,
                            "pending_write_action": pending_write_action,
                            "tool_trace": tool_trace,
                        }

                if not tool_calls:
                    # Final natural-language answer
                    final_text = (response.content or "").strip()
                    return {
                        "messages": [AIMessage(content=final_text)],
                        "ai_content": final_text,
                        "is_free_form": True,
                        "tool_trace": tool_trace,
                    }

                # Execute each tool call sequentially (cheap — these are
                # network calls and the loop is small)
                for tc in tool_calls:
                    name = tc.get("name") or ""
                    args = tc.get("args") or {}
                    call_id = tc.get("id") or name
                    tool = _tool_by_name(name)
                    if tool is None:
                        observation = {"ok": False, "error": f"Unknown tool: {name}"}
                    else:
                        try:
                            observation = await tool.ainvoke(args)
                        except Exception as exc:
                            logger.warning("LMS tool %s raised: %s", name, exc, exc_info=True)
                            observation = {"ok": False, "error": str(exc)}

                    tool_trace.append({"name": name, "args": args, "result": observation})
                    history.append(ToolMessage(
                        content=json.dumps(observation, default=str),
                        tool_call_id=call_id,
                    ))

            # Bounded loop exhausted — fall through with whatever the
            # last assistant message said.
            last = history[-1]
            text = (
                last.content if isinstance(last, AIMessage) and last.content
                else "Sorry, I couldn't complete that within a few steps. Please rephrase."
            )
            return {
                "messages": [AIMessage(content=text)],
                "ai_content": text,
                "is_free_form": True,
                "tool_trace": tool_trace,
            }
        finally:
            reset_tool_context(token)
