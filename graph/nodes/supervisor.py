"""
Supervisor agent — routes incoming requests to the appropriate specialist
agent (registered through ``graph.agents``) or responds directly for
greetings and simple clarifications.

Built-in routes:
  - RESPOND      — direct reply (greetings, clarifications, general).
  - rag_graph    — knowledge retrieval pipeline (registered by default).

Additional agents (LMS, Expense, Scoreboard, …) plug in by calling
``register_agent(AgentSpec(...))`` in their package's ``__init__.py``.
The supervisor reads the registry at compile time and exposes:

  * The agent names as the ``RouteResponse.next`` Literal options.
  * Each agent's description in the system prompt's worker block.
  * Each agent's sub-graph as a workflow node.

Disabled agents (env flag ``ENABLE_<NAME>_AGENT=false``) are skipped.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Literal, Optional

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import AzureChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, create_model

from config import (
    AZURE_OPENAI_CHAT_API_VERSION,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
)
import graph.agents  # noqa: F401 — side-effect: registers built-in agents
from graph.agents import AGENT_RESPOND, AgentRegistry, AgentSpec
from graph.context_manager import prepare_supervisor_messages
from graph.nodes.memory_node import save_memory_node
from graph.nodes.persist_node import persist_node
from graph.state import RAGState
from prompts.supervisor_prompt import (
    FEW_SHOT_EXAMPLES,
    render_worker_descriptions,
    render_worker_routing_rules,
    supervisor_system_prompt,
)
from services.memory_store import (
    get_azure_sql_store,
    get_persistent_memory_checkpoint_saver_async,
)
from services.openai_client import get_llm_model

logger = logging.getLogger(__name__)


# Lock for thread-safe singleton initialisation under async concurrency
_init_lock = asyncio.Lock()


# ── Deterministic Pre-Router ──────────────────────────────────────────────
# Keyword-based routing that fires BEFORE the LLM supervisor. This ensures
# unambiguous queries with domain-specific terms are always routed correctly
# regardless of LLM judgment. Only genuinely ambiguous queries fall through
# to the LLM.

# Scoreboard KPI terms (column names / abbreviations users would mention)
_SCOREBOARD_KEYWORDS = re.compile(
    r"\b("
    r"GTER|ANSR|TER|NUI|"
    r"global\s*margin|eng\s*margin|"
    r"utilization|utilisation|"
    r"weighted\s*pipeline|"
    r"global\s*sales|"
    r"billing|collection|"
    r"backlog|"
    r"revenue\s*days|"
    r"plan\s*attainment|plan\s*achieved|"
    r"scoreboard|scorecard|"
    r"KPI|performance\s*metric"
    r")\b",
    re.IGNORECASE,
)

# Expense-specific terms (transaction data, not policy)
_EXPENSE_KEYWORDS = re.compile(
    r"\b("
    r"expense[s]?|reimbursement|"
    r"expense\s*type|air\s*travel|hotel|meals?|"
    r"vendor[s]?|receipt|"
    r"approval\s*status|payment\s*status|"
    r"cost\s*center|engagement\s*code|"
    r"transaction\s*amount|reimbursement\s*amount|"
    r"report\s*(?:id|name)|"
    r"country\s*of\s*purchase|city\s*of\s*purchase"
    r")\b",
    re.IGNORECASE,
)

# Data-intent — query phrasing that indicates the user actually wants
# numeric/aggregate/listing data rather than a casual mention. Combined
# with a domain-keyword match for expense + scoreboard pre-routing so a
# bare "I had a meal yesterday" doesn't latch onto the expense agent.
_DATA_INTENT_RE = re.compile(
    r"\b(how much|how many|total|sum|average|avg|max|min|top \d+|"
    r"highest|lowest|largest|smallest|show me|list|count|spend|spent|"
    r"FY\d{2}|Q[1-4]|last (month|quarter|year)|this (month|quarter|year)|"
    r"YTD|year to date|\d+(\.\d+)?)\b",
    re.IGNORECASE,
)


# LMS / Leave terms
_LMS_KEYWORDS = re.compile(
    r"\b("
    r"leave\s*balance|leave\s*taken|"
    r"annual\s*leave|sick\s*leave|"
    r"casual\s*leave|maternity|paternity|"
    r"leave\s*type|leave\s*status|"
    r"apply\s*(?:for\s*)?leave|"
    r"days?\s*(?:off|remaining)|"
    r"PTO|time\s*off|vacation"
    r")\b",
    re.IGNORECASE,
)


def _deterministic_route(user_input: str, available_agents: list[str]) -> str | None:
    """Return an agent name if keywords unambiguously match, else None.

    Only routes when EXACTLY ONE agent matches. If multiple match (ambiguous)
    or none match, returns None to let the LLM decide.
    """
    if not user_input:
        return None

    matches: list[tuple[str, int]] = []

    has_data_intent = bool(_DATA_INTENT_RE.search(user_input))

    if (
        "scoreboard_agent" in available_agents
        and _SCOREBOARD_KEYWORDS.search(user_input)
        and has_data_intent
    ):
        matches.append(("scoreboard_agent", len(_SCOREBOARD_KEYWORDS.findall(user_input))))

    if (
        "expense_agent" in available_agents
        and _EXPENSE_KEYWORDS.search(user_input)
        and has_data_intent
    ):
        matches.append(("expense_agent", len(_EXPENSE_KEYWORDS.findall(user_input))))

    # LMS routing is intent-agnostic — leave/PTO/vacation phrasing is
    # already action-oriented enough on its own.
    if "lms_agent" in available_agents and _LMS_KEYWORDS.search(user_input):
        matches.append(("lms_agent", len(_LMS_KEYWORDS.findall(user_input))))

    if not matches:
        return None

    if len(matches) == 1:
        return matches[0][0]

    # Multiple agents matched — pick the one with more keyword hits.
    # If tied, let the LLM decide.
    matches.sort(key=lambda x: x[1], reverse=True)
    if matches[0][1] > matches[1][1]:
        return matches[0][0]

    return None  # Ambiguous — let LLM decide


# ──────────────────────────────────────────────────────────────────────────


def _enabled_specs() -> list[AgentSpec]:
    """All currently enabled agent specs (env flags applied)."""
    return AgentRegistry.list(only_enabled=True)


def _build_system_prompt(specs: list[AgentSpec]) -> str:
    """Render the supervisor system prompt with fresh dates and the
    current registry-derived workers block.

    Built per-request so date references never go stale and so newly
    registered / disabled agents take effect immediately on next call.
    """
    now = datetime.now()
    return supervisor_system_prompt.format(
        current_date=now.strftime("%Y-%m-%d"),
        current_date_readable=now.strftime("%A, %B %d, %Y"),
        tomorrow_date=(now + timedelta(days=1)).strftime("%Y-%m-%d"),
        worker_descriptions=render_worker_descriptions(specs),
        worker_routing_rules=render_worker_routing_rules(specs),
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


def _build_route_response_model(options: list[str]) -> type[BaseModel]:
    """Construct ``RouteResponse`` with ``next: Literal[options]`` at runtime.

    Pydantic's ``with_structured_output`` needs a Literal so the LLM is
    constrained to valid agent names. The set of options depends on the
    registry, which can change between deployments / feature flags, so we
    build the model dynamically here.
    """
    if not options:
        # Defensive: at minimum "RESPOND" is always an option.
        options = [AGENT_RESPOND]
    next_type = Literal.__getitem__(tuple(options))  # type: ignore[arg-type]
    return create_model(
        "RouteResponse",
        next=(next_type, Field(description="The next step in the workflow")),
        suggestive_actions=(
            Optional[list[ActionResponse]],
            Field(default=None, description="Suggestive follow-up actions"),
        ),
        response=(
            Optional[str],
            Field(default=None, description="Optional direct response when next=RESPOND"),
        ),
    )


# ── Supervisor Graph ──

class SupervisorGraph:
    """Supervisor agent graph for routing and direct responses.

    Members are sourced from ``graph.agents.AgentRegistry`` at compile time.
    """

    def __init__(self):
        self._compiled_graph = None
        self._checkpoint_saver = None
        self._memory_store = None
        self._members: list[str] = []
        self._options: list[str] = []
        self._route_response_model: type[BaseModel] | None = None
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

    # ── Routing chain ──

    def _create_supervisor_chain(self, state: RAGState):
        """Build the supervisor routing chain for the given state.

        The system prompt is rebuilt per-request via _build_system_prompt()
        so dates and the (potentially flag-toggled) registry are always
        fresh.
        """
        specs = _enabled_specs()
        system_prompt = _build_system_prompt(specs)
        lang = state.get("preferred_language") or "English"
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                MessagesPlaceholder(variable_name="messages"),
                ("human", f"Ensure your response is in language: {lang}"),
            ]
        ).partial(
            options=str(self._options),
            members=", ".join(self._members),
        )
        return prompt | self.llm.with_structured_output(self._route_response_model)

    async def supervisor_agent(self, state: RAGState) -> Dict[str, Any]:
        """Route requests and provide direct responses when appropriate."""
        # ── Token-aware message trimming ──
        raw_messages = state.get("messages", [])
        existing_summary = state.get("summary", "")
        trimmed_messages, updated_summary = prepare_supervisor_messages(
            raw_messages, existing_summary
        )

        # ── Deterministic pre-routing (keyword match) ──
        user_input = state.get("user_input") or ""
        if not user_input and raw_messages:
            # Fall back to last human message content
            for msg in reversed(raw_messages):
                if hasattr(msg, "type") and msg.type == "human":
                    user_input = msg.content or ""
                    break
                elif isinstance(msg, dict) and msg.get("role") == "human":
                    user_input = msg.get("content", "")
                    break

        deterministic_target = _deterministic_route(user_input, self._members)
        if deterministic_target:
            logger.info(
                "supervisor: deterministic pre-route → %s (query: %s)",
                deterministic_target, user_input[:80],
            )
            return {
                "messages": [AIMessage(content="")],
                "next": deterministic_target,
                "suggestive_actions": None,
                "summary": updated_summary,
            }

        # ── Inject citation context for multi-turn resolution ──
        citation_map = state.get("citation_map")
        if citation_map:
            citation_lines = ["Previous citation references:"]
            for ref, info in citation_map.items():
                url = info.get("url", "")
                snippet = info.get("content_snippet", "")
                citation_lines.append(f"[{ref}] {url} — {snippet}")
            from langchain_core.messages import SystemMessage as _SM
            trimmed_messages.append(_SM(content="\n".join(citation_lines)))

        trimmed_state = {**state, "messages": trimmed_messages, "summary": updated_summary}

        supervisor_chain = self._create_supervisor_chain(trimmed_state)
        result = await supervisor_chain.ainvoke(trimmed_state)

        # ``result`` is an instance of the dynamically built RouteResponse
        next_target = getattr(result, "next", AGENT_RESPOND)
        response_text = getattr(result, "response", None)
        suggestive = getattr(result, "suggestive_actions", None)

        logger.info("supervisor: LLM routed → %s (query: %s)", next_target, user_input[:80])

        if next_target == AGENT_RESPOND and response_text:
            return {
                "messages": [AIMessage(content=response_text)],
                "ai_content": response_text,
                "is_free_form": True,
                "suggestive_actions": suggestive,
                "summary": updated_summary,
                "next": next_target,
            }

        return {
            "messages": [AIMessage(content=response_text or "")],
            "next": next_target,
            "suggestive_actions": suggestive,
            "summary": updated_summary,
        }

    @staticmethod
    def _get_next(state: RAGState) -> str:
        return state["next"]

    # ── Workflow construction ──

    def _build_workflow(self) -> StateGraph:
        """Build the supervisor workflow.

        Layout:
          START → Supervisor
                    ├─ RESPOND      → persist → save_memory → END
                    ├─ rag_graph    → END         (rag has its own persist)
                    ├─ <agent_b>    → END
                    └─ <agent_c>    → END

        Each agent is responsible for its own persist + save_memory tail
        when it produces a structured answer (this matches how rag_graph
        already works). The RESPOND path runs persist + save_memory in the
        supervisor itself so greetings still appear in chat history.
        """
        specs = _enabled_specs()
        self._members = [s.name for s in specs]
        self._options = [AGENT_RESPOND, *self._members]
        self._route_response_model = _build_route_response_model(self._options)

        workflow = StateGraph(RAGState)
        workflow.add_node("Supervisor", self.supervisor_agent)
        workflow.add_node("persist", persist_node)
        workflow.add_node("save_memory", save_memory_node)

        # Conditional routing map: every member name → its own node;
        # RESPOND → the shared persist node.
        conditional_map: dict[str, str] = {AGENT_RESPOND: "persist"}

        for spec in specs:
            sub_graph = spec.build_subgraph(
                store=self._memory_store,
                checkpointer=self._checkpoint_saver,
            )
            workflow.add_node(spec.name, sub_graph)
            workflow.add_edge(spec.name, END)
            conditional_map[spec.name] = spec.name

        workflow.add_conditional_edges("Supervisor", self._get_next, conditional_map)
        workflow.add_edge(START, "Supervisor")
        workflow.add_edge("persist", "save_memory")
        workflow.add_edge("save_memory", END)

        logger.info(
            "SupervisorGraph: built workflow with members=%s",
            self._members,
        )

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
