"""
Rewrite node — query rewriting, filter extraction, coreference resolution,
and query decomposition (ASK-only).
"""

import datetime
import json
import logging
import re
from langchain_core.messages import BaseMessage
from services.telemetry import get_tracer_span
from graph.state import RAGState
from prompts.rewrite import (
    COREFERENCE_RESOLUTION_SYSTEM,
    QUERY_DECOMPOSITION_SYSTEM,
    REWRITE_QUERY_FILTER_SYSTEM_PROMPT,
    rewrite_query_filter_user_template,
)
from services.openai_client import (
    create_async_client,
    get_llm_model,
    prepare_model_args,
    retry_with_llm_backoff,
)
from config import (
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_KEY,
)

logger = logging.getLogger(__name__)


# ───────────────── Ambiguity Resolution ─────────────────


def _match_function(user_input: str, functions: list[str]) -> str | None:
    """Try to match user input to one of the available function names.

    Uses exact match, substring match, and abbreviation matching (first letter
    of each word) to handle inputs like 'C&I' → 'Client & Infrastructure'.
    Returns the matched function name or None.
    """
    if not user_input or not functions:
        return None

    normalized = user_input.strip().lower()

    # 1. Exact match (case-insensitive)
    for fn in functions:
        if fn.lower() == normalized:
            return fn

    # 2. Substring match (user input contained in function name or vice versa)
    substring_matches = []
    for fn in functions:
        fn_lower = fn.lower()
        if normalized in fn_lower or fn_lower in normalized:
            substring_matches.append(fn)
    if len(substring_matches) == 1:
        return substring_matches[0]

    # 3. Abbreviation match — first letters of words
    input_letters = [w[0] for w in re.findall(r'[a-zA-Z]+', normalized)]
    if input_letters:
        abbrev_matches = []
        for fn in functions:
            fn_words = re.findall(r'[a-zA-Z]+', fn.lower())
            fn_letters = [w[0] for w in fn_words]
            if input_letters == fn_letters:
                abbrev_matches.append(fn)
        if len(abbrev_matches) == 1:
            return abbrev_matches[0]

    return None


# ───────────────── filterToVector DSL Parser ─────────────────


def filter_to_vector(filter_string: str) -> dict:
    """
    Convert LLM filter DSL into Azure Search OData filter.
    """

    if not filter_string or filter_string == "NO_FILTER":
        return {"filter": None}

    filter_string = filter_string.strip()

    def split_top_level(expr: str):
        """
        Split arguments of and(...) / or(...) at top level only.
        """
        parts, buf, depth = [], "", 0
        for ch in expr:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append(buf.strip())
                buf = ""
                continue
            buf += ch
        if buf:
            parts.append(buf.strip())
        return parts

    def parse(expr: str) -> str:
        expr = expr.strip()

        # Logical operators
        if expr.startswith("and(") and expr.endswith(")"):
            inner = expr[4:-1]
            return " and ".join(parse(e) for e in split_top_level(inner))

        if expr.startswith("or(") and expr.endswith(")"):
            inner = expr[3:-1]
            return " or ".join(parse(e) for e in split_top_level(inner))

        if expr.startswith("not(") and expr.endswith(")"):
            inner = expr[4:-1]
            return f"not ({parse(inner)})"

        # Comparison operators
        m = re.match(r"(\w+)\(\s*\"?(\w+)\"?\s*,\s*(.+)\s*\)", expr)
        if not m:
            return ""

        comp, attr, val = m.groups()

        # Handle IN comparator (arrays).
        # Use search.in() directly — /any() lambda is only valid on Collection fields.
        if comp == "in":
            raw = val.strip("[] ").replace('"', '').replace("'", "")
            # Normalise to comma-separated values with no surrounding spaces
            values = ",".join(v.strip() for v in raw.split(",") if v.strip())
            return f"search.in({attr}, '{values}', ',')"

        # Handle date & scalar comparisons
        if comp in ("eq", "ne", "gt", "ge", "lt", "le"):
            val = val.replace('"', '').replace("'", "")
            return f"{attr} {comp} {val}"

        return ""

    odata_filter = parse(filter_string)
    return {"filter": odata_filter if odata_filter else None}

