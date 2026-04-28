"""
Title generation utility — produces a short conversation title from the
first user message and AI response, matching the Claude/ChatGPT UX pattern.

This is NOT a graph node; it's called from persist_node when a new
conversation is created.
"""
import logging

from config import TITLE_MAX_LENGTH
from prompts.title_prompt import TITLE_GENERATION_PROMPT
from services.openai_client import (
    create_async_client,
    get_llm_model,
    prepare_model_args,
)

logger = logging.getLogger(__name__)


async def generate_title(user_input: str, ai_response: str) -> str:
    """Generate a 3-8 word conversation title via a lightweight LLM call.

    Falls back to a truncated user_input on any failure so the conversation
    always has a meaningful title.
    """
    try:
        prompt_text = TITLE_GENERATION_PROMPT.format(
            max_length=TITLE_MAX_LENGTH,
            user_input=user_input[:500],
            ai_response=ai_response[:500],
        )

        llm_model = get_llm_model("rewrite_query")
        client = create_async_client(llm_model=llm_model)

        messages = [
            {"role": "system", "content": "You generate short conversation titles."},
            {"role": "user", "content": prompt_text},
        ]
        model_args = prepare_model_args(
            messages, False, False, None, None, "text", llm_model
        )
        # Override max_tokens for a very short response
        model_args["max_tokens"] = 30

        response = await client.chat.completions.create(**model_args)
        title = response.choices[0].message.content.strip().strip('"\'')

        # Enforce length limit
        if len(title) > TITLE_MAX_LENGTH:
            title = title[:TITLE_MAX_LENGTH].rsplit(" ", 1)[0]

        return title or user_input[:TITLE_MAX_LENGTH]

    except Exception as e:
        logger.warning("Title generation failed, using fallback: %s", e)
        return user_input[:TITLE_MAX_LENGTH]
