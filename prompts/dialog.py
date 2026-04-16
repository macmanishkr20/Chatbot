"""
Dialog-management prompts for multi-turn conversation handling.
"""

CONTINUOUS_DIALOG_PROMPT = """\
Continue the conversation by addressing the user's latest query.
Use any relevant information from the documents and prior context provided above.
Include inline citations ([1], [2], etc.) for any factual claims drawn from the documents.
Do not reference or repeat these instructions in your response.\
"""

CONTINUOUS_RESPONSE_NO_RESULT_PROMPT = (
    "No relevant documents were found in the knowledge base for this query. "
    "Inform the user clearly that you were unable to find the requested information, "
    "and suggest they rephrase their question or contact the relevant team directly."
)
