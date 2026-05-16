"""
Supervisor agent — routes incoming requests to the appropriate sub-graph
or responds directly for greetings and simple clarifications.

Currently supported routes:
  - RESPOND  : direct reply (greetings, clarifications, general questions)
  - rag_graph: knowledge retrieval pipeline

Future routes (not yet wired):
  - LMSAgent, ClaimAgent, ExpenseAgent, …
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Literal, Optional

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import AzureChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from core.config import (
    AZURE_OPENAI_CHAT_API_VERSION,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
)
from core.rbac import is_rank_allowed
from agents.rag.graph import build_rag_graph
from agents.rag.state import RAGState
from agents.lms.graph import build_lms_graph
from agents._base.nodes.persist import persist_node
from agents._base.nodes.memory import save_memory_node
from orchestrator.prompts import FEW_SHOT_EXAMPLES, supervisor_system_prompt
from services.memory_store import get_azure_sql_store, get_persistent_memory_checkpoint_saver_async
from agents._base.context_manager import prepare_supervisor_messages
from infrastructure.openai.client import  get_llm_model

logger = logging.getLogger(__name__)

# Members must stay in sync with:
#   - RouteResponse.next Literal below
#   - core.rbac.AGENT_ALLOWED_RANK_CODES (access rules)
#   - api/_runtime.NODE_THOUGHT (UI thinking labels)
# Order is intentional: rag_graph first as the safe default.
MEMBERS = ["rag_graph", "lms_agent"]
OPTIONS_FOR_NEXT = ["RESPOND"] + MEMBERS

# Lock for thread-safe singleton initialisation under async concurrency
_init_lock = asyncio.Lock()


def _build_system_prompt() -> str:
    """Build the system prompt with fresh dates — called per-request so
    dates never go stale if the server runs across midnight."""
    now = datetime.now()
    return supervisor_system_prompt.format(
        current_date=now.strftime("%Y-%m-%d"),
        current_date_readable=now.strftime("%A, %B %d, %Y"),
        tomorrow_date=(now + timedelta(days=1)).strftime("%Y-%m-%d"),
    ) + FEW_SHOT_EXAMPLES


# ── Pydantic response models ──

class ActionResponse(BaseModel):
    short_title: str = Field(description="Short title of the action in user's preferred language")
    description: str | None = Field(
        default=None,
        description="Expanded description of the action in user's preferred language",
    )


class SuggestiveActionResponse(BaseModel):
    suggestive_actions: list[ActionResponse] = Field(
        description="List of suggestive actions"
    )


class RouteResponse(BaseModel):
    next: Literal["RESPOND", "rag_graph", "lms_agent"] = Field(
        description="The next step in the workflow"
    )
    suggestive_actions: list[ActionResponse] | None = Field(
        default=None,
        description="Suggestive actions for the user in their preferred language",
    )
    response: str | None = Field(
        default=None,
        description="Optional direct response to the user in their preferred language",
    )


# ── Supervisor Graph ──

class SupervisorGraph:
    """Supervisor agent graph for routing and direct responses."""

    def __init__(self):
        self._compiled_graph = None
        self._checkpoint_saver = None
        self._memory_store = None
        self.llm = AzureChatOpenAI(
            azure_deployment=get_llm_model("events"),
            api_key=AZURE_OPENAI_KEY,
            api_version=AZURE_OPENAI_CHAT_API_VERSION,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            temperature=0.3,
            max_tokens=None,
            timeout=None,
            streaming=True,
            max_retries=2,
        )

    def _create_supervisor_chain(self, state: RAGState):
        """Build the supervisor routing chain for the given state.

        The system prompt is built per-request via _build_system_prompt()
        so that date references are always fresh.

        Uses a non-streaming LLM clone for structured output to avoid
        PydanticSerializationUnexpectedValue when the checkpointer
        serialises intermediate AIMessages with a `parsed` field.
        """
        system_prompt = _build_system_prompt()
        lang = state.get("preferred_language") or "English"
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                MessagesPlaceholder(variable_name="messages"),
                ("human", f"Ensure your response is in language: {lang}"),
            ]
        ).partial(options=str(OPTIONS_FOR_NEXT), members=", ".join(MEMBERS))
        # Disable streaming for structured output — supervisor routing decisions
        # are not streamed to the user, and streaming + with_structured_output
        # causes Pydantic serialisation warnings in the checkpointer.
        routing_llm = self.llm.bind(stream=False)
        return prompt | routing_llm.with_structured_output(RouteResponse)

    async def supervisor_agent(self, state: RAGState) -> Dict[str, Any]:
        """Route requests and provide direct responses when appropriate.

        Before invoking the LLM, messages are trimmed to fit within the
        token budget via context_manager.prepare_supervisor_messages().
        Older messages are condensed into a summary so the LLM retains
        context without exceeding the context window.
        """
        # ── Token-aware message trimming ──
        raw_messages = state.get("messages", [])
        existing_summary = state.get("summary", "")
        trimmed_messages, updated_summary = prepare_supervisor_messages(
            raw_messages, existing_summary
        )

        # ── Inject citation context for multi-turn resolution ──
        # When the user says "tell me more about [2]", the supervisor
        # needs this context to route correctly to rag_graph.
        citation_map = state.get("citation_map")
        if citation_map:
            citation_lines = ["Previous citation references:"]
            for ref, info in citation_map.items():
                url = info.get("url", "")
                snippet = info.get("content_snippet", "")
                citation_lines.append(f"[{ref}] {url} — {snippet}")
            from langchain_core.messages import SystemMessage as _SM
            trimmed_messages.append(_SM(content="\n".join(citation_lines)))

        # ── Inject selected-function constraint for suggestive_actions ──
        # When the user has selected one or more MENA function chips,
        # ALL 3 suggestive_actions must be scoped to those functions only.
        # When no chip is selected, suggestion generation continues with its
        # default (topic-relevant or mixed-function fallback) behaviour.
        selected_functions = state.get("function") or []
        if selected_functions:
            fn_list = ", ".join(selected_functions)
            from langchain_core.messages import SystemMessage as _SM
            trimmed_messages.append(_SM(content=(
                f"The user has selected MENA function chip(s): {fn_list}. "
                "ALL 3 `suggestive_actions` MUST be focused exclusively on "
                "these function(s)' policies, processes, tools, and topics. "
                "Do NOT suggest topics from any other MENA function. "
                "If multiple functions are selected, distribute the 3 "
                "suggestions across only those selected functions. "
                "This constraint applies to suggestive_actions only — it "
                "does NOT change routing decisions or the direct response."
            )))

        # Replace messages in state copy for this LLM call only
        trimmed_state = {**state, "messages": trimmed_messages, "summary": updated_summary}

        supervisor_chain = self._create_supervisor_chain(trimmed_state)
        result = await supervisor_chain.ainvoke(trimmed_state)

        if result.next == "RESPOND" and result.response:
            return {
                "messages": [AIMessage(content=result.response)],
                # Set ai_content + is_free_form so persist_node can save the
                # greeting/direct reply to SQL (chat history).
                "ai_content": result.response,
                "is_free_form": True,
                "suggestive_actions": result.suggestive_actions,
                "summary": updated_summary,
                "next": result.next,
            }

        return {
            "messages": [AIMessage(content=result.response or "")],
            "next": result.next,
            "suggestive_actions": result.suggestive_actions,
            "summary": updated_summary,
        }

    @staticmethod
    def _get_next(state: RAGState) -> str:
        """Route to the next node, enforcing rank-based access control.

        rag_graph and RESPOND are always open.
        Any future agent added to MEMBERS with a restricted AGENT_ALLOWED_RANK_CODES
        entry will be automatically gated here — no extra code needed.

        When access is denied, we set ``access_denied_reason`` on state via a
        side-channel (the supervisor inspects it on the next turn). Because
        _get_next is a pure routing function we cannot mutate state from
        here; instead we attach the reason via a thread-local set inside the
        supervisor_agent. v1: simply log and fall back to RESPOND; the
        supervisor will craft a generic polite reply on the next turn.
        """
        next_node = state.get("next", "RESPOND")
        # Only gate non-RAG, non-RESPOND agents
        if next_node not in ("RESPOND", "rag_graph"):
            rank_code = state.get("rank_code")
            if not is_rank_allowed(next_node, rank_code):
                logger.warning(
                    "supervisor._get_next: rank_code=%s denied access to %s → falling back to RESPOND",
                    rank_code,
                    next_node,
                )
                return "RESPOND"
        return next_node

    def _build_workflow(self) -> StateGraph:
        """Build and configure the supervisor workflow graph.

        Paths:
          - RESPOND   → persist → save_memory → END
                        (greetings, denials, clarifications saved to SQL)
          - rag_graph → END        (rag_graph runs its own persist + save_memory)
          - lms_agent → END        (lms_agent runs its own persist + save_memory)
        """
        rag_graph = build_rag_graph(memory_store=self._memory_store)
        lms_agent = build_lms_graph(memory_store=self._memory_store)

        workflow = StateGraph(RAGState)
        workflow.add_node("rag_graph", rag_graph)
        workflow.add_node("lms_agent", lms_agent)
        workflow.add_node("Supervisor", self.supervisor_agent)

        # persist + save_memory are used by the RESPOND path so direct replies
        # and denials still land in SQL chat history.
        workflow.add_node("persist", persist_node)
        workflow.add_node("save_memory", save_memory_node)

        # RESPOND routes to persist (not END) so the reply is persisted.
        conditional_map = {member: member for member in MEMBERS}
        conditional_map["RESPOND"] = "persist"

        workflow.add_conditional_edges("Supervisor", self._get_next, conditional_map)
        workflow.add_edge(START, "Supervisor")
        workflow.add_edge("rag_graph", END)
        workflow.add_edge("lms_agent", END)
        workflow.add_edge("persist", "save_memory")
        workflow.add_edge("save_memory", END)

        return workflow

    async def compile_graph(self):
        """Compile the graph with checkpoint saver and memory store (idempotent)."""
        if self._checkpoint_saver is None:
            self._checkpoint_saver = await get_persistent_memory_checkpoint_saver_async(
                type="azure_sql"
            )

        if self._memory_store is None:
            self._memory_store = await get_azure_sql_store()

        if self._compiled_graph is None:
            self._compiled_graph = self._build_workflow().compile(
                checkpointer=self._checkpoint_saver,
                store=self._memory_store,
            )

        return self._compiled_graph


_workflow_instance: Optional[SupervisorGraph] = None


async def get_graph():
    """Return the singleton compiled supervisor graph (thread-safe)."""
    global _workflow_instance
    async with _init_lock:
        if _workflow_instance is None:
            _workflow_instance = SupervisorGraph()
        return await _workflow_instance.compile_graph()


def save_graph_visualization(filename: str = "graph_diagram.md") -> None:
    """Save the graph as a Mermaid diagram to *filename*."""

    async def _async_save():
        supervisor_graph = SupervisorGraph()
        graph = await supervisor_graph.compile_graph()
        mermaid_diagram = graph.get_graph().draw_mermaid()
        with open(filename, "w", encoding="utf-8") as f:
            f.write("# MenaBot Workflow\n\n")
            f.write("```mermaid\n")
            f.write(mermaid_diagram)
            f.write("\n```\n")
        logger.info("Graph visualization saved to %s", filename)

    asyncio.run(_async_save())


if __name__ == "__main__":
    save_graph_visualization()