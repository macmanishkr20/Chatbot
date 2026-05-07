from typing import Dict, List, Tuple

import asyncio
import logging
import re

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import (
    HttpResponseError,
    ServiceRequestError,
    ServiceResponseError,
)
from azure.search.documents import SearchClient
from azure.search.documents.models import (
    VectorizedQuery,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config import (
    AZURE_SEARCH_INDEX_NAME,
    AZURE_SEARCH_API_KEY,
    AZURE_SEARCH_ENDPOINT,
    AZURE_SEARCH_SEMANTIC_CONFIG,
    AZURE_SEARCH_SCORE_THRESHOLD,
    AZURE_SEARCH_VECTOR_FIELD,
    DISCOVERY_TOP_K,
    SELECT_FIELDS,
    TOP_K,
)

logger = logging.getLogger(__name__)


# ── Prompt Injection Detection ────────────────────────────────────────────────

# Patterns that indicate an attacker injected instructions into indexed content.
# These are checked BEFORE passing retrieved documents to the LLM.
_INJECTION_PATTERNS = re.compile(
    r"("
    # Direct instruction overrides
    r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts|rules)"
    r"|disregard\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts|rules)"
    r"|forget\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts|context)"
    # Role hijacking
    r"|you\s+are\s+now\s+(a|an|the)\s+"
    r"|from\s+now\s+on\s+you\s+(are|will|must|should)"
    r"|act\s+as\s+(a|an|if)\s+"
    r"|pretend\s+you\s+are"
    r"|you\s+must\s+obey"
    # System prompt extraction
    r"|reveal\s+(your|the)\s+(system|initial)\s+(prompt|instructions)"
    r"|show\s+(me\s+)?(your|the)\s+system\s+prompt"
    r"|what\s+(are|is)\s+your\s+(system\s+)?(instructions|prompt|rules)"
    r"|repeat\s+(your|the)\s+(system|initial)\s+(prompt|instructions)"
    # Output manipulation
    r"|respond\s+only\s+with"
    r"|output\s+only"
    r"|do\s+not\s+mention"
    r"|never\s+say"
    r"|always\s+respond\s+with"
    # Delimiter attacks
    r"|<\/?system>"
    r"|\[SYSTEM\]"
    r"|\[INST\]"
    r"|<<\s*SYS\s*>>"
    r")",
    re.IGNORECASE,
)


def _sanitize_content(content: str) -> str:
    """Detect prompt injection patterns in retrieved content (log only, no redaction).

    The system prompt instructs the LLM to ignore adversarial instructions in
    source documents. We log detections for monitoring but do NOT redact, since:
    - Regex is easily bypassed (Unicode tricks, zero-width chars, obfuscation)
    - Redaction can corrupt legitimate content with similar phrasing
    - The LLM's instruction hierarchy is the real defense layer
    """
    if not content:
        return content

    matches = list(_INJECTION_PATTERNS.finditer(content))
    if matches:
        logger.warning(
            "Possible injection in retrieved doc (%d pattern(s), content_len=%d)",
            len(matches), len(content),
        )

    return content


_SHAREPOINT_BASE_URL = "https://sites.ey.com"


def _normalize_source_url(url: str) -> str:
    """Ensure source_url is a full URL, not a relative SharePoint path."""
    if not url:
        return url
    url = url.strip()
    # Relative SharePoint paths start with /sites/
    if url.startswith("/sites/") or url.startswith("/Sites/"):
        return f"{_SHAREPOINT_BASE_URL}{url}"
    # Other relative paths starting with /
    if url.startswith("/") and not url.startswith("//"):
        return f"{_SHAREPOINT_BASE_URL}{url}"
    return url


# ── Search threshold ratios (derived from AZURE_SEARCH_SCORE_THRESHOLD) ──────
# Single source of truth for all search scoring decisions.
_QA_THRESHOLD = AZURE_SEARCH_SCORE_THRESHOLD          # Full threshold for QA pairs
_DOC_THRESHOLD = AZURE_SEARCH_SCORE_THRESHOLD * 0.4   # Relaxed for documents (~0.6)
_FALLBACK_THRESHOLD = AZURE_SEARCH_SCORE_THRESHOLD * 0.2  # Broad retrieval (~0.3)


