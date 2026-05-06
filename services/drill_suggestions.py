"""
Drill-chip follow-up generator.

Given the just-executed ``QueryPlan`` and the corresponding ``TableSchema``,
heuristically produce 2-4 useful "next questions" the UI can render as
chips ("Compare to last FY", "Break down by month", "Group by Vendor", …).

These are NOT LLM-generated — they're shape-driven so the suggestions are
deterministic and cheap. The frontend echoes the prompt verbatim back into
``/chat`` when the user clicks a chip.
"""
from __future__ import annotations

import logging
from typing import Any

from services.text_to_predicate import QueryPlan, TableSchema

logger = logging.getLogger(__name__)


def _fy_filter(plan: QueryPlan) -> tuple[str | None, str | None]:
    """Return (fy_label, fq_label) from the plan's filters, if any."""
    for f in plan.filters:
        if f.fy_label:
            return f.fy_label, f.fq_label
    return None, None


def _has_group_by(plan: QueryPlan, col: str) -> bool:
    return any(g.lower() == col.lower() for g in (plan.group_by or []))


def _has_filter_on(plan: QueryPlan, col: str) -> bool:
    return any((f.column or "").lower() == col.lower() for f in (plan.filters or []))


def _suggestion(label: str, prompt: str) -> dict[str, str]:
    return {"label": label, "prompt": prompt}


def build_suggestions(
    plan: QueryPlan | None,
    schema: TableSchema,
    *,
    user_input: str | None = None,
    max_suggestions: int = 4,
) -> list[dict[str, str]]:
    """Suggest 2-4 follow-up prompts based on the executed plan shape.

    Safe with ``plan=None`` (returns []). Never raises.
    """
    if plan is None:
        return []

    suggestions: list[dict[str, str]] = []
    table = schema.table

    try:
        fy_label, fq_label = _fy_filter(plan)

        # ── 1. FY comparisons ────────────────────────────────────────
        if fy_label:
            try:
                yr = int(fy_label[2:])
                prev_fy = f"FY{(yr - 1) % 100:02d}"
                suggestions.append(_suggestion(
                    f"Compare to {prev_fy}",
                    f"Compare to {prev_fy}.",
                ))
            except (ValueError, IndexError):
                pass

        # ── 2. Break-down dimensions for aggregates ──────────────────
        if plan.intent == "aggregate" and not plan.group_by:
            if table == "UserExpenses":
                if not _has_group_by(plan, "Vendor"):
                    suggestions.append(_suggestion(
                        "Group by Vendor",
                        "Break this down by Vendor.",
                    ))
                if not _has_group_by(plan, "ExpenseType"):
                    suggestions.append(_suggestion(
                        "Group by Expense Type",
                        "Break this down by ExpenseType.",
                    ))
                if not _has_group_by(plan, "CountryOfPurchase"):
                    suggestions.append(_suggestion(
                        "Group by Country",
                        "Break this down by CountryOfPurchase.",
                    ))
            elif table == "UserScoreboard":
                if not _has_group_by(plan, "Period"):
                    suggestions.append(_suggestion(
                        "Trend by Period",
                        "Show this trend by Period.",
                    ))
                if not _has_group_by(plan, "SL"):
                    suggestions.append(_suggestion(
                        "Group by Service Line",
                        "Break this down by SL.",
                    ))
                if not _has_group_by(plan, "Country"):
                    suggestions.append(_suggestion(
                        "Group by Country",
                        "Break this down by Country.",
                    ))

        # ── 3. Top-N drill for list intents ──────────────────────────
        if plan.intent == "list" and table == "UserExpenses":
            if not _has_group_by(plan, "Vendor"):
                suggestions.append(_suggestion(
                    "Top 5 Vendors",
                    "Show me the top 5 vendors by spend"
                    + (f" in {fy_label}." if fy_label else "."),
                ))

        if plan.intent == "list" and table == "UserScoreboard":
            suggestions.append(_suggestion(
                "Highest GTER",
                "Who has the highest GTER"
                + (f" in {fy_label}?" if fy_label else "?"),
            ))

        # ── 4. Time-narrowing for plans that don't have an FY filter ─
        if not fy_label and plan.intent in {"list", "aggregate", "rank"}:
            suggestions.append(_suggestion(
                "Limit to FY26",
                "Limit this to FY26.",
            ))

        # De-dupe by label, preserve order, cap.
        seen: set[str] = set()
        deduped: list[dict[str, str]] = []
        for s in suggestions:
            if s["label"] in seen:
                continue
            seen.add(s["label"])
            deduped.append(s)
            if len(deduped) >= max_suggestions:
                break
        return deduped
    except Exception as exc:  # pragma: no cover — never break the agent
        logger.warning("build_suggestions failed: %s", exc, exc_info=True)
        return []
