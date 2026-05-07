"""
Retrieval evaluation metrics for MENA Chat RAG pipeline.

Measures:
  - Recall@K: fraction of relevant documents retrieved in top-K
  - Precision@K: fraction of top-K results that are relevant
  - MRR (Mean Reciprocal Rank): how high the first relevant result ranks
  - Function Accuracy: whether the correct MENA function was identified
  - Fallback Rate: how often the system falls through to document content_type

Usage:
    python -m tests.eval.eval_retrieval [--dataset tests/eval/golden_dataset.json]
"""
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from dataclasses import dataclass, field

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config import AZURE_SEARCH_SCORE_THRESHOLD, DISCOVERY_TOP_K, TOP_K
from graph.nodes.search_node import _generate_embeddings, _group_by_function
from services.openai_client import create_sync_client, get_embedding_model
from services.search_client import SearchService

logger = logging.getLogger(__name__)

DATASET_PATH = Path(__file__).parent / "golden_dataset.json"


@dataclass
class RetrievalResult:
    """Result of evaluating a single query."""
    query_id: str
    query: str
    expected_function: str | None
    retrieved_functions: list[str]
    function_correct: bool
    precision_at_k: float
    recall_at_k: float
    mrr: float
    score_top1: float
    score_avg: float
    num_results: int
    content_type_used: str
    latency_ms: float
    passed_threshold: bool


@dataclass
class RetrievalReport:
    """Aggregated evaluation report."""
    total_queries: int = 0
    function_accuracy: float = 0.0
    avg_precision_at_k: float = 0.0
    avg_recall_at_k: float = 0.0
    avg_mrr: float = 0.0
    avg_score_top1: float = 0.0
    avg_latency_ms: float = 0.0
    fallback_rate: float = 0.0
    threshold_pass_rate: float = 0.0
    results: list[RetrievalResult] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)


