import json
import re
from collections import OrderedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

from graph.state import RAGState
from services.telemetry import get_tracer_span
from config import (
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
    AZURE_OPENAI_CHAT_API_VERSION,
    AZURE_OPENAI_TEMPERATURE,
    MAX_TOKENS,
)
from prompts.system import SYSTEM_FREE_FORM_PROMPT, SYSTEM_JSON_FORM_PROMPT
from prompts.user import user_template_free_form
from services.openai_client import (
    get_llm_model,
    get_model_info,
    get_tokens_count,
)
from tools.json_output import json_object


def _create_message_structure(
    system_template: str,
    user_template: str,
    llm_model: str,
    summary: str = "",
    langgraph_messages: list | None = None,
    user_memories: list[str] | None = None,
    citation_map: dict | None = None,
) -> list:
    """Build the LangChain messages list for the LLM call.

    Conversation history comes exclusively from LangGraph checkpoint
    messages.  Cross-session context comes from the Store (user_memories).
    Citation map enables multi-turn citation resolution.
    """
    messages = [SystemMessage(content=system_template)]

    # Inject conversation summary if available
    if summary:
        messages.append(SystemMessage(
            content=f"Summary of earlier conversation:\n{summary}",
        ))

    # Inject long-term user memories from LangGraph Store
    # Separate user preferences from session history for clearer context
    if user_memories:
        preferences = [m for m in user_memories if m.startswith("User preferences:")]
        sessions = [m for m in user_memories if not m.startswith("User preferences:")]

        if preferences:
            messages.append(SystemMessage(content="\n".join(preferences)))

        if sessions:
            messages.append(SystemMessage(
                content=(
                    "Relevant context from the user's past sessions "
                    "(use if helpful, do not repeat verbatim):\n"
                    + "\n".join(sessions)
                ),
            ))

    # Inject prior citation map for multi-turn citation resolution
    if citation_map:
        citation_lines = ["Previous citation references (for follow-up questions):"]
        for ref, info in citation_map.items():
            url = info.get("url", "")
            snippet = info.get("content_snippet", "")
            citation_lines.append(f"[{ref}] {url} — {snippet}")
        messages.append(SystemMessage(content="\n".join(citation_lines)))

    user_template_message = HumanMessage(content=user_template)

    # Build history from LangGraph checkpoint messages
    if langgraph_messages:
        real_model_name, tokens_limit = get_model_info(llm_model)
        reserved_tokens = (
            get_tokens_count(
                [{"role": "system", "content": m.content} for m in messages],
                real_model_name,
            )
            + get_tokens_count(
                {"role": "user", "content": user_template}, real_model_name
            )
            + int(MAX_TOKENS)
        )
        available_tokens = tokens_limit - reserved_tokens
        token_count = 0
        history_msgs = []
        # Walk messages in order, skip the latest human (it's in user_template)
        for msg in langgraph_messages[:-1]:
            role = "user" if msg.type == "human" else "assistant"
            content = msg.content or ""
            msg_tokens = get_tokens_count({"role": role, "content": content}, real_model_name)
            if token_count + msg_tokens > available_tokens:
                break
            if role == "user":
                history_msgs.append(HumanMessage(content=content))
            else:
                history_msgs.append(AIMessage(content=content))
            token_count += msg_tokens
        messages.extend(history_msgs)

    messages.append(user_template_message)
    return messages


def _get_tools_and_templates(events: list, is_free_form: bool, rewritten_query: dict, sub_function: str) -> tuple:
    query_text = rewritten_query.get("query", "") if rewritten_query else ""
    filter_text = rewritten_query.get("filter", "") if rewritten_query else ""

    if is_free_form:
        tools = None
        system_template = SYSTEM_FREE_FORM_PROMPT
    else:
        tools = [json_object]
        system_template = SYSTEM_JSON_FORM_PROMPT

    user_template = user_template_free_form(events, query_text, filter_text)

    return tools, system_template, user_template


def _get_llm(llm_model: str, tools: list | None) -> AzureChatOpenAI:
    """Create an AzureChatOpenAI instance with streaming enabled."""
    llm = AzureChatOpenAI(
        azure_deployment=llm_model,
        api_key=AZURE_OPENAI_KEY,
        api_version=AZURE_OPENAI_CHAT_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        temperature=AZURE_OPENAI_TEMPERATURE,
        max_tokens=int(MAX_TOKENS),
        streaming=True,
        max_retries=2,
    )
    if tools:
        return llm.bind_tools(tools, tool_choice={"type": "function", "function": {"name": "json_object"}})
    return llm


