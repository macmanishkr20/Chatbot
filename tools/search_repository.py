"""
LangChain tool definitions for OpenAI function calling.
"""
from langchain_core.tools import tool


@tool
def search_functions_repository(query: str) -> str:
    """Search the enterprise functions repository that contains all the functions.

    Args:
        query: The fulltext query based on the intent to search the functions repository.
    """
    return f"Searching repository for: {query}"


def search_functions_repository_schema() -> list[dict]:
    """Return the raw OpenAI function-calling tool schema for searchFunctionsRepository."""
    return [
        {
            "type": "function",
            "function": {
                "name": "searchFunctionsRepository",
                "description": "Search the functions repository that contains all the functions that an enterprise uses",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The fulltext query based on the intent that is used to search the functions repository",
                        },
                    },
                    "required": ["query"],
                },
            },
        }
    ]
