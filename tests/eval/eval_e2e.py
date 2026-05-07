"""
End-to-end evaluation pipeline for MENA Chat RAG system.

Runs the full pipeline (search → grade → generate) against the golden dataset
and produces a combined report covering retrieval, generation, and overall accuracy.

Usage:
    python -m tests.eval.eval_e2e [--dataset tests/eval/golden_dataset.json] [--output report.json]

Exit code:
    0 = all quality gates pass
    1 = one or more quality gates fail
"""
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config import AZURE_SEARCH_SCORE_THRESHOLD, DISCOVERY_TOP_K, TOP_K
from graph.nodes.search_node import _generate_embeddings, _strip_internal_fields
from services.openai_client import create_sync_client, get_embedding_model
from services.search_client import SearchService
from tests.eval.eval_retrieval import evaluate_single_query, RetrievalReport, print_report as print_retrieval_report
from tests.eval.eval_generation import (
    evaluate_single_generation,
    GenerationReport,
    print_report as print_generation_report,
)

logger = logging.getLogger(__name__)

DATASET_PATH = Path(__file__).parent / "golden_dataset.json"


@dataclass
class E2EResult:
    """Combined result for a single query."""
    query_id: str
    query: str
    retrieval_score: float
    generation_faithfulness: float
    generation_relevance: float
    overall_score: float
    latency_ms: float
    passed: bool


@dataclass
class E2EReport:
    """Full end-to-end evaluation report."""
    total_queries: int = 0
    overall_accuracy: float = 0.0
    avg_latency_ms: float = 0.0
    retrieval_report: RetrievalReport = field(default_factory=RetrievalReport)
    generation_report: GenerationReport = field(default_factory=GenerationReport)
    results: list[E2EResult] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)


async def _generate_answer(query: str, events: list) -> str:
    """Generate an answer using the same logic as generate_node (non-streaming)."""
    from graph.nodes.generate_node import _generate_response
    from graph.state import RAGState

    # Build minimal state for generation
    state: RAGState = {
        "events": events,
        "rewritten_query": {"query": query, "filter": None},
        "is_free_form": True,
        "messages": [],
        "summary": "",
        "user_memories": [],
        "citation_map": None,
        "sub_function": "",
    }

    ai_content, _, _, _ = await _generate_response(events, state)
    return ai_content or ""


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
        logger.error("Embedding failed: %s", exc)
        return None


