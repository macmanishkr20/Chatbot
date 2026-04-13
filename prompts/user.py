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
            if source_url:
                meta_parts.append(f"Source: {source_url}")

            header = f"[{i}] " + (" | ".join(meta_parts) if meta_parts else "Document")
            docs_lines.append(f"{header}\n{content}")

        documents_section = "\n\n".join(docs_lines)
    else:
        documents_section = str(curateddata)

    # ── Build filter context line (only shown when a filter was applied) ──
    filter_context = f"\nApplied filter: {suffix}" if suffix else ""

    return f"""\
Source Documents:
{documents_section}
{filter_context}

Instructions:
- Answer the user query below using ONLY the source documents listed above.
- Do not use outside knowledge or make assumptions beyond the documents.
- Cite every factual claim with an inline numeric reference corresponding to \
the document number, e.g. [1] or [2][3].
- Do not include a citation for a document unless its content directly \
supports the claim.

Citation format rules:
- Inline: place the reference number immediately after the supported statement,
  e.g. "... approval is required within 5 business days [1]."
- Citation block: list all references at the end under a "Citations:" heading.
  - One reference per line: [N] <source_url>
  - If multiple reference numbers share the same source URL, group them on one
    line: [1][2] <source_url>

Example output:
  Invoices must be submitted within 30 days of the service date [1].
  Late submissions require manager approval [2][3].

  Citations:
  [1] https://ey.com/mena/finance/invoice-policy
  [2][3] https://ey.com/mena/finance/approval-guidelines

User query:
{query}\
"""
