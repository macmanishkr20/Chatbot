"""
Rewrite node — query rewriting, filter extraction, and filter parsing (ASK-only).
"""

import datetime
import json
import re

from graph.state import RAGState
from prompts.rewrite import (
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

# ───────────────── LLM Rewrite Call ─────────────────


@retry_with_llm_backoff()
async def _rewrite_filters_query(query_with_filter: dict, llm_model: str) -> dict:
    """
    Rewrite query and extract structured filter using LLM.
    """
    messages = [
        {"role": "system", "content": REWRITE_QUERY_FILTER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": rewrite_query_filter_user_template(
                query_with_filter["query"],
                query_with_filter["filter"],
            ),
        },
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
    Also handles ambiguity resolution from a previous turn.
    """
    updates = {}

    # ── Ambiguity resolution ──
    # If the previous turn was ambiguous, check if the user is selecting a function.
    pending = state.get("pending_ambiguous_query")
    if pending and state.get("is_ambiguous"):
        user_input = state.get("user_input", "")
        functions_found = state.get("functions_found", [])

        # First check if an explicit function filter was provided via the API
        explicit_functions = state.get("function", [])
        matched_fn = None
        if explicit_functions:
            for ef in explicit_functions:
                for fn in functions_found:
                    if ef.strip().lower() == fn.strip().lower():
                        matched_fn = fn
                        break
                if matched_fn:
                    break

        # Then try to match from user input text
        if not matched_fn and user_input:
            matched_fn = _match_function(user_input, functions_found)

        if matched_fn:
            # Restore the original user_input so persist_node saves the real question
            original_user_input = pending.get("user_input", "")
            result = {
                "rewritten_query": pending["rewritten_query"],
                "function": [matched_fn],
                "is_ambiguous": False,
                "pending_ambiguous_query": None,
                "functions_found": [matched_fn],
            }
            if original_user_input:
                result["user_input"] = original_user_input
            return result
        # No match — user is asking a new question; clear ambiguity and fall through

    # Always clear ambiguity state when proceeding with normal rewrite
    updates["is_ambiguous"] = False
    updates["pending_ambiguous_query"] = None

    input_type = state.get("input_type", "ask")
    user_input = state.get("user_input", "")
    start_date = state.get("start_date", "")
    source_url = state.get("source_url", [])
    llm_model = get_llm_model("rewrite_query")

    # ASK-only
    if input_type == "ask":
        query_with_filter = {
            "query": user_input,
            "filter": {
                "timeframe": start_date,
                "source_url": source_url,
            },
        }

        rewritten_query = await _rewrite_filters_query(query_with_filter, llm_model)

        #Parse and sanitize filters
        structured_filter = filter_to_vector(
            rewritten_query.get("filter", "NO_FILTER")
        )
        rewritten_query["filter"] = structured_filter.get("filter")

        updates["rewritten_query"] = rewritten_query

    return updates