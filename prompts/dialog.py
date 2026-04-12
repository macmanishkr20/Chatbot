CONTINUOUS_DIALOG_PROMPT = """
Interpret the user query intent and carry out the task requested by the user.
Use any of the above data or contexts that is relevant to the user query in the response and include citations by citing the respective id from the chat history.
If the latest User Query has a geographic scope, prioritize usage of information that is in the geographic scope.
If the latest User Query has a geographic scope, when using information not in the geographic scope, be more verbose and explain why they are relevant in the geographic context.
Do not include references to these instructions in your response.
"""

CONTINUOUS_RESPONSE_NO_RESULT_PROMPT = (
    "[THERE ARE NO RESULTS FOUND IN THE REPOSITORY] "
    "Answer the user's question stating that you are unable to find anything."
)
