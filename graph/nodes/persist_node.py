"""
Persist node — save conversation record and AI content to Azure SQL.

Pure I/O node: writes structured records the frontend needs.
No LLM calls — title generation is fire-and-forget (background task).

Conversation *context* for the LLM is handled by the checkpointer
(short-term) and Store (long-term).
"""
import asyncio
import json
import logging

from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)

from graph.state import RAGState
from models.chat_models import (
    ApplicationChatQuery,
    BusinessExceptionResponse,
    InputType,
)
from graph.nodes.title_node import generate_title
from services.sql_client import SQLChatClient
from services.telemetry import get_tracer_span


# ───────────────── Helpers ─────────────────


def _build_app_query(state: RAGState) -> ApplicationChatQuery:
    """Build ApplicationChatQuery from graph state fields."""
    return ApplicationChatQuery(
        input_type=InputType(state.get("input_type", "ask")),
        user_input=state.get("user_input", ""),
        is_free_form=state.get("is_free_form", False),
        user_id=state.get("user_id", ""),
        chat_id=state.get("chat_id"),
        chat_session_id=state.get("chat_session_id"),
        message_id=state.get("message_id"),
        function=state.get("function", []),
        sub_function=state.get("sub_function", []),
        source_url=state.get("source_url", []),
        start_date=state.get("start_date", ""),
        end_date=state.get("end_date", ""),
    )


# ───────────────── AI Content Persistence ─────────────────


async def _save_ai_content(
    ai_content_raw: str,
    app_query: ApplicationChatQuery,
    scc: SQLChatClient,
):
    """Parse AI content and save to SQL. Handles both free-form and structured."""
    if app_query.is_free_form:
        app_query.ai_content_free_form = ai_content_raw
        await scc.save_ai_content_free_form(app_query)
    else:
        cleaned = (
            ai_content_raw
            .replace("@#TOOLS#@", "")
            .replace("json_object", "")
        )
        try:
            ai_content_json = json.loads(cleaned)
            ai_content_data = ai_content_json.get("data", ai_content_json)
            if isinstance(ai_content_data, list):
                app_query.ai_content = ai_content_data
            else:
                app_query.ai_content = [ai_content_data] if ai_content_data else []
        except json.JSONDecodeError:
            app_query.ai_content = [{"raw": cleaned}]

    # Store full prompt text directly — no LLM summarization needed
    prompt_text = app_query.prompt or app_query.user_input
    app_query.summurized_prompt = prompt_text[:2000]  # Cap at reasonable DB limit

    await scc.save_ai_content(app_query)


# ───────────────── Background Title Generation ─────────────────


async def _generate_title_background(
    user_input: str, ai_content: str, chat_id: str, user_id: str
):
    """Fire-and-forget title generation — runs after response is sent."""
    try:
        title = await generate_title(user_input, ai_content)
        scc = SQLChatClient()
        await scc.connect()
        await scc.ensure()
        await scc.upsert_chat({
            "id": chat_id,
            "title": title,
            "userId": user_id,
        })
        logger.info("Background title generated: %s", title)
    except Exception as e:
        logger.warning("Background title generation failed: %s", e)


# ───────────────── Node ─────────────────


async def persist_node(state: RAGState) -> dict:
    """Create conversation/message records in SQL and save AI content.

    Pure I/O — no LLM calls in the critical path.
    Title generation is fire-and-forget (background asyncio task).
    """
    with get_tracer_span("persist_node"):
        is_new_conversation = state.get("chat_id") is None

        app_query = _build_app_query(state)

        rewritten_query = state.get("rewritten_query")
        prompt_used = state.get("prompt_used")
        error_info = state.get("error_info")
        events = state.get("events", [])

        if rewritten_query:
            app_query.rewritten_query = rewritten_query
        if error_info:
            app_query.error_info = BusinessExceptionResponse(**error_info)
        if prompt_used:
            app_query.prompt = prompt_used

        # Connect to SQL
        try:
            scc = SQLChatClient()
            await scc.connect()
            await scc.ensure()
        except Exception as e:
            logger.error("persist_node: SQL connection failed: %s", e, exc_info=True)
            return {}

        # Create conversation + message row
        try:
            new_message, _ = await scc.message_list_update(app_query, [])

            if new_message:
                app_query.id = new_message.id
                app_query.chat_id = new_message.chat_id
                app_query.message_id = new_message.message_id
        except Exception as e:
            logger.error("persist_node: message_list_update failed: %s", e, exc_info=True)
            return {}

        # Error with no events — short-circuit
        if error_info and not events:
            error_text = error_info.get("text", "No relevant events found.")
            return {
                "chat_id": app_query.chat_id,
                "message_id": app_query.message_id,
                "messages": [AIMessage(content=error_text)],
                "response": {"error": error_info},
            }

        # Ambiguity — save the disambiguation message to SQL
        if state.get("is_ambiguous") and not state.get("ai_content"):
            ambiguity_response = state.get("response") or {}
            ambiguity_text = ambiguity_response.get("message", "")
            if ambiguity_text:
                app_query.ai_content_free_form = ambiguity_text
                app_query.is_free_form = True
                app_query.summurized_prompt = app_query.user_input[:2000]
                await scc.save_ai_content_free_form(app_query)
                await scc.save_ai_content(app_query)
            return {
                "chat_id": app_query.chat_id,
                "message_id": app_query.message_id,
                "ai_content": ambiguity_text,
                "messages": [AIMessage(content=ambiguity_text)],
                "response": ambiguity_response,
            }

        # Save AI content to SQL
        ai_content = state.get("ai_content") or ""
        if ai_content:
            await _save_ai_content(ai_content, app_query, scc)

        # ── Fire-and-forget title generation for new conversations ──
        conversation_title = None
        if is_new_conversation and ai_content:
            asyncio.create_task(
                _generate_title_background(
                    state.get("user_input", ""),
                    ai_content,
                    app_query.chat_id,
                    app_query.user_id,
                )
            )

        return {
            "chat_id": app_query.chat_id,
            "message_id": app_query.message_id,
            "ai_content": ai_content,
            "conversation_title": conversation_title,
            "response": {
                "chat_id": app_query.chat_id,
                "message_id": app_query.message_id,
            },
        }
