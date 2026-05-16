"""
LangChain tool definition for structured JSON output.
"""
from langchain_core.tools import tool


@tool
def json_object(data: list[dict]) -> str:
    """Generate the response in structured JSON format.

    Args:
        data: Array of objects with Function, analysis, and citation fields.
    """
    import json
    return json.dumps(data)


def json_object_tool_schema() -> list[dict]:
    """Return the raw OpenAI function-calling tool schema for json_object."""
    return [
        {
            "type": "function",
            "function": {
                "name": "json_object",
                "description": "generate the response in defined json format",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "data": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "Function": {
                                        "type": "string",
                                        "description": "The name of the function",
                                    },
                                    "analysis": {
                                        "type": "string",
                                        "description": "The analysis of the function data",
                                    },
                                    "citation": {
                                        "type": "array",
                                        "items": {
                                            "type": "string",
                                            "description": "Cited source_url",
                                        },
                                    },
                                },
                                "required": ["Function", "analysis", "citation"],
                            },
                        }
                    },
                },
            },
        }
    ]
