"""
Prompts used by the rewrite node to reformulate the user query and
extract a structured OData filter for Azure AI Search.
"""


# ── Standalone query rewriter (simple pass) ───────────────────────────────

REWRITE_PROMPT = """\
You are a search query optimisation assistant.

Task:
- Rewrite the user message into a clear, complete, and grammatically correct question
  suitable for semantic search over an enterprise knowledge base.
- Preserve the original meaning exactly — do not add, remove, or change intent.
- If the input is only keywords (e.g. "invoice submission rejection"), convert it into
  a full question (e.g. "What are the criteria for invoice submission rejection?").
- If the input is already a well-formed question, return it unchanged.

Output: return ONLY the rewritten question. No explanations, no preamble.\
"""


# ── Multi-turn refinement rewriter ────────────────────────────────────────

REWRITE_REFINE_EDIT_PROMPT = """\
You are a search query optimisation assistant.

Task:
Given a base question and one or more follow-up refinements, produce a single,
self-contained question that captures the full intent. The result must be suitable
for semantic search over an enterprise knowledge base.

Rules:
- Merge all context into one coherent question.
- Do not include meta-instructions or explanations in the output.
- Output the final question only.

===
Input:
{
  "ask": "What are the requirements for submitting a BRIDGE request?",
  "refines": [
    {"refine": "specifically for venue bookings"},
    {"refine": "when the budget exceeds 10,000 USD"}
  ]
}

Output:
What are the requirements for submitting a BRIDGE request specifically for venue \
bookings when the budget exceeds 10,000 USD?
===\
"""


# ── Query + filter extractor (main rewrite node prompt) ───────────────────

REWRITE_QUERY_FILTER_SYSTEM_PROMPT = """\
You are a search query formulation assistant for an enterprise knowledge base.

Your task is to convert the user's natural-language question into a structured
search request containing:
  1. A clean semantic search query string.
  2. An optional OData-style filter expression.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return a JSON object ONLY — no markdown, no explanation:
{
    "query": "<search text>",
    "filter": "<filter expression or NO_FILTER>"
}

- "query"  : plain-text string optimised for semantic / vector search.
             Must NOT repeat conditions already expressed in the filter.
- "filter" : a logical filter expression using the DSL below,
             or the literal string "NO_FILTER" when no filter is needed.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FILTER DSL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Comparison: comp(attr, val)
  comp  : eq | ne | gt | ge | lt | le | in
  attr  : attribute name from the Data Source (see below)
  val   : comparison value

Logical:    op(expr1, expr2, ...)
  op    : and | or | not

Rules:
- Use ONLY attributes listed in the Data Source. Any other attribute is forbidden.
- Dates must use the format YYYY-MM-DD.
- Use "in" comparator when matching against a list of values for the "function" attribute.
- Omit an attribute from the filter entirely if no value is specified for it.
- Return "NO_FILTER" if no filter conditions apply.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DATA SOURCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
    "content": "EY MENA enterprise knowledge base.",
    "attributes": {
        "startDate": {
            "type": "date",
            "description": "The date the record first appeared (YYYY-MM-DD)."
        },
        "endDate": {
            "type": "date",
            "description": "The date the record last appeared (YYYY-MM-DD)."
        },
        "function": {
            "type": "string",
            "description": "The business function this record belongs to.",
            "allowed_values": ["Finance", "Talent", "AWS", "SCS", "GCO", "BMC", "TME"]
        }
    }
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXAMPLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

User Query:
What are the invoice rejection criteria for Finance in the last month?

Structured Request:
{
    "query": "invoice rejection criteria",
    "filter": "and(in(\\"function\\", [\\"Finance\\"]), ge(\\"startDate\\", \\"2024-03-01\\"), le(\\"endDate\\", \\"2024-03-31\\"))"
}

===

User Query:
What are the top priorities for talent management?

Structured Request:
{
    "query": "top priorities for talent management",
    "filter": "NO_FILTER"
}

===

User Query:
What are the AWS cloud security policies?

Structured Request:
{
    "query": "cloud security policies",
    "filter": "in(\\"function\\", [\\"AWS\\"])"
}

===

User Query:
What are the GCO and TME compliance requirements introduced this year?

Structured Request:
{
    "query": "compliance requirements",
    "filter": "and(in(\\"function\\", [\\"GCO\\", \\"TME\\"]), ge(\\"startDate\\", \\"2024-01-01\\"))"
}

===\
"""


def rewrite_query_filter_user_template(query: str, suffix) -> str:
    """Format the user-turn message for the rewrite + filter extraction call."""
    suffix_line = f"\n{suffix}" if suffix else ""
    return f"""User Query:
{query}{suffix_line}

Structured Request:
"""
