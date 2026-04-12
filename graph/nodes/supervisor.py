import asyncio
import os
import json
from typing import Literal, Dict, Any, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import AzureChatOpenAI
from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph
from graph.rag_graph import build_rag_graph
from graph.nodes.validate_node import validate_node
from graph.nodes.memory_node import load_memory_node, save_memory_node
from graph.nodes.rewrite_node import rewrite_node
from graph.nodes.embed_node import embed_node
from graph.nodes.search_node import search_node
from graph.nodes.generate_node import generate_node
from graph.nodes.persist_node import persist_node
from services.memory_store import get_persistent_memory_checkpoint_saver_async, get_azure_sql_store
from prompts.supervisor_prompt import (
    supervisor_system_prompt,
    FEW_SHOT_EXAMPLES,
)
from datetime import datetime, timedelta

from graph.state import RAGState
from config import AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, AZURE_OPENAI_CHAT_DEPLOYMENT, AZURE_OPENAI_API_VERSION
from services.openai_client import create_async_client, get_llm_model

load_dotenv()

# Define the list of member agents
MEMBERS = ["rag_graph"]
OPTIONS_FOR_NEXT = ["RESPOND"] + MEMBERS

current_date = datetime.now().strftime("%Y-%m-%d")
current_date_readable = datetime.now().strftime("%A, %B %d, %Y")
tomorrow_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


class ActionResponse(BaseModel):
    """Model for individual action response."""

    short_title: str = Field(description="Short title of the action in user's preferred language")
    description: str | None = Field(
        default=None, description="expanded description of the action in user's preferred language"
    )


class SuggestiveActionResponse(BaseModel):
    """Response model for suggestive actions."""

    suggestive_actions: list[ActionResponse] = Field(
        description="List of suggestive actions "
    )


class RouteResponse(BaseModel):
    """Response model for routing decisions."""

    next: Literal[
        "RESPOND", "rag_graph",
    ] = Field(description="The next step in the workflow")
    suggestive_actions: list[ActionResponse] | None = Field(
        default=None, description=" suggestive actions that can be taken by the user in their preferred language"
    )

    response: str | None = Field(
        default=None, description="Optional direct response to the user in their preferred language"
    )


# Define the system prompt: a supervisor tasked with managing a conversation between workers
system_prompt = supervisor_system_prompt + FEW_SHOT_EXAMPLES


