import json
import logging
import re
from collections import OrderedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

from graph.state import RAGState
from graph.context_manager import trim_messages_to_budget
from services.telemetry import get_tracer_span
from config import (
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
    AZURE_OPENAI_CHAT_API_VERSION,
    AZURE_OPENAI_TEMPERATURE,
    DUAL_CONTENT_SEARCH_ENABLED,
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


logger = logging.getLogger(__name__)

_FALLBACK_MESSAGE = (
    "I couldn't find a specific answer to your question in "
    "the available knowledge base. Please try rephrasing your "
    "query or provide more details."
)


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

    if summary:
        messages.append(SystemMessage(
            content=f"Summary of earlier conversation:\n{summary}",
        ))

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

    if citation_map:
        citation_lines = ["Previous citation references (for follow-up questions):"]
        for ref, info in citation_map.items():
            url = info.get("url", "")
            snippet = info.get("content_snippet", "")
            citation_lines.append(f"[{ref}] {url} — {snippet}")
        messages.append(SystemMessage(content="\n".join(citation_lines)))

    user_template_message = HumanMessage(content=user_template)

    # Build history from LangGraph checkpoint messages using unified context manager
    if langgraph_messages:
        # Filter out prior fallback messages so the LLM judges fresh results
        # independently, without being influenced by earlier "I couldn't find..." turns.
        filtered_messages = [
            m for m in langgraph_messages
            if not (isinstance(m, AIMessage) and m.content == _FALLBACK_MESSAGE)
        ]

        # Calculate available token budget for history (model limit minus reserved)
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
        available_budget = tokens_limit - reserved_tokens

        # Use unified context manager for sliding window trimming
        history_msgs = trim_messages_to_budget(
            filtered_messages[:-1],  # Exclude current message (appended separately)
            token_budget=available_budget,
            model=real_model_name,
        )
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


# ── Document fallback detection ───────────────────────────────────────────
# Phrases the LLM uses when it can't answer from document content.
# Triggers a graph-level retry with content_type="qa_pair".
_DOC_FALLBACK_PHRASES = (
    "the provided documents do not explicitly state",
    "does not explicitly state",
    "not explicitly mentioned",
    "no relevant information found",
    "the documents do not specify",
    "i wasn't able to find a specific answer",
    "couldn't find a specific answer",
    "rephrase your question",
    "I couldn't find a specific answer to your question in the available knowledge base. Please try rephrasing your query or provide more details."
)


def _needs_document_fallback(ai_content: str) -> bool:
    """Check if the LLM response indicates documents didn't contain the answer."""
    text = (ai_content or "").lower()
    return any(phrase in text for phrase in _DOC_FALLBACK_PHRASES)


# ── Groundedness Verification ──────────────────────────────────────────────

# Minimum ratio of claim tokens found in source document content.
_GROUNDEDNESS_THRESHOLD = 0.25

_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must",
    "in", "on", "at", "to", "for", "with", "by", "from", "of", "about",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "under", "over", "out", "up", "down", "off",
    "and", "or", "but", "not", "no", "nor", "so", "yet", "both",
    "this", "that", "these", "those", "it", "its", "they", "them",
    "he", "she", "his", "her", "we", "our", "you", "your",
    "which", "what", "who", "whom", "where", "when", "how", "why",
    "if", "then", "than", "also", "very", "just", "only", "more",
})


