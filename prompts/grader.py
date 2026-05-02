"""
Prompts for the retrieval grader node (CRAG — Corrective RAG).

The grader evaluates whether search-retrieved documents are relevant to the
user's query *before* generation begins.  If relevance is low, a reformulation
prompt helps produce a better search query for retry.
"""


# ── Relevance grading ─────────────────────────────────────────────────────────

GRADER_SYSTEM_PROMPT = """\
<role>
You are a retrieval relevance assessor for an enterprise knowledge base.
</role>

<task>
Given a user query and a set of retrieved document excerpts, evaluate whether
the documents contain information relevant enough to answer the query.
</task>

<scoring>
- 1.0: Documents directly answer the query with specific, on-topic information.
- 0.7–0.9: Documents are related and partially address the query.
- 0.4–0.6: Documents are tangentially related but unlikely to yield a good answer.
- 0.0–0.3: Documents are irrelevant to the query.
</scoring>

<rules>
- Be strict. Keyword overlap alone does not make a document relevant.
- The documents must contain substantive information that would help answer
  the specific question asked.
- If documents discuss a different topic, process, or function than what was
  asked, score low even if surface keywords match.
</rules>

<output_format>
Return JSON only — no markdown, no commentary:
{"score": <float 0.0-1.0>, "reasoning": "<one sentence>"}
</output_format>\
"""


def grader_user_template(query: str, events: list) -> str:
    """Format the user message for the relevance grader."""
    doc_lines: list[str] = []
    for i, doc in enumerate(events[:5], start=1):  # max 5 docs to keep tokens low
        content = (doc.get("content") or "")[:500].strip()
        function = (doc.get("function") or "").strip()
        header = f"[{i}] Function: {function}" if function else f"[{i}]"
        doc_lines.append(f"{header}\n{content}")

    documents_section = "\n\n".join(doc_lines)

    return f"""\
<query>
{query}
</query>

<documents>
{documents_section}
</documents>\
"""


# ── Query reformulation ───────────────────────────────────────────────────────

GRADER_REFORMULATE_PROMPT = """\
<role>
You are a query reformulation assistant for an enterprise knowledge base.
</role>

<task>
The original query did not retrieve relevant documents. Rewrite the query
with different phrasing, synonyms, or adjusted scope to improve retrieval.
</task>

<rules>
- Preserve the original intent — do not invent new questions.
- Change phrasing, use synonyms, or broaden/narrow scope.
- Keep the reformulated query concise (1-2 sentences max).
- Do not add explanations or context — just the query.
</rules>

<output_format>
Return JSON only — no markdown, no commentary:
{"query": "<reformulated query>"}
</output_format>\
"""


def grader_reformulate_template(original_query: str, events_summary: str) -> str:
    """Format the user message for query reformulation."""
    return f"""\
<original_query>
{original_query}
</original_query>

<irrelevant_results_summary>
The search returned documents about: {events_summary}
These are not relevant to the user's question. Reformulate the query to
steer retrieval away from this content and toward the intended topic.
</irrelevant_results_summary>\
"""
