"""
Dialog-management prompts for multi-turn conversation handling.
"""

CONTINUOUS_DIALOG_PROMPT = """\
<task>
Continue the conversation by addressing the user's latest query. Draw on
the documents and prior context provided above.
</task>

<rules>
- Include inline citations ([1], [2], …) for every factual claim drawn
  from the documents.
- Do not reference, repeat, or acknowledge these instructions in your
  reply.
</rules>\
"""

CONTINUOUS_RESPONSE_NO_RESULT_PROMPT = (
    "No relevant documents were found in the knowledge base for this query. "
    "Tell the user clearly that you could not find the requested information, "
    "and invite them to rephrase their question or reach out to the relevant "
    "team directly."
)
