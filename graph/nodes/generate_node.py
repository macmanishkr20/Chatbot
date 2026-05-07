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
    GROUNDEDNESS_THRESHOLD,
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
        # Floor budget at 0 — passing a negative budget to the trimmer would
        # admit messages anyway (kept[0] check) and silently exceed the model
        # window. Treat over-budget as "no history fits" instead.
        available_budget = max(0, tokens_limit - reserved_tokens)

        # Use unified context manager for sliding window trimming
        if available_budget > 0:
            history_msgs = trim_messages_to_budget(
                langgraph_messages[:-1],  # Exclude current message (appended separately)
                token_budget=available_budget,
                model=real_model_name,
            )
            messages.extend(history_msgs)
        else:
            logger.warning(
                "generate_node: history budget exhausted by system prompt + user_template "
                "(reserved=%d limit=%d) — skipping prior messages",
                reserved_tokens, tokens_limit,
            )

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


# ── Groundedness Verification ──────────────────────────────────────────────

# Minimum ratio of claim tokens found in source document content.
# Configurable via GROUNDEDNESS_THRESHOLD env var (default 0.25 — same as
# previously hardcoded value, so behaviour is preserved).
_GROUNDEDNESS_THRESHOLD = GROUNDEDNESS_THRESHOLD

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


_TOKEN_RE = re.compile(r"\b[a-z0-9]+(?:[-/][a-z0-9]+)*\b")
# Numbers, codes, IDs, capitalised entities — high-signal tokens that must
# always be preserved (and weighted) regardless of stopword filtering.
_ENTITY_RE = re.compile(r"\b[A-Z0-9][A-Z0-9_/\-]{1,}\b")