# ───────────────── Coreference Resolution ─────────────────


_FOLLOW_UP_INDICATORS = re.compile(
    r"\b(it|that|this|they|them|those|its|their|these|the same|"
    r"what about|how about|and for|same for|also for|tell me more)\b",
    re.IGNORECASE,
)


def _likely_needs_coreference(query: str, has_history: bool) -> bool:
    """Fast heuristic: does this query look like a follow-up?"""
    if not has_history:
        return False
    # Short queries (< 6 words) with no explicit topic are likely follow-ups
    words = query.split()
    if len(words) <= 5 and _FOLLOW_UP_INDICATORS.search(query):
        return True
    # Very short input (likely a topic switch like "TME:" or "Finance?")
    if len(words) <= 2 and not query.endswith("?"):
        return True
    # Contains pronouns/references
    if _FOLLOW_UP_INDICATORS.search(query):
        return True
    return False


@retry_with_llm_backoff()
async def _resolve_coreferences(query: str, conversation_context: str, llm_model: str) -> str:
    """Resolve pronouns and references using conversation history."""
    user_prompt = (
        f"<conversation_history>\n{conversation_context}\n</conversation_history>\n\n"
        f"<current_query>{query}</current_query>"
    )
    messages = [
        {"role": "system", "content": COREFERENCE_RESOLUTION_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]
    client = create_async_client(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_key=AZURE_OPENAI_KEY,
        llm_model=llm_model,
    )
    response = await client.chat.completions.create(
        **prepare_model_args(
            request_messages=messages,
            stream=False,
            use_data=False,
            tools=None,
            tool_choice=None,
            response_format="json_object",
            llm_model=llm_model,
        )
    )
    result = json.loads(response.choices[0].message.content)
    if result.get("needs_resolution") and result.get("resolved_query"):
        return result["resolved_query"]
    return query


# ───────────────── Query Decomposition ─────────────────


_DECOMPOSITION_SIGNALS = re.compile(
    r"\b(compare|comparison|difference between|versus|vs\.?|"
    r"how does .+ differ from|contrast|both .+ and|"
    r"across .+ and|between .+ and)\b",
    re.IGNORECASE,
)


def _likely_needs_decomposition(query: str) -> bool:
    """Fast heuristic: does this query need decomposition?"""
    return bool(_DECOMPOSITION_SIGNALS.search(query))


@retry_with_llm_backoff()
async def _decompose_query(query: str, llm_model: str) -> list[str] | None:
    """Decompose a complex query into sub-queries. Returns None if not needed."""
    messages = [
        {"role": "system", "content": QUERY_DECOMPOSITION_SYSTEM},
        {"role": "user", "content": query},
    ]
    client = create_async_client(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_key=AZURE_OPENAI_KEY,
        llm_model=llm_model,
    )
    response = await client.chat.completions.create(
        **prepare_model_args(
            request_messages=messages,
            stream=False,
            use_data=False,
            tools=None,
            tool_choice=None,
            response_format="json_object",
            llm_model=llm_model,
        )
    )
    result = json.loads(response.choices[0].message.content)
    if result.get("needs_decomposition") and result.get("sub_queries"):
        subs = result["sub_queries"]
        # Sanity: max 3, each must be non-empty
        return [s for s in subs[:3] if s and s.strip()]
    return None


# ───────────────── Conversation Context Helper ─────────────────


def _format_conversation_context(messages: list[BaseMessage], max_turns: int = 5) -> str:
    """Format recent conversation messages as context for the rewrite LLM.

    Returns a compact string with the last N user/assistant exchanges so the
    rewrite LLM can resolve follow-up queries (e.g. "TME:" → full intent).
    """
    if not messages:
        return ""

    # Take the last max_turns*2 messages (user + assistant pairs)
    recent = messages[-(max_turns * 2):]
    lines = []
    for msg in recent:
        if not isinstance(msg, BaseMessage):
            continue
        role = "User" if msg.type == "human" else "Assistant"
        content = (msg.content or "").strip()
        if content:
            # Truncate very long messages to keep context concise
            if len(content) > 300:
                content = content[:300] + "..."
            lines.append(f"{role}: {content}")

    return "\n".join(lines)


# ───────────────── LLM Rewrite Call ─────────────────


@retry_with_llm_backoff()
async def _rewrite_filters_query(query_with_filter: dict, llm_model: str, conversation_context: str = "") -> dict:
    """
    Rewrite query and extract structured filter using LLM.
    Includes conversation context to resolve follow-up queries.
    """
    # Build the user message with conversation context if available
    user_content = ""
    if conversation_context:
        user_content += f"<conversation_history>\n{conversation_context}\n</conversation_history>\n\n"
    user_content += rewrite_query_filter_user_template(
        query_with_filter["query"],
        query_with_filter["filter"],
    )

    messages = [
        {"role": "system", "content": REWRITE_QUERY_FILTER_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    client = create_async_client(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_key=AZURE_OPENAI_KEY,
        llm_model=llm_model,
    )

    response = await client.chat.completions.create(
        **prepare_model_args(
            request_messages=messages,
            stream=False,
            use_data=False,
            tools=None,
            tool_choice=None,
            response_format="json_object",
            llm_model=llm_model,
        )
    )
    #LLM responds with JSON.
    return json.loads(response.choices[0].message.content)


# ───────────────── Node ─────────────────


async def rewrite_node(state: RAGState) -> dict:
    """
    ASK-only rewrite node: rewrite query and extract structured search filter.
    """

    # START REWRITE NODE SPAN
    with get_tracer_span("rewrite_node"):

        updates: dict = {}

        input_type = state.get("input_type", "ask")
        user_input = state.get("user_input", "")
        start_date = state.get("start_date", "")
        source_url = state.get("source_url", [])
        llm_model = get_llm_model("rewrite_query")

        # Build conversation context from messages for follow-up resolution
        raw_messages = state.get("messages", [])
        # Exclude the last message (current user input) — it's already in user_input
        history_messages = raw_messages[:-1] if raw_messages else []
        conversation_context = _format_conversation_context(history_messages)

        # ASK-only
        if input_type == "ask":
            # ── Step 1: Coreference Resolution ──
            # Detect and resolve pronouns/references from follow-up queries
            resolved_input = user_input
            if _likely_needs_coreference(user_input, bool(conversation_context)):
                try:
                    resolved_input = await _resolve_coreferences(
                        user_input, conversation_context, llm_model
                    )
                    if resolved_input != user_input:
                        logger.info(
                            "Coreference resolved: '%s' → '%s'",
                            user_input, resolved_input,
                        )
                except Exception as exc:
                    logger.warning("Coreference resolution failed, using original: %s", exc)
                    resolved_input = user_input

            # ── Step 2: Query Decomposition ──
            # Detect comparison/multi-hop queries and decompose into sub-queries
            sub_queries = None
            if _likely_needs_decomposition(resolved_input):
                try:
                    sub_queries = await _decompose_query(resolved_input, llm_model)
                    if sub_queries:
                        logger.info(
                            "Query decomposed: '%s' → %s",
                            resolved_input, sub_queries,
                        )
                except Exception as exc:
                    logger.warning("Query decomposition failed, using original: %s", exc)

            # ── Step 3: Standard rewrite + filter extraction ──
            query_with_filter = {
                "query": resolved_input,
                "filter": {
                    "timeframe": start_date,
                    "source_url": source_url,
                },
            }

            rewritten_query = await _rewrite_filters_query(query_with_filter, llm_model, conversation_context)

            #Parse and sanitize filters
            structured_filter = filter_to_vector(
                rewritten_query.get("filter", "NO_FILTER")
            )
            rewritten_query["filter"] = structured_filter.get("filter")

            updates["rewritten_query"] = rewritten_query

            # Pass sub-queries downstream if decomposition was needed
            if sub_queries:
                updates["sub_queries"] = [
                    {"function": None, "query": sq} for sq in sub_queries
                ]
                updates["needs_multi_search"] = True

        return updates