class SupervisorGraph:
    """Supervisor agent graph for routing and direct responses."""

    def __init__(self):
        self._supervisor_chain = None
        self._compiled_graph = None
        self._checkpoint_saver = None
        self._memory_store = None
        self._background_summary_task: Optional[asyncio.Task] = None
        self.llm = AzureChatOpenAI(
            azure_deployment="gpt-4o",
            api_key=AZURE_OPENAI_KEY,
            api_version="2024-02-01",
            temperature=0.3,
            max_tokens=None,
            timeout=None,
            streaming=True,
            max_retries=2,
        )

    def _create_supervisor_chain(self, state:RAGState):
        """Create and configure the supervisor chain."""
        if self._supervisor_chain is not None:
            return self._supervisor_chain

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    system_prompt.format(
                        current_date=current_date,
                        current_date_readable=current_date_readable,
                        tomorrow_date=tomorrow_date,
                    ),
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        ).partial(options=str(OPTIONS_FOR_NEXT), members=", ".join(MEMBERS))
        prompt = prompt + f"Ensure your response should be in language -{state['preferred_language']}"
        #print("^^^^787", state['preferred_language'])
        return prompt | self.llm.with_structured_output(RouteResponse)

    def generate_suggestive_actions(self, state: RAGState):
        """
        Generate suggestive actions for the user based on the current state.

        Args:
            state: Current state of the leave management system"""

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are an assistant that suggests helpful follow-up actions based on the conversation so far "
                    "suggest very simple and relevant actions that the user might want to take next"
                    ". Generate 3 helpful follow-up actions the user might want to take.",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )
        prompt = prompt + f"Ensure your response should be in language -{state['preferred_language']}"
        return prompt | self.llm.with_structured_output(SuggestiveActionResponse)

    async def supervisor_agent(self, state: RAGState) -> Dict[str, Any]:
        """
        Supervisor agent that routes requests and provides direct responses.

        Args:
            state: Current state of the RAG system

        Returns:
            Dictionary containing next step and optional messages
        """
        # Check if leave data has been parsed and needs to go to LMSAgent
        # leave_data = state["leave_application_data"]
        # if leave_data and isinstance(leave_data, dict) and any(leave_data.values()):
        #     # Leave data is parsed, route to LMSAgent for actual application
        #     return {
        #         "messages": [AIMessage(content="Processing your leave application...")],
        #         "next": "LMSAgent",
        #     }

        # Continue with normal supervisor routing
        supervisor_chain = self._create_supervisor_chain(state)
        result = await supervisor_chain.ainvoke(state)

        # Handle direct responses from supervisor
        if result.next == "RESPOND" and result.response:
            return {
                "messages": [AIMessage(content=result.response)],
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
        """Extract the next step from state."""
        return state["next"]

    # @staticmethod
    # def trim_messages(state: LeaveManagementState) -> LeaveManagementState:
    #     """Trim messages to the last 10 exchanges to manage context size."""
    #     max_exchanges = 5
    #     messages = state["messages"]
    #     if len(messages) > max_exchanges * 2:
    #         state["messages"] = messages[-(max_exchanges * 2):]
    #     return state

    def _build_workflow(self) -> StateGraph:
        """Build and configure the leave management workflow graph."""
        rag_graph = build_rag_graph(memory_store=self._memory_store)
        workflow = StateGraph(RAGState)
        workflow.add_node("rag_graph", rag_graph)
        workflow.add_node("Supervisor", self.supervisor_agent)

        # # Configure conditional routing
        conditional_map = {member: member for member in MEMBERS}
        conditional_map["RESPOND"] = END

        workflow.add_conditional_edges("Supervisor", self._get_next, conditional_map)

        # Configure start and end
        workflow.add_edge(START, "Supervisor")
        # Entry point
        workflow.add_edge("rag_graph", END)

        return workflow

    async def compile_graph(self):
        """Get the compiled graph with checkpoint saver initialized."""
        # Initialize checkpoint_saver - will be set in async context
        if self._checkpoint_saver is None:
            self._checkpoint_saver = await get_persistent_memory_checkpoint_saver_async(
                type="azure_sql"
            )

        # Initialize SQL-backed memory store for cross-session user memory
        if self._memory_store is None:
            self._memory_store = await get_azure_sql_store()

        # Compile graph once
        if self._compiled_graph is None:
            self._compiled_graph = self._build_workflow().compile(
                checkpointer=self._checkpoint_saver,
                store=self._memory_store,
            )

        return self._compiled_graph


_workflow_instance: Optional[SupervisorGraph] = None


async def get_graph():
    """Get the compiled graphs."""
    global _workflow_instance
    if _workflow_instance is None:
        _workflow_instance = SupervisorGraph()
    return await _workflow_instance.compile_graph()


def save_graph_visualization(filename: str = "graph_diagram.md") -> None:
    """
    Save the graph visualization as a Mermaid diagram.

    Args:
        filename: Name of the file to save the diagram to
    """
    import asyncio

    async def _async_save():
        supervisor_graph = SupervisorGraph()
        graph = await supervisor_graph.compile_graph()
        mermaid_diagram = graph.get_graph().draw_mermaid()

        with open(filename, "w", encoding="utf-8") as f:
            f.write("# Leave Management Workflow\n\n")
            f.write("```mermaid\n")
            f.write(mermaid_diagram)
            f.write("\n```\n")

        print(f"Graph visualization saved to {filename}")

    asyncio.run(_async_save())

    print(f"Graph visualization saved to {filename}")


if __name__ == "__main__":
    save_graph_visualization()
