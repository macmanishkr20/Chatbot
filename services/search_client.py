"""
Azure AI Search client.

Search strategy: Hybrid (BM25 keyword + Vector exact-KNN) + Semantic Reranker.

  BM25 keyword match ──┐
                        ├─→ RRF merge ──→ Semantic Reranker ──→ @search.reranker_score (0–4)
  Vector exact-KNN   ──┘

Results below AZURE_SEARCH_SCORE_THRESHOLD are dropped so only
high-confidence chunks reach the LLM.
"""

from typing import Dict, List

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.aio import SearchClient as AsyncSearchClient
from azure.search.documents.models import (
    QueryAnswerType,
    QueryCaptionType,
    QueryType,
    VectorizedQuery,
)
from azure.core.exceptions import (
    HttpResponseError,
    ServiceRequestError,
    ServiceResponseError,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config import (
    AZURE_SEARCH_API_KEY,
    AZURE_SEARCH_ENDPOINT,
    AZURE_SEARCH_INDEX_NAME,
    AZURE_SEARCH_SCORE_THRESHOLD,
    AZURE_SEARCH_SEMANTIC_CONFIG,
    AZURE_SEARCH_VECTOR_FIELD,
    DISCOVERY_TOP_K,
    SELECT_FIELDS,
)


class SearchService:

    def _get_client(self) -> AsyncSearchClient:
        return AsyncSearchClient(
            AZURE_SEARCH_ENDPOINT,
            AZURE_SEARCH_INDEX_NAME,
            credential=AzureKeyCredential(AZURE_SEARCH_API_KEY),
        )

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5),
        retry=retry_if_exception_type((HttpResponseError, ServiceRequestError, ServiceResponseError)),
    )
    async def _safe_search(self, client: AsyncSearchClient, **kwargs) -> list:
        results = []
        async with client:
            async for r in await client.search(**kwargs):
                results.append(r)
        return results

    async def unified_search(
        self, query: dict, embedded_query: list, odata_filter: str | None = None
    ) -> List[Dict]:
        """
        Hybrid + Semantic search.

        Uses exact KNN (exhaustive=True) so every vector comparison is
        computed — no approximate HNSW shortcuts — giving the highest-
        precision nearest-neighbour results before the semantic reranker
        re-scores them.

        Results below AZURE_SEARCH_SCORE_THRESHOLD (@search.reranker_score
        on a 0–4 scale, or @search.score as fallback) are discarded.
        """
        client = self._get_client()

        vector_query = VectorizedQuery(
            vector=embedded_query,
            k_nearest_neighbors=DISCOVERY_TOP_K,   # fixed: was k= (deprecated)
            fields=AZURE_SEARCH_VECTOR_FIELD,
            exhaustive=True,                        # exact KNN — highest precision
        )

        select_fields = [f.strip() for f in SELECT_FIELDS.split(",")] + [
            "function", "sub_function"
        ]

        search_kwargs = dict(
            search_text=query.get("query", ""),
            vector_queries=[vector_query],
            select=select_fields,
            top=DISCOVERY_TOP_K,
        )

        if AZURE_SEARCH_SEMANTIC_CONFIG:
            search_kwargs.update(
                query_type=QueryType.SEMANTIC,
                semantic_configuration_name=AZURE_SEARCH_SEMANTIC_CONFIG,
                query_caption=QueryCaptionType.EXTRACTIVE,
                query_answer=QueryAnswerType.EXTRACTIVE,
            )

        if odata_filter:
            search_kwargs["filter"] = odata_filter

        raw_results = await self._safe_search(client, **search_kwargs)

        enriched = []
        for r in raw_results:
            # Prefer semantic reranker score (0–4); fall back to BM25/vector score.
            # Use `is not None` — a reranker score of 0.0 is valid, not missing.
            reranker = r.get("@search.reranker_score")
            score = reranker if reranker is not None else r.get("@search.score", 0.0)

            # Drop low-confidence results — keeps only high-relevance chunks
            if score < AZURE_SEARCH_SCORE_THRESHOLD:
                continue

            enriched.append({
                "file_name": r.get("file_name", ""),
                "page_number": r.get("page_number", ""),
                "content": r.get("content", ""),
                "source_url": r.get("source_url", ""),
                "function": r.get("function", ""),
                "sub_function": r.get("sub_function", ""),
                "@search.reranker_score": score,
            })

        # Return sorted by score descending so top results are first
        enriched.sort(key=lambda x: x["@search.reranker_score"], reverse=True)
        return enriched
