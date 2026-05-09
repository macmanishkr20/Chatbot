import asyncio
import hashlib
import time
from collections import defaultdict
import logging

from graph.state import RAGState
from services.telemetry import get_tracer_span
from config import (
    AMBIGUITY_SCORE_RATIO,
    AZURE_OPENAI_EMBED_API_KEY,
    AZURE_OPENAI_EMBED_ENDPOINT,
    BUSINESS_EXCEPTION_DETAILS,
    DUAL_CONTENT_SEARCH_ENABLED,
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


# ── Process-local embedding cache (avoid re-embed on doc-fallback retry) ──
# Keyed by hash of query text; entries auto-expire to bound memory.
# Not persisted to checkpoint state — that would bloat every checkpoint by
# ~6KB per turn for a 1.5K-dim float vector.
_EMBED_CACHE_TTL_SECONDS = 120
_embed_cache: dict[str, tuple[float, list]] = {}


def _embed_cache_key(query_text: str) -> str:
    return hashlib.sha1(query_text.encode("utf-8")).hexdigest()


def _embed_cache_get(key: str) -> list | None:
    entry = _embed_cache.get(key)
    if not entry:
        return None
    expiry, vec = entry
    if expiry <= time.time():
        _embed_cache.pop(key, None)
        return None
    return vec


def _embed_cache_put(key: str, vec: list) -> None:
    # Drop expired entries opportunistically to bound size
    now = time.time()
    if len(_embed_cache) > 256:
        for k in [k for k, (exp, _) in _embed_cache.items() if exp <= now]:
            _embed_cache.pop(k, None)
    _embed_cache[key] = (now + _EMBED_CACHE_TTL_SECONDS, vec)


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
        entry = {
            "file_name": r.get("file_name", ""),
            "page_number": r.get("page_number", ""),
            "content": r.get("content", ""),
            "source_url": r.get("source_url", ""),
            "function": r.get("function", ""),
            "sub_function": r.get("sub_function", ""),
        }
        if r.get("_source_type"):
            entry["_source_type"] = r["_source_type"]
        cleaned.append(entry)
    return cleaned


def _with_content_type(filter_expr: str | None, content_type: str) -> str:
    """Append a content_type eq clause to an existing OData filter."""
    ct_filter = f"content_type eq '{content_type}'"
    return f"({filter_expr}) and ({ct_filter})" if filter_expr else ct_filter


async def search_node(state: RAGState) -> dict:
    """LangGraph search node — embeds query then runs unified waterfall search."""
    with get_tracer_span("search_node"):
        rewritten_query = state.get("rewritten_query")

        if not rewritten_query or not rewritten_query.get("query"):
            return {
                "events": [],
                "error_info": {"error_code": "NO_QUERY", "text": "No query to search."},
            }

        # ── Embed the query (process-local cache avoids re-embed on retry) ──
        cache_key = _embed_cache_key(rewritten_query["query"])
        embedded_query = _embed_cache_get(cache_key)
        if not embedded_query:
            embedded_query = await _embed_query(rewritten_query["query"])
            if not embedded_query:
                return {
                    "events": [],
                    "error_info": {"error_code": "EMBED_FAILED", "text": "Failed to embed query."},
                }
            _embed_cache_put(cache_key, embedded_query)

        # ── Build base filter (date/function filters, NOT content_type) ──
        base_filter = rewritten_query.get("filter") or None

        user_functions = state.get("function", [])
        if user_functions:
            search_fns = [CHIP_TO_SEARCH.get(f, f) for f in user_functions]
            fn_filter = " or ".join(f"function eq '{f}'" for f in search_fns)
            base_filter = f"({base_filter}) and ({fn_filter})" if base_filter else fn_filter

        # ── Content-type search: dual parallel or sequential fallback ──
        search_service = SearchService()
        all_results: list = []

        if DUAL_CONTENT_SEARCH_ENABLED:
            # Parallel search both content types simultaneously
            doc_filter = _with_content_type(base_filter, "document")
            qa_filter = _with_content_type(base_filter, "qa_pair")

            doc_results, qa_results = await asyncio.gather(
                search_service.unified_search(rewritten_query, embedded_query, odata_filter=doc_filter),
                search_service.unified_search(rewritten_query, embedded_query, odata_filter=qa_filter),
            )

            for r in doc_results:
                r["_source_type"] = "document"
            for r in qa_results:
                r["_source_type"] = "qa_pair"

            # Merge by relevance score (descending) so the most relevant
            # results from either content type appear first.
            combined = doc_results + qa_results
            combined.sort(
                key=lambda r: r.get("@search.reranker_score", 0.0),
                reverse=True,
            )
            all_results = combined
        else:
            # Sequential fallback: document → qa_pair
            requested_ct = (state.get("content_type") or "document").strip() or "document"
            fallback_chain = [requested_ct]
            if requested_ct == "document":
                fallback_chain.append("qa_pair")

            for ct in fallback_chain:
                odata_filter = _with_content_type(base_filter, ct)
                all_results = await search_service.unified_search(
                    rewritten_query, embedded_query, odata_filter=odata_filter
                )
                if all_results:
                    # Tag with provenance (same field the dual-search branch
                    # sets) so downstream citation rendering can format
                    # type-appropriately even in sequential mode.
                    for r in all_results:
                        r.setdefault("_source_type", ct)
                    break

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
            "needs_multi_search": len(functions_found) > 1,
        }