def _tokenize(text: str) -> set[str]:
    """Extract meaningful lowercase tokens (skip stopwords and short tokens)."""
    words = re.findall(r"\b[a-z0-9]+(?:[-/][a-z0-9]+)*\b", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _verify_groundedness(ai_content: str, events: list) -> str:
    """Remove inline citations not grounded in the cited source document.

    Splits output into segments around [N] references, checks token-level
    overlap between the preceding claim text and the cited document's content.
    Strips ungrounded citations (overlap < threshold).
    """
    if not events or not ai_content:
        return ai_content

    # Split into alternating text/citation-cluster segments
    segments = re.split(r"(\[\d+\](?:\[\d+\])*)", ai_content)

    result_parts: list[str] = []
    current_claim = ""

    for part in segments:
        if re.fullmatch(r"(\[\d+\])+", part):
            # Citation cluster — verify each ref against the claim
            refs = re.findall(r"\[(\d+)\]", part)
            claim_tokens = _tokenize(current_claim)

            if not claim_tokens:
                # No meaningful tokens — keep citations as-is (headings, short phrases)
                result_parts.append(part)
            else:
                verified: list[str] = []
                for ref_str in refs:
                    idx = int(ref_str) - 1
                    if 0 <= idx < len(events):
                        doc_content = events[idx].get("content", "")
                        doc_tokens = _tokenize(doc_content)
                        if not doc_tokens:
                            continue
                        overlap = claim_tokens & doc_tokens
                        ratio = len(overlap) / len(claim_tokens)
                        if ratio >= _GROUNDEDNESS_THRESHOLD:
                            verified.append(ref_str)
                        else:
                            logger.debug(
                                "groundedness: stripped [%s] (overlap=%.2f < %.2f)",
                                ref_str, ratio, _GROUNDEDNESS_THRESHOLD,
                            )

                if verified:
                    result_parts.append("".join(f"[{r}]" for r in verified))

            current_claim = ""
        else:
            current_claim = part
            result_parts.append(part)

    return "".join(result_parts)


# ── Citation Block Builder ─────────────────────────────────────────────────


def _rebuild_citations_block(ai_content: str, events: list) -> str:
    """Build the Citations block entirely in code from events source data.

    The LLM only outputs inline [N] references. This function:
    1. Extracts all [N] references from the LLM output
    2. Maps each to the actual source_url from events
    3. Renumbers citations sequentially starting from [1]
    4. Groups shared URLs (e.g. [1][2] https://...)
    5. Strips any LLM-generated citation block (safety net)
    6. Appends the deterministic code-built block
    """
    if not events:
        return ai_content

    used_refs = sorted(set(re.findall(r"\[(\d+)\]", ai_content)), key=int)
    if not used_refs:
        return ai_content

    # Map original refs to source URLs (skip invalid/internal URLs)
    ref_to_url: dict[str, str] = {}
    for ref_str in used_refs:
        idx = int(ref_str) - 1
        if 0 <= idx < len(events):
            doc = events[idx]
            source_url = (doc.get("source_url") or "").strip()
            # Skip internal chatbot URLs — not useful as citations
            if "MENABusinessEnablementChatbot" in source_url:
                source_url = ""
            if source_url:
                ref_to_url[ref_str] = source_url

    if not ref_to_url:
        # Strip any LLM-generated citation block and inline refs with no valid URL
        stripped = re.sub(r"(?i)\n*Citations:\s*\n.*", "", ai_content, flags=re.DOTALL).rstrip()
        stripped = re.sub(r"\[\d+\]", "", stripped)
        return stripped

    # Renumber: map original ref numbers to sequential 1, 2, 3...
    valid_refs = sorted(ref_to_url.keys(), key=int)
    old_to_new: dict[str, str] = {old: str(i + 1) for i, old in enumerate(valid_refs)}

    # Replace inline refs in content (strip refs without valid URLs)
    stripped = re.sub(r"(?i)\n*Citations:\s*\n.*", "", ai_content, flags=re.DOTALL).rstrip()

    def _replace_ref(m: re.Match) -> str:
        old_ref = m.group(1)
        new_ref = old_to_new.get(old_ref)
        return f"[{new_ref}]" if new_ref else ""

    stripped = re.sub(r"\[(\d+)\]", _replace_ref, stripped)

    # Build citations block with new numbering
    url_to_refs: OrderedDict[str, list[str]] = OrderedDict()
    for old_ref in valid_refs:
        url = ref_to_url[old_ref]
        new_ref = old_to_new[old_ref]
        url_to_refs.setdefault(url, []).append(new_ref)

    citation_lines = []
    for url, refs in url_to_refs.items():
        refs_label = "".join(f"[{r}]" for r in refs)
        citation_lines.append(f"{refs_label} {url}")

    new_block = "Citations:\n" + "\n".join(citation_lines)

    return f"{stripped}\n\n{new_block}"


async def _generate_response(
    events: list,
    state: RAGState,
) -> tuple[str, str, dict | None, object]:
    """Core generation logic.

    Returns (ai_content, prompt_used, citation_map, response_message).
    Streaming is always enabled — LangGraph captures per-token events via
    "messages" stream mode for the client.
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
        response = await llm.ainvoke(messages)

        # Extract content — for tool calls, get the arguments JSON
        if response.tool_calls:
            ai_content = json.dumps(response.tool_calls[0]["args"])
        else:
            ai_content = response.content or ""

        # ── Verify groundedness — remove citations not supported by source ──
        if is_free_form and ai_content and events:
            ai_content = _verify_groundedness(ai_content, events)
            # Rebuild citations block with only verified references
            ai_content = _rebuild_citations_block(ai_content, events)

        # ── Build citation map for multi-turn tracking ──
        citation_map = None
        if is_free_form and ai_content and events:
            used_refs = set(re.findall(r"\[(\d+)\]", ai_content))
            if used_refs:
                citation_map = {}
                for ref_str in used_refs:
                    idx = int(ref_str) - 1
                    if 0 <= idx < len(events):
                        doc = events[idx]
                        source_url = doc.get("source_url", "")
                        if "MENABusinessEnablementChatbot" in source_url:
                            source_url = ""
                        if source_url:
                            citation_map[ref_str] = {
                                "url": source_url,
                                "content_snippet": (doc.get("content", ""))[:200],
                            }

        return ai_content, prompt_used, citation_map, response


async def generate_node(state: RAGState) -> dict:
    """Generate AI response with real-time token streaming.

    Uses streaming=True with ainvoke() so LangGraph's "messages" stream mode
    captures each token for real-time SSE delivery to the client.

    Generation NEVER re-searches — all retry/fallback is handled upstream
    by SearchService.search_with_retry() in search_node.
    If [NO_ANSWER], returns a user-friendly fallback message.
    """
    with get_tracer_span("generate_node"):
        events = state.get("events", [])

        # ── No events: search exhausted all retries upstream ──
        if not events:
            return {
                "ai_content": _FALLBACK_MESSAGE,
                "prompt_used": "",
                "citation_map": None,
                "messages": [AIMessage(content=_FALLBACK_MESSAGE)],
                "events": [],
            }

        # ── Generate response (streaming) ──
        ai_content, prompt_used, citation_map, response = await _generate_response(
            events, state,
        )

        # ── Handle [NO_ANSWER] — LLM couldn't answer from the provided context ──
        if (ai_content or "").strip().startswith("[NO_ANSWER]"):
            logger.info("generate_node: [NO_ANSWER] — returning fallback message")
            ai_content = _FALLBACK_MESSAGE
            response = AIMessage(content=ai_content)
            citation_map = None

        # ── Detect if document fallback should trigger ──
        # Skip when dual search is on — both content types already searched.
        # Only retries once: document → qa_pair (prevented by doc_fallback_attempted)
        trigger_fallback = (
            not DUAL_CONTENT_SEARCH_ENABLED
            and _needs_document_fallback(ai_content)
            and state.get("content_type", "document") == "document"
            and not state.get("doc_fallback_attempted", False)
        )

        return {
            "ai_content": ai_content,
            "prompt_used": prompt_used,
            "citation_map": citation_map,
            "needs_doc_fallback": trigger_fallback,
            "messages": [response],
            "events": events,
        }