async def run_e2e_evaluation(dataset_path: str | None = None) -> E2EReport:
    """Run full end-to-end evaluation."""
    path = Path(dataset_path) if dataset_path else DATASET_PATH
    with open(path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    search_service = SearchService()
    report = E2EReport(total_queries=len(dataset))
    retrieval_report = RetrievalReport(total_queries=len(dataset))
    generation_report = GenerationReport(total_queries=len(dataset))

    for item in dataset:
        query_id = item["id"]
        query_text = item["query"]

        try:
            start = time.perf_counter()

            # Phase 1: Retrieval
            retrieval_result = await evaluate_single_query(item, search_service)
            if not retrieval_result:
                report.failures.append({"id": query_id, "phase": "retrieval", "reason": "embed_failed"})
                continue
            retrieval_report.results.append(retrieval_result)

            # Phase 2: Get actual search results for generation
            embedded = await _embed_query(query_text)
            if not embedded:
                report.failures.append({"id": query_id, "phase": "embed", "reason": "failed"})
                continue

            content_type = item.get("content_type", "qa_pair")
            fallback_chain = [content_type]
            if content_type == "qa_pair":
                fallback_chain.append("document")

            all_results: list = []
            for ct in fallback_chain:
                ct_filter = f"content_type eq '{ct}'"
                raw = await search_service.unified_search(
                    {"query": query_text, "filter": None}, embedded, odata_filter=ct_filter
                )
                qualified = [r for r in raw if r.get("@search.reranker_score", 0) >= AZURE_SEARCH_SCORE_THRESHOLD]
                all_results.extend(qualified)
                if len(all_results) >= DISCOVERY_TOP_K:
                    break

            all_results.sort(key=lambda r: r.get("@search.reranker_score", 0), reverse=True)
            events = _strip_internal_fields(all_results[:TOP_K])

            # Phase 3: Generation
            answer = await _generate_answer(query_text, events)

            # Phase 4: Evaluate generation
            gen_result = await evaluate_single_generation(query_text, answer, events, item)
            generation_report.results.append(gen_result)

            latency_ms = (time.perf_counter() - start) * 1000

            # Compute overall score (weighted: retrieval 30%, faithfulness 40%, relevance 30%)
            overall = (
                retrieval_result.precision_at_k * 0.3
                + gen_result.faithfulness_score * 0.4
                + gen_result.relevance_score * 0.3
            )

            report.results.append(E2EResult(
                query_id=query_id,
                query=query_text,
                retrieval_score=retrieval_result.precision_at_k,
                generation_faithfulness=gen_result.faithfulness_score,
                generation_relevance=gen_result.relevance_score,
                overall_score=overall,
                latency_ms=latency_ms,
                passed=overall >= 0.6,
            ))

        except Exception as exc:
            report.failures.append({"id": query_id, "phase": "e2e", "reason": str(exc)})
            logger.error("E2E eval failed for %s: %s", query_id, exc, exc_info=True)

    # Aggregate
    if report.results:
        n = len(report.results)
        report.overall_accuracy = sum(1 for r in report.results if r.passed) / n
        report.avg_latency_ms = sum(r.latency_ms for r in report.results) / n

    # Aggregate sub-reports
    if retrieval_report.results:
        n = len(retrieval_report.results)
        retrieval_report.function_accuracy = sum(1 for r in retrieval_report.results if r.function_correct) / n
        retrieval_report.avg_precision_at_k = sum(r.precision_at_k for r in retrieval_report.results) / n
        retrieval_report.avg_mrr = sum(r.mrr for r in retrieval_report.results) / n

    if generation_report.results:
        n = len(generation_report.results)
        answered = [r for r in generation_report.results if not r.is_no_answer]
        generation_report.avg_faithfulness = sum(r.faithfulness_score for r in answered) / len(answered) if answered else 0
        generation_report.avg_relevance = sum(r.relevance_score for r in answered) / len(answered) if answered else 0
        generation_report.avg_citation_accuracy = sum(r.citation_accuracy for r in answered) / len(answered) if answered else 0
        generation_report.hallucination_rate = sum(1 for r in answered if r.has_hallucination) / len(answered) if answered else 0
        generation_report.no_answer_rate = sum(1 for r in generation_report.results if r.is_no_answer) / n
        no_answers = [r for r in generation_report.results if r.is_no_answer]
        generation_report.no_answer_precision = sum(1 for r in no_answers if r.no_answer_appropriate) / len(no_answers) if no_answers else 1.0

    report.retrieval_report = retrieval_report
    report.generation_report = generation_report

    return report


def print_e2e_report(report: E2EReport) -> bool:
    """Print combined E2E report."""
    print("\n" + "=" * 70)
    print("  END-TO-END EVALUATION REPORT")
    print("=" * 70)
    print(f"  Total Queries:     {report.total_queries}")
    print(f"  Evaluated:         {len(report.results)}")
    print(f"  Failures:          {len(report.failures)}")
    print(f"  Overall Accuracy:  {report.overall_accuracy:.1%}")
    print(f"  Avg Latency:       {report.avg_latency_ms:.0f}ms")
    print("-" * 70)

    print("\n  PER-QUERY SCORES:")
    print(f"  {'ID':<10} {'Retr':>5} {'Faith':>6} {'Relev':>6} {'Total':>6} {'Pass?':>5}")
    print("  " + "-" * 45)
    for r in report.results:
        mark = "PASS" if r.passed else "FAIL"
        print(
            f"  {r.query_id:<10} {r.retrieval_score:>5.1%} "
            f"{r.generation_faithfulness:>6.1%} {r.generation_relevance:>6.1%} "
            f"{r.overall_score:>6.1%} {mark:>5}"
        )

    # Print sub-reports
    print_retrieval_report(report.retrieval_report)
    gen_pass = print_generation_report(report.generation_report)

    # Overall quality gates
    print("\n" + "=" * 70)
    print("  FINAL QUALITY GATES:")
    gates = [
        ("Overall Accuracy ≥ 70%", report.overall_accuracy >= 0.7),
        ("Avg Latency < 5000ms", report.avg_latency_ms < 5000),
        ("Failure Rate < 20%", len(report.failures) / max(report.total_queries, 1) < 0.2),
    ]
    all_pass = True
    for label, passed in gates:
        icon = "[+]" if passed else "[-]"
        if not passed:
            all_pass = False
        print(f"    {icon} {label}: {'PASS' if passed else 'FAIL'}")

    print(f"\n  FINAL VERDICT: {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70 + "\n")

    return all_pass


async def main():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Run end-to-end RAG evaluation")
    parser.add_argument("--dataset", default=None, help="Path to golden dataset JSON")
    parser.add_argument("--output", default=None, help="Path to save JSON results")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    report = await run_e2e_evaluation(args.dataset)
    all_pass = print_e2e_report(report)

    if args.output:
        output_data = {
            "overall_accuracy": report.overall_accuracy,
            "avg_latency_ms": report.avg_latency_ms,
            "total_queries": report.total_queries,
            "pass_count": sum(1 for r in report.results if r.passed),
            "fail_count": sum(1 for r in report.results if not r.passed),
            "failures": report.failures,
            "results": [
                {
                    "query_id": r.query_id,
                    "query": r.query,
                    "overall_score": r.overall_score,
                    "retrieval_score": r.retrieval_score,
                    "faithfulness": r.generation_faithfulness,
                    "relevance": r.generation_relevance,
                    "latency_ms": r.latency_ms,
                    "passed": r.passed,
                }
                for r in report.results
            ],
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2)
        print(f"  Results saved to: {args.output}")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    asyncio.run(main())