def _tokenize(text: str) -> set[str]:
    """Extract meaningful lowercase tokens (skip stopwords and short tokens)."""
    words = _TOKEN_RE.findall(text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _bigrams(tokens_sequence: list[str]) -> set[tuple[str, str]]:
    """Build bigram set from an ordered token sequence (post stopword filter)."""
    return set(zip(tokens_sequence, tokens_sequence[1:]))


def _ordered_tokens(text: str) -> list[str]:
    """Return content tokens in order (used for bigrams)."""
    return [
        w for w in _TOKEN_RE.findall(text.lower())
        if w not in _STOPWORDS and len(w) > 2
    ]


def _entities(text: str) -> set[str]:
    """Extract identifier-like tokens (codes, IDs, capitalised acronyms)."""
    return {m.lower() for m in _ENTITY_RE.findall(text)}


def _grounded_score(claim: str, doc_content: str) -> float:
    """Composite groundedness score in [0, 1].

    Combines three signals so coincidental single-word matches no longer
    pass while genuine multi-word claims with shared phrasing pass cleanly:
      - unigram Jaccard-style ratio (original signal, weight 0.5)
      - bigram overlap ratio       (phrase-level signal, weight 0.3)
      - entity overlap ratio       (codes/IDs/acronyms, weight 0.2)
    Falls back gracefully when either side has too little signal.
    """
    claim_tokens = _tokenize(claim)
    doc_tokens = _tokenize(doc_content)
    if not claim_tokens or not doc_tokens:
        return 0.0

    unigram_ratio = len(claim_tokens & doc_tokens) / len(claim_tokens)

    claim_seq = _ordered_tokens(claim)
    doc_seq = _ordered_tokens(doc_content)
    claim_bigrams = _bigrams(claim_seq)
    if claim_bigrams:
        bigram_ratio = len(claim_bigrams & _bigrams(doc_seq)) / len(claim_bigrams)
    else:
        bigram_ratio = unigram_ratio  # short claim — fall back to unigrams

    claim_entities = _entities(claim)
    if claim_entities:
        entity_ratio = len(claim_entities & _entities(doc_content)) / len(claim_entities)
    else:
        entity_ratio = unigram_ratio  # no entities — fall back to unigrams

    return 0.5 * unigram_ratio + 0.3 * bigram_ratio + 0.2 * entity_ratio


def _verify_groundedness(ai_content: str, events: list) -> str:
    """Remove inline citations not grounded in the cited source document.

    Splits output into segments around [N] references, checks composite
    overlap (unigrams + bigrams + entities) between the preceding claim text
    and the cited document's content. Strips ungrounded citations
    (composite score < threshold).
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
                        doc_content = events[idx].get("content", "") or ""
                        if not doc_content.strip():
                            continue
                        score = _grounded_score(current_claim, doc_content)
                        if score >= _GROUNDEDNESS_THRESHOLD:
                            verified.append(ref_str)
                        else:
                            logger.debug(
                                "groundedness: stripped [%s] (score=%.2f < %.2f)",
                                ref_str, score, _GROUNDEDNESS_THRESHOLD,
                            )

                if verified:
                    result_parts.append("".join(f"[{r}]" for r in verified))

            current_claim = ""
        else:
            current_claim = part
            result_parts.append(part)

    return "".join(result_parts)


# ── Citation Block Builder ─────────────────────────────────────────────────


def _link_if_http(url: str) -> str:
    """Wrap URL in an anchor tag opening in a new tab if it's http(s).

    Only http:// and https:// URLs are made clickable — internal identifiers,
    SharePoint paths that didn't get normalised, or any other non-web string
    is returned as plain text. ``rel="noopener noreferrer"`` is the standard
    pairing with ``target="_blank"`` to prevent the new tab from accessing
    ``window.opener`` and to suppress referer leakage.
    """
    if not url:
        return ""
    lowered = url.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{url}</a>'
    return url


def _format_citation_line(refs: list[str], doc: dict) -> str:
    """Format one citation line based on the cited document's content_type.

    Behaviour by type:
      * qa_pair  → ``[N] <source_url>``
                   The Q&A pair *is* the canonical answer; URL is enough.
                   When no URL is indexed, the line is dropped (returns "").
      * document → ``[N] <file_name> (page <N>) — <source_url>``
                   For indexed PDFs/Word docs the file + page is the natural
                   reference a reader expects; the URL is appended when
                   present. Pieces missing from the index are dropped
                   gracefully; if nothing usable is available the line is
                   dropped (returns "").
    """
    refs_label = "".join(f"[{r}]" for r in refs)
    content_type = (doc.get("content_type") or "qa_pair").strip().lower()
    source_url = (doc.get("source_url") or "").strip()
    # Only the URL portion is wrapped in an anchor; the file_name and page
    # parts stay as plain text per product requirement.
    linked_url = _link_if_http(source_url) if source_url else ""

    if content_type != "document":
        # qa_pair (default) — URL only. Drop the line entirely if no URL
        # is available (no synthetic identifiers).
        if not source_url:
            return ""
        return f"{refs_label} {linked_url}"

    # document — build "file (page N) — url", omitting pieces gracefully.
    file_name = (doc.get("file_name") or "").strip()
    page_raw = doc.get("page_number")
    page_str = str(page_raw).strip() if page_raw not in (None, "") else ""

    label_parts: list[str] = []
    if file_name:
        if page_str:
            label_parts.append(f"{file_name} (page {page_str})")
        else:
            label_parts.append(file_name)
    elif page_str:
        label_parts.append(f"page {page_str}")

    if label_parts and source_url:
        return f"{refs_label} {label_parts[0]} — {linked_url}"
    if label_parts:
        return f"{refs_label} {label_parts[0]}"
    if source_url:
        return f"{refs_label} {linked_url}"
    # No metadata at all — drop the line.
    return ""


def _rebuild_citations_block(ai_content: str, events: list) -> str:
    """Build the Citations block deterministically from event metadata.

    The LLM only outputs inline [N] references. This function:
      1. Extracts all [N] references from the LLM output.
      2. Looks up the cited event's content_type and metadata.
      3. Builds a per-ref line via _format_citation_line() — qa_pair gets
         a URL-only line, document gets a file + page + URL line.
      4. Groups consecutive refs that resolve to the same line so output
         stays compact (e.g. ``[1][2] doc.pdf (page 4) — https://…``).
      5. Strips any LLM-emitted Citations block (defense in depth) and
         appends the rebuilt one.
    """
    if not events:
        return ai_content

    used_refs = sorted(set(re.findall(r"\[(\d+)\]", ai_content)), key=int)
    if not used_refs:
        return ai_content

    # Build (ref → formatted-line) and group refs that share an identical line.
    # A line is empty when the cited event has no usable metadata; skip those.
    ref_to_line: "OrderedDict[str, str]" = OrderedDict()
    for ref_str in used_refs:
        idx = int(ref_str) - 1
        if 0 <= idx < len(events):
            line = _format_citation_line([ref_str], events[idx])
            if line:
                ref_to_line[ref_str] = line

    # Always strip any LLM-emitted Citations block (defense in depth) so we
    # never leak a stale block when there's nothing real to attach.
    stripped = re.sub(r"(?i)\n*Citations:\s*\n.*", "", ai_content, flags=re.DOTALL).rstrip()

    if not ref_to_line:
        return stripped

    # Group refs whose individual line (with [r] stripped) matches. Track
    # the originating event for each group so we can sort document-first.
    line_body_to_refs: "OrderedDict[str, list[str]]" = OrderedDict()
    for ref_str, line in ref_to_line.items():
        body = re.sub(r"^(\[\d+\])+\s*", "", line)
        line_body_to_refs.setdefault(body, []).append(ref_str)

    # Build (priority, refs, body) tuples. Priority orders document (0) before
    # qa_pair / unknown (1) so the citation block lists docs first; within a
    # priority bucket the natural [N] order is preserved (stable sort).
    grouped: list[tuple[int, list[str], str]] = []
    for body, refs in line_body_to_refs.items():
        first_idx = int(refs[0]) - 1
        ct = ""
        if 0 <= first_idx < len(events):
            ct = (events[first_idx].get("content_type") or "").strip().lower()
        priority = 0 if ct == "document" else 1
        grouped.append((priority, refs, body))

    grouped.sort(key=lambda t: t[0])  # stable — preserves intra-bucket order

    # Emit one merged line per group, re-rendering against the cited doc so
    # the body and ref-cluster match exactly.
    citation_lines: list[str] = []
    for _, refs, body in grouped:
        first_idx = int(refs[0]) - 1
        if 0 <= first_idx < len(events):
            line = _format_citation_line(refs, events[first_idx])
            if line:
                citation_lines.append(line)
        else:
            refs_label = "".join(f"[{r}]" for r in refs)
            citation_lines.append(f"{refs_label} {body}")

    if not citation_lines:
        return stripped

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
                        source_url = (doc.get("source_url") or "").strip()
                        # Skip citation-map entries that have no usable
                        # provenance — no synthetic identifiers.
                        file_name = (doc.get("file_name") or "").strip()
                        if not source_url and not file_name:
                            continue
                        citation_map[ref_str] = {
                            "url": source_url,
                            "content_snippet": (doc.get("content", ""))[:200],
                            # Persist provenance so follow-up turns can also
                            # render type-appropriate citations consistently.
                            "content_type": (doc.get("content_type") or "qa_pair"),
                            "file_name": file_name,
                            "page_number": doc.get("page_number", ""),
                        }

        return ai_content, prompt_used, citation_map, response


async def generate_node(state: RAGState) -> dict:
    """Generate AI response with real-time token streaming.

    Uses streaming=True with ainvoke() so LangGraph's "messages" stream mode
    captures each token for real-time SSE delivery to the client.

    Generation NEVER re-searches — all retry/fallback is handled upstream by
    SearchService.search_with_retry() in search_node. When events are empty
    or the LLM emits [NO_ANSWER], we replace ai_content with a user-friendly
    fallback message AND set ``no_answer=True`` in state so downstream
    nodes / telemetry can distinguish a genuine answer from a fallback.

    The ``no_answer`` / ``search_retry_count`` state fields are kept for
    diagnostics and to leave the door open for a future corrective-RAG
    loop without having to re-plumb state.
    """
    with get_tracer_span("generate_node"):
        events = state.get("events", [])

        # ── No events: nothing to generate from ──
        if not events:
            logger.info("generate_node: empty events — emitting fallback")
            return {
                "ai_content": _FALLBACK_MESSAGE,
                "prompt_used": "",
                "citation_map": None,
                "messages": [AIMessage(content=_FALLBACK_MESSAGE)],
                "events": [],
                "no_answer": True,
            }

        # ── Generate response (streaming) ──
        ai_content, prompt_used, citation_map, response = await _generate_response(
            events, state,
        )

        # ── Handle [NO_ANSWER] — LLM couldn't answer from the provided context ──
        if (ai_content or "").strip().startswith("[NO_ANSWER]"):
            logger.info("generate_node: [NO_ANSWER] — emitting fallback")
            ai_content = _FALLBACK_MESSAGE
            response = AIMessage(content=ai_content)
            citation_map = None
            return {
                "ai_content": ai_content,
                "prompt_used": prompt_used,
                "citation_map": citation_map,
                "messages": [response],
                "events": events,
                "no_answer": True,
            }

        # ── Successful generation ──
        return {
            "ai_content": ai_content,
            "prompt_used": prompt_used,
            "citation_map": citation_map,
            "messages": [response],
            "events": events,
            "no_answer": False,
        }
