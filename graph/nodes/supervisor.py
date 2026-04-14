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

from config import (
    AZURE_OPENAI_API_VERSION,
    AZURE_OPENAI_KEY,
)
from graph.rag_graph import build_rag_graph
from graph.state import RAGState
from graph.nodes.persist_node import persist_node
from graph.nodes.memory_node import save_memory_node
from prompts.supervisor_prompt import FEW_SHOT_EXAMPLES, supervisor_system_prompt
from services.memory_store import get_azure_sql_store, get_persistent_memory_checkpoint_saver_async
from services.openai_client import get_llm_model

logger = logging.getLogger(__name__)

MEMBERS = ["rag_graph"]
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
    next: Literal["RESPOND", "rag_graph"] = Field(
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
            api_version=AZURE_OPENAI_API_VERSION,
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
        return prompt | self.llm.with_structured_output(RouteResponse)

    async def supervisor_agent(self, state: RAGState) -> Dict[str, Any]:
        """Route requests and provide direct responses when appropriate."""
        supervisor_chain = self._create_supervisor_chain(state)
        result = await supervisor_chain.ainvoke(state)

        if result.next == "RESPOND" and result.response:
            return {
                "messages": [AIMessage(content=result.response)],
                # Set ai_content + is_free_form so persist_node can save the
                # greeting/direct reply to SQL (chat history).
                "ai_content": result.response,
                "is_free_form": True,
                "suggestive_actions": result.suggestive_actions,
                "next": result.next,
            }

        return {
            "messages": [AIMessage(content=result.response or "")],
            "next": result.next,
            "suggestive_actions": result.suggestive_actions,
        }

    @staticmethod
    def _get_next(state: RAGState) -> str:
        return state["next"]

    def _build_workflow(self) -> StateGraph:
        """Build and configure the supervisor workflow graph.

        RESPOND path: Supervisor → persist → save_memory → END
          Ensures greetings and direct replies are saved to SQL so they
          appear in the user's chat history (/conversations endpoint).

        rag_graph path: Supervisor → rag_graph → END
          rag_graph internally runs: load_memory → rewrite → embed →
          search → generate → persist → save_memory → END
        """
        rag_graph = build_rag_graph(memory_store=self._memory_store)
        workflow = StateGraph(RAGState)
        workflow.add_node("rag_graph", rag_graph)
        workflow.add_node("Supervisor", self.supervisor_agent)

        # persist + save_memory are shared by both paths so greetings and
        # direct RESPOND replies are stored in SQL chat history.
        workflow.add_node("persist", persist_node)
        workflow.add_node("save_memory", save_memory_node)

        # RESPOND routes to persist (not END) so the reply is persisted.
        conditional_map = {member: member for member in MEMBERS}
        conditional_map["RESPOND"] = "persist"

        workflow.add_conditional_edges("Supervisor", self._get_next, conditional_map)
        workflow.add_edge(START, "Supervisor")
        workflow.add_edge("rag_graph", END)
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
