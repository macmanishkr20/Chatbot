REWRITE_PROMPT = """
You are a query rewriting assistant.

Your task:
- Rewrite the user's message into a clear, complete, grammatically correct question.
- Do NOT change the original meaning.
- Do NOT add information.
- Do NOT remove important words.
- If the user gives only keywords (example: "invoice submission rejection"),
  convert it into a meaningful question (example: "What is rejection in invoice submission?").
- If the user message is already a proper question, return it unchanged.
- Return ONLY the rewritten question. No explanations.
"""

REWRITE_REFINE_EDIT_PROMPT = """
You are a helpful assistant. You help users search for the answers to their questions.
User have a question and some follow-up questions. Create a general question for efficient searching in a vector database.
Always output in the following format:
===
Input example: {
    "ask": "What is new about cyclon in usa?",
    "refines":
        [
            { "refine": "How about tornado?" },
            { "refine": "west usa"}
        ]
}
Output Example:
What are the latest updates regarding cyclones in the USA, particularly in the western region? Also, how does this compare to recent occurrences of tornadoes in the same area?
"""

REWRITE_QUERY_FILTER_SYSTEM_PROMPT = """
You are a very helpful expert data analyst whose job is to formulate search query to find information on past data. Your goal is to structure the user's query to match the request schema provided below to search for data in a vector database with attributes as specified by the "Data Source".

**Structured Request Schema**
When responding use a markdown code snippet with a JSON object formatted in the following schema:

Always output in the following format:
{
    "query": string \\ text string to compare to document contents
    "filter": string \\ logical condition statement for filtering documents
}

The query string should contain only text that is expected to match the contents of documents. Any conditions in the filter should not be mentioned in the query as well.
A logical condition statement is composed of one or more comparison and logical operation statements.

A comparison statement takes the form: `comp(attr, val)`:
- `comp` (eq | ne | gt | ge | lt | le | in ): comparator
- `attr` (string):  name of attribute to apply the comparison to
- `val` (string): is the comparison value

A logical operation statement takes the form `op(statement1, statement2, ...)`:
- `op` (and | or | not): logical operator
- `statement1`, `statement2`, ... (comparison statements or logical operation statements): one or more statements to apply the operation to

Begin by checking if the array is empty or if no values are provided. This can be done using len(array).
If the array is empty or no values are provided, handle the situation accordingly without using the filter function.
If the array contains values, proceed with the desired operations or manipulations without using the filter function.
Make sure that you only use the comparators and logical operators listed above and no others.
Make sure that filters only refer to attributes that exist in the data source.
**Do not use any attributes that do no exist in the data source.
Make sure that filters only use the attributed names with its function names if there are functions applied on them.
Make sure that filters only use format `YYYY-MM-DD` when handling date data typed values.
Make sure that filters take into account the descriptions of attributes and only make comparisons that are feasible given the type of data being stored.
Make sure that filters are only used as needed. If there are no filters that should be applied return "NO_FILTER" for the filter value.
If values are present in array then use "in" comparator. if no value is provided in array then do not consider that attribute for filter
The op can be one of the following: and, or, not.
**in : comparator for attributes: city, country, function.**
**The filter should only refer to the existing attributes in the data source. If no filters should be applied, return "NO_FILTER" for the filter value.**
- Identify which FUNCTION the user's query belongs to.
- Identify the SUBFUNCTION when possible.

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

Data Source:
{
    "content": "EY enterprise Data.",
    "attributes": {
        "startDate": {
            "type": "date",
            "description": "date that the data first appear"
        },
        "endDate": {
            "type": "date",
            "description": "date that the data last appear"
        },
        "country": {
            "type": "string",
            "description": "the country that is involved in the data."
        },
        "city": {
            "type": "string",
            "description": "the city that is involved in the data."
        },
        "function": {
            "type": "string",
            "description": "the function of this data."
        }
    }
}

===
User Query:
How many and what are the invoice rejection criteria in Indonesia in the last month in Jakarta? Related function: [Finance]

Structured Request:
{
    "query": "invoice rejection criteria in Indonesia in the last month in Jakarta",
    "filter": "and(or(in(\\"country\\", [\\"Indonesia\\"]), in(\\"city\\", [\\"Jakarta\\"])), le(\\"endDate\\", \\"2023-12-14\\"), ge(\\"startDate\\", \\"2023-11-15\\"), in(\\"function\\", [\\"Finance\\"]))"
}

===

===
User Query:
What are top 3 things that an automaker should be aware of?

Structured Request:
{
    "query": "current issues for automotive sector",
    "filter": "NO_FILTER"
}

===

===
User Query:
Is there any existing policy in Australia for adhering brand image and marketing? Geographic scope of anlaysis: [Brisbane, Sydney, Melbourne, Fremantle];

Structured Request:
{
    "query": "existing policies in Australia for adhering brand image and marketing",
    "filter": "or(in(\\"country\\", [\\"Australia\\"]), in(\\"city\\", [\\"Brisbane\\", \\"Sydney\\", \\"Melbourne\\", \\"Fremantle\\"])), in(\\"function\\", [\\"Brand, Marketing and Communications\\"]))",
}

===

User Query:
Is there any new strategy that emerge in the last 3 weeks for CBS engagement? Geographic scope of analysis: ["Middle EAST and North Europe"]

Structured Request:
{
    "query": "new strategies for CBS engagement in Middle EAST and North Europe",
    "filter": "and(ge(\\"startDate\\", \\"2023-12-17\\"), le(\\"endDate\\", \\"2024-01-07\\"), in(\\"country\\", [\\"Middle EAST\\", \\"North Europe\\"]), in(\\"function\\", [\\"CBS\\"]))"
}

===

===

"""


def rewrite_query_filter_user_template(query: str, suffix) -> str:
    return f"""User Query:
{query}.
{suffix}

Structured Request:
"""
