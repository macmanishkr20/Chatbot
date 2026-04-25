"""
User-turn message templates injected just before the assistant's reply.
"""


def user_template_free_form(curateddata: list, query: str, suffix: str) -> str:
    """Build the user-turn message that includes numbered source documents,
    the user's query, and citation formatting instructions.

    Each document is assigned a numeric reference [1], [2], … that the LLM
    must use for inline citations.  Shared source URLs are consolidated in
    the citation block, e.g. ``[1][2] https://…`` when two references share
    the same URL.
    """

    # ── Format numbered source documents ──────────────────────────────────
    if curateddata and isinstance(curateddata[0], dict):
        docs_lines: list[str] = []
        for i, doc in enumerate(curateddata, start=1):
            content    = (doc.get("content")      or "").strip()
            source_url = (doc.get("source_url")   or "").strip()
            function   = (doc.get("function")     or "").strip()
            sub_fn     = (doc.get("sub_function") or "").strip()

            meta_parts = []
            if function:
                meta_parts.append(f"Function: {function}")
            if sub_fn:
                meta_parts.append(f"Sub-function: {sub_fn}")
            if not source_url:
                source_url = f"{function}_internal_QnA_document" if function else "internal_QnA_document"
            meta_parts.append(f"Source: {source_url}")

            fallback = doc.get("file_name")
            header = f"[{i}] " + (" | ".join(meta_parts) if meta_parts else fallback)
            docs_lines.append(f"{header}\n{content}")

        documents_section = "\n\n".join(docs_lines)
    else:
        documents_section = str(curateddata)

    # ── Build filter context line (only shown when a filter was applied) ──
    filter_context = f"\n<applied_filter>{suffix}</applied_filter>" if suffix else ""

    return f"""\
<source_documents>
{documents_section}
</source_documents>{filter_context}

<instructions>
- Answer the user query below using ONLY the source documents listed above.
- Do not use outside knowledge or make assumptions beyond the documents.
- Cite every factual claim with an inline numeric reference corresponding
  to the document number, e.g. [1] or [1][2]. Always start from [1] for the first document.
- Include a citation ONLY when the document's content **directly and explicitly**
  supports the claim. Do NOT cite a document loosely or for general context.
- Do NOT hallucinate or fabricate citations. If none of the documents support
  a statement, do not attach a citation to it.
- If the documents do not fully answer the query, say so clearly instead of
  guessing or forcing a citation.
</instructions>

<citation_format>
- Inline: place the reference number immediately after the supported
  statement, e.g. "... approval is required within 5 business days [1]."
- Citation block: list only the references you actually used inline,
  under a "Citations:" heading, one per line — [N] <source_url>.
  Do NOT include references that were not cited in the answer.
- If multiple reference numbers share the same source, group them on
  one line: [1][2] <source_url>.
- Every document will have a source — use it in the Citations block.
</citation_format>

<example>
Invoices must be submitted within 30 days of the service date [1].
Late submissions require manager approval [2].
The approval SLA is five business days [3].

Citations:
[1] https://ey.com/mena/finance/invoice-policy
[2][3] Finance_internal_QnA_Document.
</example>

<user_query>
{query}
</user_query>\
"""
