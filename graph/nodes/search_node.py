import asyncio
from collections import defaultdict
import logging

from graph.state import RAGState
from services.telemetry import get_tracer_span
from config import (
    AMBIGUITY_SCORE_RATIO,
    AZURE_OPENAI_EMBED_API_KEY,
    AZURE_OPENAI_EMBED_ENDPOINT,
    BUSINESS_EXCEPTION_DETAILS,
    TOP_K,
)
from prompts._functions import CHIP_TO_SEARCH
from services.openai_client import (
    create_sync_client,
    get_embedding_model,
    retry_with_embedding_backoff,
)
from services.search_client import SearchService

logger = logging.getLogger(__name__)


# ── Embedding ──────────────────────────────────────────────────────────────


@retry_with_embedding_backoff()
def _generate_embeddings(text: str, client, embedding_model: str) -> list:
    """Generate embeddings using the sync Azure OpenAI client."""
    return client.embeddings.create(input=[text], model=embedding_model).data[0].embedding


async def _embed_query(query_text: str) -> list | None:
    """Generate vector embeddings for a query string."""
    if not query_text:
        return None

    embedding_model = get_embedding_model("embedding")
    client = create_sync_client(
        azure_endpoint=AZURE_OPENAI_EMBED_ENDPOINT,
        azure_key=AZURE_OPENAI_EMBED_API_KEY,
        llm_model=embedding_model,
    )
    return await asyncio.to_thread(
        _generate_embeddings, query_text, client, embedding_model=embedding_model
    )


# ── Helpers ────────────────────────────────────────────────────────────────


def _group_by_function(results: list) -> tuple[dict[str, list], dict[str, float]]:
    groups: dict[str, list] = defaultdict(list)
    scores: dict[str, float] = defaultdict(float)
    for r in results:
        fn = (r.get("function") or "unknown").strip()
        groups[fn].append(r)
        scores[fn] += r.get("@search.reranker_score", 0.0)
    return dict(groups), dict(scores)


def _strip_internal_fields(results: list) -> list:
    cleaned = []
    for r in results:
        cleaned.append({
            "file_name": r.get("file_name", ""),
            "page_number": r.get("page_number", ""),
            "content": r.get("content", ""),
            "source_url": r.get("source_url", ""),
            "function": r.get("function", ""),
            "sub_function": r.get("sub_function", ""),
        })
    return cleaned


async def search_node(state: RAGState) -> dict:
    """LangGraph search node — embeds query then runs unified waterfall search."""
    with get_tracer_span("search_node"):
        rewritten_query = state.get("rewritten_query")

        if not rewritten_query or not rewritten_query.get("query"):
            return {
                "events": [],
                "error_info": {"error_code": "NO_QUERY", "text": "No query to search."},
            }

        # ── Embed the query (previously a separate node) ──
        embedded_query = await _embed_query(rewritten_query["query"])
        if not embedded_query:
            return {
                "events": [],
                "error_info": {"error_code": "EMBED_FAILED", "text": "Failed to embed query."},
            }

        # ── Build base filter (date/function filters, NOT content_type) ──
        base_filter = rewritten_query.get("filter") or None

        user_functions = state.get("function", [])
        if user_functions:
            search_fns = [CHIP_TO_SEARCH.get(f, f) for f in user_functions]
            fn_filter = " or ".join(f"function eq '{f}'" for f in search_fns)
            base_filter = f"({base_filter}) and ({fn_filter})" if base_filter else fn_filter

        requested_ct = (state.get("content_type") or "qa_pair").strip() or "qa_pair"

        # ── Single call handles the entire waterfall (Levels 1-4) ──
        search_service = SearchService()
        all_results = await search_service.search_with_retry(
            rewritten_query,
            embedded_query,
            base_filter=base_filter,
            content_type=requested_ct,
        )

        if not all_results:
            empty_detail = BUSINESS_EXCEPTION_DETAILS.get("empty_events", {})
            return {
                "events": [],
                "functions_found": [],
                "is_ambiguous": False,
                "error_info": {
                    "error_code": empty_detail.get("error_code", "NO_EVENTS"),
                    "text": empty_detail.get("text", "No relevant events found."),
                },
            }

        # ── Ambiguity handling: group by function ──
        function_groups, function_scores = _group_by_function(all_results)
        functions_found = list(function_groups.keys())

        if len(functions_found) == 1:
            curated = all_results[:TOP_K]
        else:
            total_score = sum(function_scores.values())
            top_fn = max(function_scores, key=function_scores.get)
            top_ratio = function_scores[top_fn] / total_score if total_score > 0 else 0

            if top_ratio >= AMBIGUITY_SCORE_RATIO:
                curated = function_groups[top_fn][:TOP_K]
                functions_found = [top_fn]
            else:
                curated = all_results[:TOP_K]
                ranked_fns = sorted(function_scores, key=function_scores.get, reverse=True)
                functions_found = ranked_fns

        return {
            "events": _strip_internal_fields(curated),
            "functions_found": functions_found,
            "is_ambiguous": False,
        }
