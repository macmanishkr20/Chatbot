"""
Generation evaluation metrics for MENA Chat RAG pipeline.

Measures:
  - Faithfulness: is the answer grounded in the retrieved documents?
  - Answer Relevance: does the answer actually address the question?
  - Hallucination Detection: are there unsupported claims?
  - Citation Accuracy: do inline citations [1], [2] map to real sources?
  - [NO_ANSWER] appropriateness: was it correct to refuse?

Usage:
    python -m tests.eval.eval_generation [--dataset tests/eval/golden_dataset.json]
"""
import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.openai_client import create_async_client, get_llm_model

logger = logging.getLogger(__name__)

DATASET_PATH = Path(__file__).parent / "golden_dataset.json"


# ── LLM-as-Judge Prompts ──────────────────────────────────────────────────────

FAITHFULNESS_SYSTEM = """\
You are an expert evaluator assessing whether an AI assistant's answer is
faithfully grounded in the provided source documents.

Score the answer on a scale of 0.0 to 1.0:
- 1.0: Every claim is directly supported by the source documents
- 0.7: Most claims are supported, minor extrapolation
- 0.5: Mix of supported and unsupported claims
- 0.3: Significant unsupported claims or speculation
- 0.0: Answer is fabricated or contradicts the sources

Return JSON only: {"score": float, "reasoning": "...", "unsupported_claims": [...]}
"""

RELEVANCE_SYSTEM = """\
You are an expert evaluator assessing whether an AI assistant's answer
actually addresses the user's question.

Score the answer on a scale of 0.0 to 1.0:
- 1.0: Directly and completely answers the question
- 0.7: Mostly answers but misses some aspects
- 0.5: Partially relevant but incomplete
- 0.3: Tangentially related
- 0.0: Does not address the question at all

Return JSON only: {"score": float, "reasoning": "..."}
"""


@dataclass
class GenerationResult:
    """Result of evaluating a single generation."""
    query_id: str
    query: str
    answer: str
    faithfulness_score: float
    relevance_score: float
    citation_accuracy: float
    has_hallucination: bool
    is_no_answer: bool
    no_answer_appropriate: bool
    unsupported_claims: list[str]


@dataclass
class GenerationReport:
    """Aggregated generation evaluation report."""
    total_queries: int = 0
    avg_faithfulness: float = 0.0
    avg_relevance: float = 0.0
    avg_citation_accuracy: float = 0.0
    hallucination_rate: float = 0.0
    no_answer_rate: float = 0.0
    no_answer_precision: float = 0.0
    results: list[GenerationResult] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)


