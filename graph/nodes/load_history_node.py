"""
Load history node for the simplified RAG flow.
Loads chat history from SQL and prepares ApplicationChatQuery for downstream nodes.
"""
from graph.state import RAGState
from services.telemetry import get_tracer_span
from models.chat_models import ApplicationChatQuery, InputType
from services.sql_client import SQLChatClient


def _build_app_query(state: RAGState) -> ApplicationChatQuery:
    """Build ApplicationChatQuery from graph state."""
    return ApplicationChatQuery(
        input_type=InputType(state["input_type"]),
        user_input=state.get("user_input", ""),
        is_free_form=state.get("is_free_form", False),
        user_id=state.get("user_id", ""),
        chat_id=state.get("chat_id"),
        message_id=state.get("message_id"),
        channel_type=state["channel_type"],
        function=state.get("function", []),
        sub_function=state.get("sub_function", []),
        source_url=state.get("source_url", []),
        start_date=state.get("start_date", ""),
        end_date=state.get("end_date", ""),
    )


async def load_history_node(state: RAGState) -> dict:
    """Load conversation history and attach app query to state."""
    with get_tracer_span("load_history_node"):
        scc = SQLChatClient()
        await scc.connect()
        await scc.ensure()

        app_query = _build_app_query(state)
        history = await scc.message_list(app_query)
        history_dicts = [h.model_dump() for h in history] if history else []

        return {
            "history": history_dicts,
            "application_chat_query": app_query.model_dump(),
        }
