from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

from graph.state import RAGState
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
) -> list:
    """Build the LangChain messages list for the LLM call.

    Conversation history comes exclusively from LangGraph checkpoint
    messages.  Cross-session context comes from the Store (user_memories).
    """
    messages = [SystemMessage(content=system_template)]

    # Inject conversation summary if available
    if summary:
        messages.append(SystemMessage(
            content=f"Summary of earlier conversation:\n{summary}",
        ))

    # Inject long-term user memories from LangGraph Store
    if user_memories:
        memories_text = "\n".join(user_memories)
        messages.append(SystemMessage(
            content=(
                "Relevant context from the user's past sessions "
                "(use if helpful, do not repeat verbatim):\n"
                + memories_text
            ),
        ))

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


async def generate_node(state: RAGState) -> dict:
    """Generate AI response using AzureChatOpenAI with real-time token streaming.

    Uses LangChain's AzureChatOpenAI so that stream_mode='messages' in LangGraph
    automatically captures and streams each token to the client.

    Conversation context comes from:
      - **Checkpoint messages** (short-term, this thread)
      - **user_memories** (long-term, from Store)
    """
    events = state.get("events", [])
    is_free_form = state.get("is_free_form", False)
    rewritten_query = state.get("rewritten_query", {})
    sub_function = state.get("sub_function", "")
    llm_model = get_llm_model("events")
    summary = state.get("summary", "")
    langgraph_messages = state.get("messages", [])
    user_memories = state.get("user_memories", [])

    if not events and not state.get("error_info"):
        return {"messages": [AIMessage(content="No Data Available")]}

    tools, system_template, user_template = _get_tools_and_templates(
        events, is_free_form, rewritten_query, sub_function
    )

    messages = _create_message_structure(
        system_template, user_template, llm_model,
        summary=summary,
        langgraph_messages=langgraph_messages,
        user_memories=user_memories,
    )

    prompt_used = user_template

    llm = _get_llm(llm_model, tools)
    response = await llm.ainvoke(messages)

    # Extract content — for tool calls, get the arguments JSON
    if response.tool_calls:
        import json
        ai_content = json.dumps(response.tool_calls[0]["args"])
    else:
        ai_content = response.content or ""

    return {
        "ai_content": ai_content,
        "prompt_used": prompt_used,
        "messages": [response],
    }
