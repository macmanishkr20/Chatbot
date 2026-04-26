from collections import defaultdict

from langchain_core.messages import AIMessage

from graph.state import RAGState
from config import AMBIGUITY_SCORE_RATIO, BUSINESS_EXCEPTION_DETAILS, TOP_K
from services.search_client import SearchService


def _group_by_function(results: list) -> tuple[dict[str, list], dict[str, float]]:
    groups: dict[str, list] = defaultdict(list)
    scores: dict[str, float] = defaultdict(float)
    for r in results:
        fn = r.get("function") or "unknown"
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
    rewritten_query = state.get("rewritten_query")
    embedded_query = state.get("embedded_query")

    if not rewritten_query or not embedded_query:
        return {
            "events": [],
            "error_info": {"error_code": "NO_QUERY", "text": "No query to search."},
        }

    base_filter = rewritten_query.get("filter") or None

    user_functions = state.get("function", [])
    if user_functions:
        fn_filter = " or ".join(f"function eq '{f}'" for f in user_functions)
        base_filter = f"({base_filter}) and ({fn_filter})" if base_filter else fn_filter

    def _with_content_type(filter_expr: str | None, content_type: str) -> str:
        ct_filter = f"content_type eq '{content_type}'"
        return f"({filter_expr}) and ({ct_filter})" if filter_expr else ct_filter

    requested_ct = (state.get("content_type") or "qna_pair").strip() or "qna_pair"
    fallback_chain = [requested_ct]
    if requested_ct == "qna_pair":
        fallback_chain.append("document")

    search_service = SearchService()
    all_results: list = []
    for ct in fallback_chain:
        odata_filter = _with_content_type(base_filter, ct)
        all_results = await search_service.unified_search(
            rewritten_query, embedded_query, odata_filter=odata_filter
        )
        if all_results:
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
            ranked_fns = sorted(function_scores, key=function_scores.get, reverse=True)
            ambiguity_message = (
                "This query exists under multiple functions: "
                + ", ".join(ranked_fns)
                + ". Please specify one."
            )
            return {
                "messages": [AIMessage(content=ambiguity_message)],
                "events": [],
                "functions_found": ranked_fns,
                "is_ambiguous": True,
                "pending_ambiguous_query": {
                    "rewritten_query": state.get("rewritten_query"),
                    "user_input": state.get("user_input", ""),
                },
                "response": {
                    "message": ambiguity_message,
                    "intent": "CASUAL",
                },
            }

    return {
        "events": _strip_internal_fields(curated),
        "functions_found": functions_found,
        "is_ambiguous": False,
    }