def _compute_keyword_relevance(content: str, keywords: list[str]) -> bool:
    """Check if a retrieved document is relevant based on expected keywords."""
    content_lower = content.lower()
    # A result is considered relevant if it contains at least half the expected keywords
    matches = sum(1 for kw in keywords if kw.lower() in content_lower)
    return matches >= max(1, len(keywords) // 2)


async def _embed_query(query: str) -> list | None:
    """Generate embeddings for a query."""
    try:
        from config import AZURE_OPENAI_EMBED_API_KEY, AZURE_OPENAI_EMBED_ENDPOINT
        embedding_model = get_embedding_model("embedding")
        client = create_sync_client(
            azure_endpoint=AZURE_OPENAI_EMBED_ENDPOINT,
            azure_key=AZURE_OPENAI_EMBED_API_KEY,
            llm_model=embedding_model,
        )
        return await asyncio.to_thread(
            _generate_embeddings, query, client, embedding_model=embedding_model
        )
    except Exception as exc:
        logger.error("Embedding failed for query: %s — %s", query, exc)
        return None


async def evaluate_single_query(
    item: dict, search_service: SearchService
) -> RetrievalResult | None:
    """Evaluate retrieval for a single golden dataset entry."""
    query_id = item["id"]
    query_text = item["query"]
    expected_fn = item.get("expected_function")
    expected_keywords = item.get("expected_keywords", [])
    content_type = item.get("content_type", "qa_pair")

    # Embed the query
    embedded = await _embed_query(query_text)
    if not embedded:
        return None

    rewritten_query = {"query": query_text, "filter": None}

    # Search with content_type fallback (same as search_node)
    fallback_chain = [content_type]
    if content_type == "qa_pair":
        fallback_chain.append("document")

    start_time = time.perf_counter()
    all_results: list = []
    content_type_used = content_type

    for ct in fallback_chain:
        ct_filter = f"content_type eq '{ct}'"
        raw_results = await search_service.unified_search(
            rewritten_query, embedded, odata_filter=ct_filter
        )
        qualified = [
            r for r in raw_results
            if r.get("@search.reranker_score", 0) >= AZURE_SEARCH_SCORE_THRESHOLD
        ]
        all_results.extend(qualified)
        if all_results:
            content_type_used = ct
        if len(all_results) >= DISCOVERY_TOP_K:
            break

    latency_ms = (time.perf_counter() - start_time) * 1000

    # Sort by score and take top-K
    all_results.sort(key=lambda r: r.get("@search.reranker_score", 0), reverse=True)
    top_results = all_results[:TOP_K]

    if not top_results:
        return RetrievalResult(
            query_id=query_id,
            query=query_text,
            expected_function=expected_fn,
            retrieved_functions=[],
            function_correct=False,
            precision_at_k=0.0,
            recall_at_k=0.0,
            mrr=0.0,
            score_top1=0.0,
            score_avg=0.0,
            num_results=0,
            content_type_used=content_type_used,
            latency_ms=latency_ms,
            passed_threshold=False,
        )

    # Compute metrics
    function_groups, _ = _group_by_function(top_results)
    retrieved_functions = list(function_groups.keys())
    function_correct = expected_fn in retrieved_functions if expected_fn else True

    # Keyword-based relevance for each result
    relevance_flags = [
        _compute_keyword_relevance(r.get("content", ""), expected_keywords)
        for r in top_results
    ]

    # Precision@K
    relevant_count = sum(relevance_flags)
    precision_at_k = relevant_count / len(top_results) if top_results else 0.0

    # Recall@K (assumes all relevant docs are ≤ DISCOVERY_TOP_K in the index)
    # This is an approximation — true recall requires knowing total relevant docs
    recall_at_k = 1.0 if relevant_count > 0 else 0.0

    # MRR — reciprocal rank of first relevant result
    mrr = 0.0
    for i, is_rel in enumerate(relevance_flags):
        if is_rel:
            mrr = 1.0 / (i + 1)
            break

    scores = [r.get("@search.reranker_score", 0) for r in top_results]
    score_top1 = scores[0] if scores else 0.0
    score_avg = sum(scores) / len(scores) if scores else 0.0
    passed_threshold = score_top1 >= AZURE_SEARCH_SCORE_THRESHOLD

    return RetrievalResult(
        query_id=query_id,
        query=query_text,
        expected_function=expected_fn,
        retrieved_functions=retrieved_functions,
        function_correct=function_correct,
        precision_at_k=precision_at_k,
        recall_at_k=recall_at_k,
        mrr=mrr,
        score_top1=score_top1,
        score_avg=score_avg,
        num_results=len(top_results),
        content_type_used=content_type_used,
        latency_ms=latency_ms,
        passed_threshold=passed_threshold,
    )


async def run_retrieval_evaluation(dataset_path: str | None = None) -> RetrievalReport:
    """Run retrieval evaluation against the golden dataset."""
    path = Path(dataset_path) if dataset_path else DATASET_PATH
    with open(path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    search_service = SearchService()
    report = RetrievalReport(total_queries=len(dataset))

    for item in dataset:
        try:
            result = await evaluate_single_query(item, search_service)
            if result:
                report.results.append(result)
            else:
                report.failures.append({"id": item["id"], "reason": "embedding_failed"})
        except Exception as exc:
            report.failures.append({"id": item["id"], "reason": str(exc)})
            logger.error("Evaluation failed for %s: %s", item["id"], exc)

    # Aggregate metrics
    if report.results:
        n = len(report.results)
        report.function_accuracy = sum(1 for r in report.results if r.function_correct) / n
        report.avg_precision_at_k = sum(r.precision_at_k for r in report.results) / n
        report.avg_recall_at_k = sum(r.recall_at_k for r in report.results) / n
        report.avg_mrr = sum(r.mrr for r in report.results) / n
        report.avg_score_top1 = sum(r.score_top1 for r in report.results) / n
        report.avg_latency_ms = sum(r.latency_ms for r in report.results) / n
        report.fallback_rate = sum(
            1 for r in report.results if r.content_type_used == "document"
        ) / n
        report.threshold_pass_rate = sum(
            1 for r in report.results if r.passed_threshold
        ) / n

    return report


def print_report(report: RetrievalReport) -> None:
    """Print a formatted evaluation report."""
    print("\n" + "=" * 70)
    print("  RETRIEVAL EVALUATION REPORT")
    print("=" * 70)
    print(f"  Total Queries:        {report.total_queries}")
    print(f"  Successful:           {len(report.results)}")
    print(f"  Failures:             {len(report.failures)}")
    print("-" * 70)
    print(f"  Function Accuracy:    {report.function_accuracy:.1%}")
    print(f"  Precision@K:          {report.avg_precision_at_k:.1%}")
    print(f"  Recall@K:             {report.avg_recall_at_k:.1%}")
    print(f"  MRR:                  {report.avg_mrr:.3f}")
    print(f"  Avg Top-1 Score:      {report.avg_score_top1:.2f}")
    print(f"  Threshold Pass Rate:  {report.threshold_pass_rate:.1%}")
    print(f"  Fallback Rate:        {report.fallback_rate:.1%}")
    print(f"  Avg Latency:          {report.avg_latency_ms:.0f}ms")
    print("-" * 70)

    # Per-query breakdown
    print("\n  PER-QUERY RESULTS:")
    print(f"  {'ID':<10} {'Score':>6} {'P@K':>5} {'MRR':>5} {'Fn?':>4} {'CT':>8} {'Query':<35}")
    print("  " + "-" * 75)
    for r in report.results:
        fn_mark = "Y" if r.function_correct else "N"
        print(
            f"  {r.query_id:<10} {r.score_top1:>6.2f} "
            f"{r.precision_at_k:>5.1%} {r.mrr:>5.2f} "
            f"{fn_mark:>4} {r.content_type_used:>8} "
            f"{r.query[:35]}"
        )

    if report.failures:
        print(f"\n  FAILURES:")
        for f in report.failures:
            print(f"    {f['id']}: {f['reason']}")

    print("=" * 70)

    # Quality gates
    print("\n  QUALITY GATES:")
    gates = [
        ("Function Accuracy ≥ 80%", report.function_accuracy >= 0.8),
        ("Precision@K ≥ 60%", report.avg_precision_at_k >= 0.6),
        ("MRR ≥ 0.5", report.avg_mrr >= 0.5),
        ("Threshold Pass ≥ 70%", report.threshold_pass_rate >= 0.7),
        ("Avg Latency < 3000ms", report.avg_latency_ms < 3000),
    ]
    all_pass = True
    for label, passed in gates:
        status = "PASS" if passed else "FAIL"
        icon = "[+]" if passed else "[-]"
        if not passed:
            all_pass = False
        print(f"    {icon} {label}: {status}")

    print(f"\n  OVERALL: {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70 + "\n")

    return all_pass


async def main():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Run retrieval evaluation")
    parser.add_argument("--dataset", default=None, help="Path to golden dataset JSON")
    parser.add_argument("--output", default=None, help="Path to save JSON results")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    report = await run_retrieval_evaluation(args.dataset)
    all_pass = print_report(report)

    if args.output:
        output_data = {
            "summary": {
                "total_queries": report.total_queries,
                "function_accuracy": report.function_accuracy,
                "avg_precision_at_k": report.avg_precision_at_k,
                "avg_recall_at_k": report.avg_recall_at_k,
                "avg_mrr": report.avg_mrr,
                "avg_score_top1": report.avg_score_top1,
                "avg_latency_ms": report.avg_latency_ms,
                "fallback_rate": report.fallback_rate,
                "threshold_pass_rate": report.threshold_pass_rate,
            },
            "results": [
                {
                    "query_id": r.query_id,
                    "query": r.query,
                    "function_correct": r.function_correct,
                    "precision_at_k": r.precision_at_k,
                    "mrr": r.mrr,
                    "score_top1": r.score_top1,
                    "num_results": r.num_results,
                    "content_type_used": r.content_type_used,
                    "latency_ms": r.latency_ms,
                }
                for r in report.results
            ],
            "failures": report.failures,
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2)
        print(f"  Results saved to: {args.output}")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    asyncio.run(main())