def _rebuild_citations_block(ai_content: str, events: list) -> str:
    """Replace the LLM-generated Citations block with one built from actual source_url values.

    This ensures citations are deterministic and always reflect the search
    result's ``source_url`` field, regardless of LLM non-determinism.
    """
    if not events:
        return ai_content

    # Collect all [N] references used in the answer text
    used_refs = sorted(set(re.findall(r"\[(\d+)\]", ai_content)), key=int)
    if not used_refs:
        return ai_content

    # Map each ref to its source_url (with fallback)
    ref_to_url: dict[str, str] = {}
    for ref_str in used_refs:
        idx = int(ref_str) - 1  # citations are 1-indexed
        if 0 <= idx < len(events):
            doc = events[idx]
            source_url = (doc.get("source_url") or "").strip()
            if not source_url:
                fn = (doc.get("function") or "unknown").strip()
                source_url = f"{fn}_internal_QnA_document"
            ref_to_url[ref_str] = source_url

    if not ref_to_url:
        return ai_content

    # Group refs that share the same URL
    url_to_refs: OrderedDict[str, list[str]] = OrderedDict()
    for ref_str in used_refs:
        url = ref_to_url.get(ref_str)
        if url:
            url_to_refs.setdefault(url, []).append(ref_str)

    # Build new citations block
    citation_lines = []
    for url, refs in url_to_refs.items():
        refs_label = "".join(f"[{r}]" for r in refs)
        citation_lines.append(f"{refs_label} {url}")

    new_block = "Citations:\n" + "\n".join(citation_lines)

    # Strip old LLM-generated Citations block (case-insensitive, from "Citations:" to end)
    stripped = re.sub(r"(?i)\n*Citations:\s*\n.*", "", ai_content, flags=re.DOTALL).rstrip()

    return f"{stripped}\n\n{new_block}"


async def _generate_response(
    events: list,
    state: RAGState,
    streaming: bool = True,
) -> tuple[str, str, dict | None, object]:
    """Core generation logic reusable by generate_node and multi_function_search_node.

    Returns (ai_content, prompt_used, citation_map, response_message).
    """
    with get_tracer_span("generate_node"):
        is_free_form = state.get("is_free_form", False)
        rewritten_query = state.get("rewritten_query", {})
        sub_function = state.get("sub_function", "")
        llm_model = get_llm_model("events")
        summary = state.get("summary", "")
        langgraph_messages = state.get("messages", [])
        user_memories = state.get("user_memories", [])
        prior_citation_map = state.get("citation_map")

        tools, system_template, user_template = _get_tools_and_templates(
            events, is_free_form, rewritten_query, sub_function
        )

        messages = _create_message_structure(
            system_template, user_template, llm_model,
            summary=summary,
            langgraph_messages=langgraph_messages,
            user_memories=user_memories,
            citation_map=prior_citation_map,
        )

        prompt_used = user_template

        llm = _get_llm(llm_model, tools)
        if not streaming:
            # Non-streaming variant — used for intermediate checks in multi-function search
            llm = AzureChatOpenAI(
                azure_deployment=llm_model,
                api_key=AZURE_OPENAI_KEY,
                api_version=AZURE_OPENAI_CHAT_API_VERSION,
                azure_endpoint=AZURE_OPENAI_ENDPOINT,
                temperature=AZURE_OPENAI_TEMPERATURE,
                max_tokens=int(MAX_TOKENS),
                streaming=False,
                max_retries=2,
            )
            if tools:
                llm = llm.bind_tools(tools, tool_choice={"type": "function", "function": {"name": "json_object"}})

        response = await llm.ainvoke(messages)

        # Extract content — for tool calls, get the arguments JSON
        if response.tool_calls:
            ai_content = json.dumps(response.tool_calls[0]["args"])
        else:
            ai_content = response.content or ""

        # ── Rebuild Citations block from actual source_url values ──
        if is_free_form and ai_content and events:
            ai_content = _rebuild_citations_block(ai_content, events)

        # ── Build citation map for multi-turn tracking ──
        citation_map = None
        if is_free_form and ai_content and events:
            used_refs = set(re.findall(r"\[(\d+)\]", ai_content))
            if used_refs:
                citation_map = {}
                for ref_str in used_refs:
                    idx = int(ref_str) - 1  # citations are 1-indexed
                    if 0 <= idx < len(events):
                        doc = events[idx]
                        source_url = doc.get("source_url", "")
                        if not source_url:
                            fn = doc.get("function", "unknown")
                            source_url = f"{fn}_internal_QnA_document"
                        citation_map[ref_str] = {
                            "url": source_url,
                            "content_snippet": (doc.get("content", ""))[:200],
                        }

        return ai_content, prompt_used, citation_map, response


async def generate_node(state: RAGState) -> dict:
    """Generate AI response using AzureChatOpenAI with real-time token streaming.

    Uses LangChain's AzureChatOpenAI so that stream_mode='messages' in LangGraph
    automatically captures and streams each token to the client.

    Conversation context comes from:
      - **Checkpoint messages** (short-term, this thread)
      - **user_memories** (long-term, from Store)
    """
    with get_tracer_span("generate_node"):
        events = state.get("events", [])

        if not events and not state.get("error_info"):
            return {"messages": [AIMessage(content="No Data Available")]}

        ai_content, prompt_used, citation_map, response = await _generate_response(
            events, state, streaming=True,
        )

        # ── Strip [NO_ANSWER] prefix — replace with a helpful fallback ──
        # The LLM may respond with [NO_ANSWER] when the retrieved documents
        # don't cover the query.  This must never reach the user verbatim.
        if (ai_content or "").strip().startswith("[NO_ANSWER]"):
            functions_found = state.get("functions_found", [])
            fn_hint = f" ({', '.join(functions_found)})" if functions_found else ""
            ai_content = (
                "I wasn't able to find a specific answer for your query in the "
                f"available documents{fn_hint}. To help me get you the best result, "
                "could you please select the specific function your question "
                "relates to? This will allow me to search more precisely."
            )
            response = AIMessage(content=ai_content)

        return {
            "ai_content": ai_content,
            "prompt_used": prompt_used,
            "citation_map": citation_map,
            "messages": [response],
        }
