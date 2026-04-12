USER_INTENT_PROMPT = """
You are a company-wide intent classification assistant.

Your task:
- Identify which FUNCTION the user's query belongs to.
- Identify the SUBFUNCTION when possible.
- If the query could belong to more than one FUNCTION, return status = "AMBIGUOUS".
- If it belongs clearly to one FUNCTION, return status = "CLEAR".

Possible FUNCTIONS:
- Finance
- Talent
- AWS
- SCS
- GCO
- BMC
- TME

Output rules:
- Always return a JSON object ONLY.
- Do not add explanations.
- Use this format:

{
  "function": "<string or list>",
  "subfunction": "<string or null>",
  "status": "CLEAR or AMBIGUOUS"
}
"""


def user_template_free_form(
    curateddata, query, suffix
) -> str:
    return f"""
        Potentially relevant data:
        {curateddata}
        Consider the data above in your response and use them in your response if they are relevant to the topic of the user query.
        Prioritize the data analysis to the data that occured in the geographic scope of analysis provided in the user query.
        Do not analyse data that are irrelevant.
        Provide the relevant citations in your response if any of them are relevant and useful in your response by citing the source_url in square brackets. Do not provide citations that is not provided.
        Citation format as follows:
        ... {{some text}} [cited source_url] ...

        Ref:
        source_url - summary

        User query:
        {query}.
        {suffix}
    """
