"""
QueryPlan — the typed predicate tree the LLM produces for analytical agents.

The LLM never writes SQL strings. Instead it fills this Pydantic model via
``LLM.with_structured_output(QueryPlan)``. The compiler then turns the plan
into safe parameterised SQL.

Why typed plans:
  - Auditable: every filter / aggregation is named and bounded.
  - Safe: identifiers come from a whitelisted ``TableSchema``; values are
    bound as parameters.
  - Testable: round-trip the plan through compile + DB without an LLM.
  - Evolvable: adding a new op or aggregate is a one-line schema update.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Schema description for prompt construction ────────────────────────────────

@dataclass(frozen=True)
class ColumnSpec:
    """One column — what the LLM is allowed to filter / group by / aggregate."""
    name: str                    # SQL column name (must be a plain identifier)
    py_type: Literal["string", "int", "decimal", "date", "fy", "fq"]
    description: str
    sample_values: tuple[str, ...] = field(default_factory=tuple)
    aggregatable: bool = False
    filterable: bool = True
    groupable: bool = False


@dataclass(frozen=True)
class TableSchema:
    """A single analytical table that an agent is allowed to query."""
    table: str                              # SQL table name
    columns: tuple[ColumnSpec, ...]
    description: str
    default_order_by: Optional[str] = None  # default sort column
    # Column-level synonym map: {column_name: {alias_lc: [canonical1, ...]}}
    # Lets the compiler turn ``eq "flight"`` into ``in ["Air Travel", "Airfare"]``.
    synonyms: dict = field(default_factory=dict)

    # ── Prompt rendering ──────────────────────────────────────────────────────
    def render_for_prompt(self) -> str:
        lines = [f"Table: **{self.table}**", self.description, "", "Columns:"]
        for c in self.columns:
            qualifiers = []
            if c.aggregatable:
                qualifiers.append("aggregatable")
            if c.groupable:
                qualifiers.append("groupable")
            qual = f" [{', '.join(qualifiers)}]" if qualifiers else ""
            samples = (
                f"  e.g. {', '.join(c.sample_values[:5])}"
                if c.sample_values else ""
            )
            lines.append(f"  - {c.name} ({c.py_type}){qual} — {c.description}{samples}")
        return "\n".join(lines)

    def column(self, name: str) -> ColumnSpec | None:
        for c in self.columns:
            if c.name.lower() == name.lower():
                return c
        return None


# ── Query plan (LLM-produced structured output) ───────────────────────────────

Operator = Literal[
    "eq", "ne", "lt", "lte", "gt", "gte",
    "in", "not_in", "between", "like", "is_null", "is_not_null",
]

Aggregate = Literal["count", "sum", "avg", "min", "max"]


class FilterClause(BaseModel):
    """One WHERE-clause atom over a single column."""
    model_config = ConfigDict(extra="forbid")

    column: str
    op: Operator
    value: Union[str, int, float, bool, None] = None
    values: Optional[list[Union[str, int, float]]] = None  # for `in` / `between`
    fy_label: str | None = None      # for FY-typed columns: "FY26"
    fq_label: str | None = None      # for FQ-typed columns: "Q3" (paired with fy_label)


class OrderClause(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    direction: Literal["asc", "desc"] = "desc"


class QueryPlan(BaseModel):
    """The structured output the LLM must produce for an analytical query."""
    model_config = ConfigDict(extra="forbid")

    intent: Literal["list", "aggregate", "rank"] = Field(
        description=(
            "`list` returns rows; `aggregate` returns a single SUM/AVG/etc. "
            "(optionally grouped); `rank` returns the top-N rows by a measure."
        ),
    )
    select_columns: list[str] = Field(
        default_factory=list,
        description="Columns to select for `list`/`rank`. Ignored for `aggregate`.",
    )
    aggregate: Optional[Aggregate] = Field(
        default=None,
        description="Required when intent='aggregate'. Function applied to `aggregate_column`.",
    )
    aggregate_column: Optional[str] = Field(
        default=None,
        description="Column to aggregate. Required for sum/avg/min/max; optional for count.",
    )
    group_by: list[str] = Field(default_factory=list)
    filters: list[FilterClause] = Field(default_factory=list)
    order_by: list[OrderClause] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1, le=1000)

    # ── Confidence / clarification metadata ──
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description=(
            "Planner self-assessed confidence in [0, 1]. < 0.6 should "
            "trigger a clarification card instead of executing."
        ),
    )
    clarification_question: Optional[str] = Field(
        default=None,
        description="When confidence is low, the question to ask the user.",
    )

    @field_validator("limit")
    @classmethod
    def _cap_limit(cls, v: int) -> int:
        return max(1, min(v, 1000))