async def _judge_llm(system_prompt: str, user_prompt: str) -> dict:
    """Call LLM-as-judge for evaluation scoring."""
    llm_model = get_llm_model("events")
    client = create_async_client(llm_model=llm_model)
    response = await client.chat.completions.create(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        model=llm_model,
        temperature=0.0,
        max_tokens=300,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def _check_citation_accuracy(answer: str, events: list) -> float:
    """Check if inline citations [N] map to valid source documents."""
    cited_refs = set(re.findall(r"\[(\d+)\]", answer))
    if not cited_refs:
        return 1.0  # No citations to validate

    valid = 0
    for ref_str in cited_refs:
        idx = int(ref_str) - 1
        if 0 <= idx < len(events):
            valid += 1

    return valid / len(cited_refs) if cited_refs else 1.0


async def evaluate_single_generation(
    query: str,
    answer: str,
    events: list,
    item: dict,
) -> GenerationResult:
    """Evaluate a single generated response."""
    query_id = item["id"]
    expected_keywords = item.get("expected_answer_contains", [])

    # Check if [NO_ANSWER]
    is_no_answer = (
        "[NO_ANSWER]" in answer
        or "couldn't find a specific answer" in answer.lower()
        or "wasn't able to find" in answer.lower()
    )

    # Determine if [NO_ANSWER] was appropriate
    no_answer_appropriate = True
    if is_no_answer and events:
        # Had results but said no answer — check if expected keywords exist in results
        all_content = " ".join(e.get("content", "") for e in events).lower()
        keyword_coverage = sum(1 for kw in expected_keywords if kw.lower() in all_content)
        # If results cover most keywords, [NO_ANSWER] was likely wrong
        if keyword_coverage >= len(expected_keywords) * 0.5:
            no_answer_appropriate = False

    if is_no_answer:
        return GenerationResult(
            query_id=query_id,
            query=query,
            answer=answer[:200],
            faithfulness_score=1.0 if no_answer_appropriate else 0.0,
            relevance_score=0.0,
            citation_accuracy=1.0,
            has_hallucination=False,
            is_no_answer=True,
            no_answer_appropriate=no_answer_appropriate,
            unsupported_claims=[],
        )

    # Build context string from events
    context_str = "\n\n".join(
        f"[{i+1}] {e.get('content', '')}" for i, e in enumerate(events)
    )

    # Faithfulness scoring via LLM-as-judge
    faithfulness_prompt = (
        f"Source Documents:\n{context_str}\n\n"
        f"User Question: {query}\n\n"
        f"Assistant Answer: {answer}"
    )
    try:
        faith_result = await _judge_llm(FAITHFULNESS_SYSTEM, faithfulness_prompt)
        faithfulness_score = float(faith_result.get("score", 0.5))
        unsupported_claims = faith_result.get("unsupported_claims", [])
    except Exception:
        faithfulness_score = 0.5
        unsupported_claims = []

    # Relevance scoring via LLM-as-judge
    relevance_prompt = (
        f"User Question: {query}\n\n"
        f"Assistant Answer: {answer}"
    )
    try:
        rel_result = await _judge_llm(RELEVANCE_SYSTEM, relevance_prompt)
        relevance_score = float(rel_result.get("score", 0.5))
    except Exception:
        relevance_score = 0.5

    # Citation accuracy
    citation_accuracy = _check_citation_accuracy(answer, events)

    # Hallucination = low faithfulness + unsupported claims
    has_hallucination = faithfulness_score < 0.5 or len(unsupported_claims) > 0

    return GenerationResult(
        query_id=query_id,
        query=query,
        answer=answer[:200],
        faithfulness_score=faithfulness_score,
        relevance_score=relevance_score,
        citation_accuracy=citation_accuracy,
        has_hallucination=has_hallucination,
        is_no_answer=False,
        no_answer_appropriate=True,
        unsupported_claims=unsupported_claims,
    )


def print_report(report: GenerationReport) -> bool:
    """Print a formatted generation evaluation report."""
    print("\n" + "=" * 70)
    print("  GENERATION EVALUATION REPORT")
    print("=" * 70)
    print(f"  Total Queries:        {report.total_queries}")
    print(f"  Evaluated:            {len(report.results)}")
    print(f"  Failures:             {len(report.failures)}")
    print("-" * 70)
    print(f"  Faithfulness:         {report.avg_faithfulness:.1%}")
    print(f"  Answer Relevance:     {report.avg_relevance:.1%}")
    print(f"  Citation Accuracy:    {report.avg_citation_accuracy:.1%}")
    print(f"  Hallucination Rate:   {report.hallucination_rate:.1%}")
    print(f"  [NO_ANSWER] Rate:     {report.no_answer_rate:.1%}")
    print(f"  [NO_ANSWER] Precision:{report.no_answer_precision:.1%}")
    print("-" * 70)

    # Per-query breakdown
    print("\n  PER-QUERY RESULTS:")
    print(f"  {'ID':<10} {'Faith':>6} {'Relev':>6} {'Cite':>5} {'Hall?':>5} {'Query':<35}")
    print("  " + "-" * 70)
    for r in report.results:
        hall_mark = "Y" if r.has_hallucination else "N"
        if r.is_no_answer:
            print(
                f"  {r.query_id:<10} {'N/A':>6} {'N/A':>6} "
                f"{'N/A':>5} {'N/A':>5} {r.query[:35]} [NO_ANSWER]"
            )
        else:
            print(
                f"  {r.query_id:<10} {r.faithfulness_score:>6.1%} "
                f"{r.relevance_score:>6.1%} {r.citation_accuracy:>5.1%} "
                f"{hall_mark:>5} {r.query[:35]}"
            )

    print("=" * 70)

    # Quality gates
    print("\n  QUALITY GATES:")
    gates = [
        ("Faithfulness ≥ 80%", report.avg_faithfulness >= 0.8),
        ("Relevance ≥ 70%", report.avg_relevance >= 0.7),
        ("Citation Accuracy ≥ 90%", report.avg_citation_accuracy >= 0.9),
        ("Hallucination Rate ≤ 10%", report.hallucination_rate <= 0.1),
        ("[NO_ANSWER] Precision ≥ 80%", report.no_answer_precision >= 0.8),
    ]
    all_pass = True
    for label, passed in gates:
        icon = "[+]" if passed else "[-]"
        if not passed:
            all_pass = False
        print(f"    {icon} {label}: {'PASS' if passed else 'FAIL'}")

    print(f"\n  OVERALL: {'PASS' if all_pass else 'FAIL'}")
    print("=" * 70 + "\n")

    return all_pass
