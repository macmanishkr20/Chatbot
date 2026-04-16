"""
Embed node — generate vector embeddings for the rewritten query.
"""
import asyncio

from config import AZURE_OPENAI_EMBED_API_KEY, AZURE_OPENAI_EMBED_ENDPOINT
from graph.state import RAGState
from services.openai_client import (
    create_sync_client,
    get_embedding_model,
    retry_with_embedding_backoff,
)


@retry_with_embedding_backoff()
def _generate_embeddings(text: str, client, embedding_model: str) -> list:
    """Generate embeddings using the sync Azure OpenAI client."""
    return client.embeddings.create(input=[text], model=embedding_model).data[0].embedding


async def embed_node(state: RAGState) -> dict:
    """Generate vector embeddings for the rewritten query text."""
    rewritten_query = state.get("rewritten_query")
    if not rewritten_query or not rewritten_query.get("query"):
        return {"embedded_query": None}

    embedding_model = get_embedding_model("embedding")
    client = create_sync_client(
        azure_endpoint=AZURE_OPENAI_EMBED_ENDPOINT,
        azure_key=AZURE_OPENAI_EMBED_API_KEY,
        llm_model=embedding_model,
    )

    embedded_query = await asyncio.to_thread(
        _generate_embeddings, rewritten_query["query"], client, embedding_model=embedding_model
    )

    return {"embedded_query": embedded_query}

