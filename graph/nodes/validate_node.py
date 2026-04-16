"""
Validate node — greeting detection and intent classification (ASK-only).
"""

import re

from langchain_core.messages import HumanMessage

from graph.state import RAGState
from prompts.classifier import CLASSIFIER_PROMPT
from services.openai_client import (
    create_async_client,
    prepare_model_args,
    get_llm_model,
)

# ───────────────── Greeting Detection ─────────────────

#Regex pattern that matches only greeting
_GREETING_RE = re.compile(
    r"^(hi+|hello+|hey+|heyy+|hy+|hii+|hola|yo|gm|greetings|good\s*"
    r"(morning|afternoon|evening|night|day))\b",
    re.IGNORECASE,
)

# Function that checks if input is greeting or not
def _is_greeting(text: str) -> bool:
    """
    Check if the user input is a simple greeting.
    """
    if not text:
        return False
    return _GREETING_RE.match(text.strip().lower()) is not None


# ───────────────── Intent Classification ─────────────────

# This function uses the LLM to classify user intent
async def _classify_intent(user_input: str) -> str:
    """
    Use LLM to classify the intent of the user query.
    Returns one of: VALID_QUERY, CASUAL, INVALID
    """
    client = create_async_client(llm_model=get_llm_model("classifier"))

    messages = [
        {"role": "system", "content": CLASSIFIER_PROMPT},
        {"role": "user", "content": user_input},
    ]

    # Sends query to LLM 
    response = await client.chat.completions.create(
        **prepare_model_args(
            request_messages=messages,
            stream=False,
            use_data=False,
            tools=None,
            tool_choice=None,
            response_format="text",
            llm_model=get_llm_model("classifier"),
        )
    )

    # Extracts only the label (VALID_QUERY, CASUAL, INVALID).
    return response.choices[0].message.content.strip()


# ───────────────── Node ─────────────────

async def validate_node(state: RAGState) -> dict:
    """
    Gatekeeper node.
    - Adds the user message to LangGraph messages
    - Handles greetings
    - Classifies intent
    - Allows only valid enterprise queries to continue the graph
    """

    #Reads the payload from the graph state
    user_input = state.get("user_input", "")

    # Always record the user's message into LangGraph messages for checkpoint
    human_msg = HumanMessage(content=user_input)

    # Greeting short-circuit
    if _is_greeting(user_input):
        return {
            "messages": [human_msg],
            "is_greeting": True,
            "intent": "CASUAL",
            "response": {
                "message": "Hello! How can I help you today?",
            },
        }

    # Intent classification
    intent = await _classify_intent(user_input)

    if intent == "CASUAL":
        return {
            "messages": [human_msg],
            "intent": "CASUAL",
            "response": {
                "message": "I only answer policy or service-related questions.",
            },
        }

    if intent == "INVALID":
        return {
            "messages": [human_msg],
            "intent": "INVALID",
            "response": {
                "message": "This question is outside the scope of available information.",
            },
        }

    # VALID_QUERY → allow graph to continue
    return {
        "messages": [human_msg],
        "intent": "VALID_QUERY", #Only valid queries continue the graph
    }