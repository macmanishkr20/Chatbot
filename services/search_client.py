from typing import Dict, List, Tuple

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import (
    QueryAnswerType,
    QueryCaptionType,
    QueryType,
    VectorizedQuery,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config import (
    AZURE_SEARCH_INDEX_NAME,
    AZURE_SEARCH_API_KEY,
    AZURE_SEARCH_ENDPOINT,
    AZURE_SEARCH_SEMANTIC_CONFIG,
    AZURE_SEARCH_VECTOR_FIELD,
    DISCOVERY_TOP_K,
    SELECT_FIELDS,
    TOP_K,
)


class SearchService:

    def _get_client(self) -> SearchClient:
        return SearchClient(
            AZURE_SEARCH_ENDPOINT,
            AZURE_SEARCH_INDEX_NAME,
            credential=AzureKeyCredential(AZURE_SEARCH_API_KEY),
        )

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5),
        retry=retry_if_exception_type(Exception),
    )
    async def _safe_search(self, client, **kwargs):
        return client.search(**kwargs)

    async def unified_search(
        self, query: dict, embedded_query: list, odata_filter: str | None = None
    ) -> List[Dict]:
        client = self._get_client()

        vector_query = VectorizedQuery(
            vector=embedded_query,
            k_nearest_neighbors=DISCOVERY_TOP_K,
            fields=AZURE_SEARCH_VECTOR_FIELD,
        )

        select_fields = [f.strip() for f in SELECT_FIELDS.split(",")] + ["function", "sub_function"]

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

        results = await self._safe_search(client, **search_kwargs)

        enriched = []
        for r in results:
            score = r.get("@search.reranker_score") or r.get("@search.score", 0.0)
            enriched.append({
                "file_name": r.get("file_name", ""),
                "page_number": r.get("page_number", ""),
                "content": r.get("content", ""),
                "source_url": r.get("source_url", ""),
                "function": r.get("function", ""),
                "sub_function": r.get("sub_function", ""),
                "@search.reranker_score": score,
            })

        return enriched

    async def detect_ambiguity(
        self, query: dict, embedded_query: list
    ) -> Tuple[List[Dict], List[str]]:
        client = self._get_client()

        vector_query = VectorizedQuery(
            vector=embedded_query,
            k_nearest_neighbors=TOP_K,
            fields=AZURE_SEARCH_VECTOR_FIELD,
        )
        select_fields = [f.strip() for f in SELECT_FIELDS.split(",")] + ["function"]

        results = await self._safe_search(
            client,
            search_text=query.get("query", ""),
            vector_queries=[vector_query],
            select=select_fields,
            top=TOP_K,
        )

        functions_found = set()
        chunks = []
        for r in results:
            fn = r.get("function")
            if fn:
                functions_found.add(fn)
            chunks.append(dict(r))

        return chunks, list(functions_found)

    async def retrieve(
        self, query: dict, embedded_query: list, function: str | None = None
    ) -> List[Dict]:
        if not query:
            return []

        client = self._get_client()

        vector_query = VectorizedQuery(
            vector=embedded_query,
            k=TOP_K,
            fields=AZURE_SEARCH_VECTOR_FIELD,
        )

        filter_expr = None
        if function:
            filter_expr = f"function eq '{function}'"

        select_fields = [f.strip() for f in SELECT_FIELDS.split(",")]

        results = await self._safe_search(
            client,
            search_text=query.get("query", ""),
            vector_queries=[vector_query],
            select=select_fields,
            query_type=QueryType.SEMANTIC,
            semantic_configuration_name="my-semantic-config",
            query_caption=QueryCaptionType.EXTRACTIVE,
            query_answer=QueryAnswerType.EXTRACTIVE,
            top=TOP_K,
            filter=filter_expr,
        )

        return [
            {
                "file_name": r.get("file_name", ""),
                "page_number": r.get("page_number", ""),
                "content": r.get("content", ""),
                "source_url": r.get("source_url", ""),
                "function": r.get("function", ""),
                "sub_function": r.get("sub_function", ""),
            }
            for r in results
        ]