def strip_function_filter(filter_expr: str | None) -> str | None:
    """Remove function-specific OData filter clauses to broaden search.

    Handles patterns like:
      - function eq 'TME'
      - (function eq 'TME') and (...)
      - search.in(function, 'TME,BMC', ',')
      - (...) and (function eq 'TME' or function eq 'BMC')
    """
    if not filter_expr:
        return None

    # Remove search.in(function, ...) clauses
    cleaned = re.sub(r"search\.in\(function,\s*'[^']*',\s*','\)", "", filter_expr)
    # Remove function eq '...' clauses
    cleaned = re.sub(r"function\s+eq\s+'[^']*'", "", cleaned)
    # Clean up leftover logical operators and parentheses
    cleaned = re.sub(r"\(\s*\)", "", cleaned)  # empty parens
    cleaned = re.sub(r"\s+and\s+and\s+", " and ", cleaned)  # double and
    cleaned = re.sub(r"^\s*and\s+", "", cleaned)  # leading and
    cleaned = re.sub(r"\s+and\s*$", "", cleaned)  # trailing and
    cleaned = re.sub(r"^\s*or\s+", "", cleaned)   # leading or
    cleaned = re.sub(r"\s+or\s*$", "", cleaned)   # trailing or
    cleaned = re.sub(r"\(\s*and\s*\)", "", cleaned)
    cleaned = re.sub(r"\(\s*or\s*\)", "", cleaned)
    cleaned = cleaned.strip()

    if not cleaned or cleaned in ("()", "( )", "and", "or"):
        return None

    return cleaned


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
        retry=retry_if_exception_type(
            (HttpResponseError, ServiceRequestError, ServiceResponseError)
        ),
    )
    async def _safe_search(self, client, **kwargs):
        # The Azure SDK's SearchClient is synchronous and blocks while iterating
        # results. Materialize the iterator on a worker thread to avoid blocking
        # the asyncio event loop (otherwise parallel_search_node serializes).
        def _run() -> list:
            return list(client.search(**kwargs))

        return await asyncio.to_thread(_run)

    async def unified_search(
        self, query: dict, embedded_query: list, odata_filter: str | None = None
    ) -> List[Dict]:
        client = self._get_client()

        # Use a larger vector search pool when a filter is applied — filters
        # narrow the candidate set, so we need more neighbors to compensate.
        k_neighbors = DISCOVERY_TOP_K * 5 if odata_filter else DISCOVERY_TOP_K

        vector_query = VectorizedQuery(
            vector=embedded_query,
            k_nearest_neighbors=k_neighbors,
            fields=AZURE_SEARCH_VECTOR_FIELD,
        )

        # Always include function/sub_function/content_type so callers can
        # render type-appropriate citations (qa_pair → URL only,
        # document → file_name + page_number + URL).
        select_fields = list({
            *(f.strip() for f in SELECT_FIELDS.split(",") if f.strip()),
            "function", "sub_function", "content_type",
        })

        search_kwargs = dict(
            search_text=query.get("query", ""),
            vector_queries=[vector_query],
            select=select_fields,
            top=DISCOVERY_TOP_K,
        )
        if AZURE_SEARCH_SEMANTIC_CONFIG:
            search_kwargs.update(
                query_type="semantic",
                semantic_configuration_name=AZURE_SEARCH_SEMANTIC_CONFIG,
                query_caption="extractive",
                query_answer="extractive",
            )
        if odata_filter:
            search_kwargs["filter"] = odata_filter

        results = await self._safe_search(client, **search_kwargs)

        enriched = []
        for r in results:
            # Semantic reranker score (0–4 scale) takes priority.
            # Falls back to hybrid search score (0–1 scale) when semantic
            # ranker is not configured. The score is normalized to 0–4 scale
            # so a single threshold works consistently across both modes.
            reranker_score = r.get("@search.reranker_score")
            if reranker_score is not None:
                score = float(reranker_score)
            else:
                # Hybrid score (BM25 + vector) is roughly 0–1 but unbounded;
                # rescale to 0–4 and clamp so BM25 outliers cannot inflate
                # past the reranker's natural ceiling.
                hybrid_score = float(r.get("@search.score", 0.0))
                score = max(0.0, min(hybrid_score, 1.0)) * 4.0

            enriched.append({
                "file_name": r.get("file_name", ""),
                "page_number": r.get("page_number", ""),
                "content": _sanitize_content(r.get("content", "")),
                "source_url": _normalize_source_url(r.get("source_url", "")),
                "function": r.get("function", ""),
                "sub_function": r.get("sub_function", ""),
                # Preserve content_type so the caller can choose a
                # type-appropriate citation format (qa_pair vs document).
                # Default to "qa_pair" only when missing — that is the
                # historic behaviour and keeps citations URL-only when the
                # index lacks the field.
                "content_type": (r.get("content_type") or "qa_pair").strip() or "qa_pair",
                "@search.reranker_score": score,
            })

        # Drop documents whose content was entirely redacted (injection-only docs)
        enriched = [doc for doc in enriched if doc["content"].strip()]

        return enriched

    async def search_with_retry(
        self,
        query: dict,
        embedded_query: list,
        base_filter: str | None = None,
        content_type: str = "document",  # accepted for back-compat; not used as a filter
        top_k: int = DISCOVERY_TOP_K,
        skip_last_resort: bool = False,
    ) -> List[Dict]:
        """Sequential waterfall: document → qa_pair → no filter.

        Each level runs a single search call and returns its results as
        soon as any pass the level's threshold. The ``content_type``
        parameter is retained in the signature for back-compat but is
        ignored — the level order is fixed.

        Levels:
          L1: content_type='document' + base_filter   (threshold: relaxed)
              Documents are the primary corpus.
          L2: content_type='qa_pair'  + base_filter   (threshold: full)
              Curated Q&A backstop when documents miss.
          L3: no filter at all                        (threshold: very relaxed)
              Last resort — skipped when skip_last_resort=True.

        Each level uses its appropriate threshold so a weak match in one
        type cannot pre-empt a strong match in another that hasn't been
        checked yet.

        Returns results sorted by raw reranker score, capped at top_k.
        """
        del content_type  # intentional — ordering is fixed by the level chain

        sorted_by_score = lambda rs: sorted(  # noqa: E731
            rs, key=lambda r: r.get("@search.reranker_score", 0.0), reverse=True
        )

        # ── Level 1: documents + base_filter ──
        ct_filter = "content_type eq 'document'"
        odata_filter = f"({base_filter}) and ({ct_filter})" if base_filter else ct_filter
        raw = await self.unified_search(query, embedded_query, odata_filter=odata_filter)
        qualified = [r for r in raw if r.get("@search.reranker_score", 0) >= _DOC_THRESHOLD]
        if qualified:
            logger.info(
                "search_with_retry: L1 document found=%d (threshold=%.2f)",
                len(qualified), _DOC_THRESHOLD,
            )
            return sorted_by_score(qualified)[:top_k]

        # ── Level 2: qa_pair + base_filter ──
        ct_filter = "content_type eq 'qa_pair'"
        odata_filter = f"({base_filter}) and ({ct_filter})" if base_filter else ct_filter
        raw = await self.unified_search(query, embedded_query, odata_filter=odata_filter)
        qualified = [r for r in raw if r.get("@search.reranker_score", 0) >= _QA_THRESHOLD]
        if qualified:
            logger.info(
                "search_with_retry: L2 qa_pair found=%d (threshold=%.2f)",
                len(qualified), _QA_THRESHOLD,
            )
            return sorted_by_score(qualified)[:top_k]

        # ── Level 3: no filter at all (last resort) ──
        if skip_last_resort:
            return []

        raw = await self.unified_search(query, embedded_query, odata_filter=None)
        qualified = [r for r in raw if r.get("@search.reranker_score", 0) >= _FALLBACK_THRESHOLD]
        if qualified:
            logger.info(
                "search_with_retry: L3 no-filter found=%d (threshold=%.2f)",
                len(qualified), _FALLBACK_THRESHOLD,
            )
            return sorted_by_score(qualified)[:top_k]

        return []
