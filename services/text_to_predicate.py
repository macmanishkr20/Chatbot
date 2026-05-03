"""
Text-to-Predicate-Tree compiler — shared by the Expense and Scoreboard
agents.

Why not Text-to-SQL directly?
  - LLM-generated raw SQL is an injection / footgun risk.
  - A whitelisted typed predicate tree makes intent auditable.
  - Compiling the tree to SQL is deterministic, testable, and cacheable.

Flow:
  1. LLM produces a ``QueryPlan`` (Pydantic) given the user question + a
     compact ``TableSchema`` description.
  2. ``compile_query_plan(plan, schema, security_predicates)`` returns
     ``(sql, params)`` — parameterised, SELECT-only, row-capped.
  3. Caller passes (sql, params) to ``DataDB.fetchall`` and the executor
     never sees free-form SQL.

The compiler enforces:
  * SELECT only.
  * No multi-statement / no semicolons / no comments in identifiers.
  * Whitelisted columns and aggregations.
  * Mandatory ``security_predicates`` injected as additional WHERE clauses
    so row-level security can never be bypassed by a clever LLM.
  * Hard ``LIMIT`` / ``TOP`` cap on row count.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from helpers.fiscal import (
    fiscal_quarter_range,
    fiscal_year_range,
)

logger = logging.getLogger(__name__)


# ── Schema description for LLM prompting ──

@dataclass(frozen=True)
class ColumnSpec:
    """Single column — what the LLM is allowed to filter / group by."""
    name: str                    # SQL column name (must be safely quoted)
    py_type: Literal["string", "int", "decimal", "date", "fy", "fq"]
    description: str
    sample_values: tuple[str, ...] = field(default_factory=tuple)
    aggregatable: bool = False   # True for numeric measure columns
    filterable: bool = True
    groupable: bool = False


@dataclass(frozen=True)
class TableSchema:
    """A single analytical table the agent can query."""
    table: str                   # SQL table name
    columns: tuple[ColumnSpec, ...]
    description: str             # one paragraph describing the table for the LLM
    default_order_by: Optional[str] = None  # column name for default sort

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


# ── Query plan (what the LLM emits) ──

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
        description="`list` returns rows; `aggregate` returns a single SUM/AVG/etc.; `rank` returns top-N rows by a measure.",
    )
    select_columns: list[str] = Field(
        default_factory=list,
        description="Columns to select for `list`/`rank`. Ignored for `aggregate`.",
    )
    aggregate: Optional[Aggregate] = Field(
        default=None,
        description="Required when intent='aggregate'. The function applied to `aggregate_column`.",
    )
    aggregate_column: Optional[str] = Field(
        default=None,
        description="Column to aggregate. Required for sum/avg/min/max; optional for count.",
    )
    group_by: list[str] = Field(default_factory=list)
    filters: list[FilterClause] = Field(default_factory=list)
    order_by: list[OrderClause] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1, le=1000)

    @field_validator("limit")
    @classmethod
    def _cap_limit(cls, v: int) -> int:
        return max(1, min(v, 1000))


# ── Compilation ──

class CompileError(ValueError):
    """Raised when a QueryPlan is not safe to compile."""


_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _check_ident(name: str) -> str:
    """Reject anything that's not a plain SQL identifier."""
    if not isinstance(name, str) or not _SAFE_IDENT.match(name):
        raise CompileError(f"Unsafe identifier: {name!r}")
    return name


def _check_column(name: str, schema: TableSchema, *, must_be: set[str] | None = None) -> ColumnSpec:
    spec = schema.column(name)
    if spec is None:
        raise CompileError(f"Unknown column: {name!r}. Allowed: {[c.name for c in schema.columns]}")
    if must_be:
        if "filterable" in must_be and not spec.filterable:
            raise CompileError(f"Column {name!r} is not filterable.")
        if "groupable" in must_be and not spec.groupable:
            raise CompileError(f"Column {name!r} is not groupable.")
        if "aggregatable" in must_be and not spec.aggregatable:
            raise CompileError(f"Column {name!r} is not aggregatable.")
    return spec


def _coerce_value(spec: ColumnSpec, value: Any) -> Any:
    """Coerce a Python value to a type the SQL driver accepts."""
    if value is None:
        return None
    if spec.py_type == "int":
        return int(value)
    if spec.py_type == "decimal":
        return Decimal(str(value))
    if spec.py_type == "date":
        if isinstance(value, date):
            return value
        from datetime import datetime as _dt
        return _dt.fromisoformat(str(value)).date()
    if spec.py_type in {"string", "fy", "fq"}:
        return str(value)
    return value


def _compile_filter(filter_: FilterClause, schema: TableSchema) -> tuple[str, list[Any]]:
    spec = _check_column(filter_.column, schema, must_be={"filterable"})
    col_sql = _check_ident(spec.name)
    op = filter_.op

    # Special-case: fiscal-year and fiscal-quarter use a label → date-range
    # translation. The LLM never emits raw dates for FY filters.
    if spec.py_type == "fy" and op == "eq" and filter_.fy_label:
        # If the column itself stores the FY label, we can equality-match it.
        # But many consumers want to filter on a date column by the FY range.
        # Here we equality-match on the label — actual range filtering on dates
        # is expressed as op=between with values=[start, end] on a date column.
        return f"{col_sql} = ?", [filter_.fy_label.upper()]

    if op == "is_null":
        return f"{col_sql} IS NULL", []
    if op == "is_not_null":
        return f"{col_sql} IS NOT NULL", []

    if op in {"eq", "ne", "lt", "lte", "gt", "gte"}:
        if filter_.value is None:
            raise CompileError(f"Operator {op} requires a value for {filter_.column!r}.")
        sql_op = {
            "eq": "=", "ne": "<>", "lt": "<", "lte": "<=", "gt": ">", "gte": ">=",
        }[op]
        return f"{col_sql} {sql_op} ?", [_coerce_value(spec, filter_.value)]

    if op == "in":
        if not filter_.values:
            raise CompileError(f"Operator IN requires non-empty values for {filter_.column!r}.")
        placeholders = ", ".join("?" for _ in filter_.values)
        return f"{col_sql} IN ({placeholders})", [_coerce_value(spec, v) for v in filter_.values]

    if op == "not_in":
        if not filter_.values:
            raise CompileError(f"Operator NOT IN requires non-empty values for {filter_.column!r}.")
        placeholders = ", ".join("?" for _ in filter_.values)
        return f"{col_sql} NOT IN ({placeholders})", [_coerce_value(spec, v) for v in filter_.values]

    if op == "between":
        # Special: FY/FQ labels resolve to date ranges if the column is a date.
        if spec.py_type == "date" and filter_.fy_label and not filter_.values:
            if filter_.fq_label:
                lo, hi = fiscal_quarter_range(filter_.fy_label, filter_.fq_label)
            else:
                lo, hi = fiscal_year_range(filter_.fy_label)
            return f"{col_sql} BETWEEN ? AND ?", [lo, hi]
        if not filter_.values or len(filter_.values) != 2:
            raise CompileError(
                f"Operator BETWEEN on {filter_.column!r} requires exactly 2 values "
                f"or fy_label.",
            )
        return f"{col_sql} BETWEEN ? AND ?", [
            _coerce_value(spec, filter_.values[0]),
            _coerce_value(spec, filter_.values[1]),
        ]

    if op == "like":
        if filter_.value is None:
            raise CompileError(f"Operator LIKE requires a value for {filter_.column!r}.")
        return f"{col_sql} LIKE ?", [str(filter_.value)]

    raise CompileError(f"Unsupported operator: {op}")


def compile_query_plan(
    plan: QueryPlan,
    schema: TableSchema,
    *,
    security_predicates: Sequence[tuple[str, Sequence[Any]]] = (),
    hard_row_cap: int = 1000,
) -> tuple[str, list[Any]]:
    """Compile a validated ``QueryPlan`` to (sql, params).

    ``security_predicates`` are tuples of (sql_fragment, params) that are
    AND-ed onto WHERE unconditionally. Use this for row-level security
    (e.g. ``("EmployeeId = ?", [current_user_id])``). Fragments are
    treated as trusted code — they never come from the LLM.

    The compiler raises ``CompileError`` for any unsafe input. The caller
    should treat this as a 4xx-equivalent and fall back to "I can't run
    that query — try rephrasing".
    """
    table = _check_ident(schema.table)

    select_parts: list[str] = []
    group_by_parts: list[str] = []

    if plan.intent == "aggregate":
        if plan.aggregate is None:
            raise CompileError("intent=aggregate requires `aggregate`.")
        if plan.aggregate == "count" and plan.aggregate_column is None:
            select_parts.append("COUNT(*) AS Value")
        else:
            if plan.aggregate_column is None:
                raise CompileError("Non-count aggregates require `aggregate_column`.")
            agg_spec = _check_column(plan.aggregate_column, schema, must_be={"aggregatable"})
            agg_col = _check_ident(agg_spec.name)
            select_parts.append(f"{plan.aggregate.upper()}({agg_col}) AS Value")

        for g in plan.group_by:
            spec = _check_column(g, schema, must_be={"groupable"})
            select_parts.insert(-1, _check_ident(spec.name))
            group_by_parts.append(_check_ident(spec.name))

    else:  # list / rank
        # Strip wildcard "*" — treat it as "no specific columns" (select all).
        cols_requested = [c for c in plan.select_columns if c != "*"]
        if not cols_requested:
            # Default to all groupable + a few measure columns
            select_cols = [c.name for c in schema.columns if c.groupable or c.aggregatable]
            if not select_cols:
                select_cols = [c.name for c in schema.columns[:8]]
        else:
            select_cols = cols_requested
        for col in select_cols:
            spec = _check_column(col, schema)
            select_parts.append(_check_ident(spec.name))

    select_clause = ", ".join(select_parts) if select_parts else "*"

    # ── WHERE ──
    where_fragments: list[str] = []
    params: list[Any] = []

    for f in plan.filters:
        sql_frag, sql_params = _compile_filter(f, schema)
        where_fragments.append(sql_frag)
        params.extend(sql_params)

    # Security predicates last — they are mandatory and trusted.
    for sec_frag, sec_params in security_predicates:
        if not isinstance(sec_frag, str):
            raise CompileError("security_predicate must be a string SQL fragment.")
        if ";" in sec_frag or "--" in sec_frag:
            raise CompileError("security_predicate must not contain `;` or `--`.")
        where_fragments.append(sec_frag)
        params.extend(list(sec_params))

    where_clause = ""
    if where_fragments:
        where_clause = " WHERE " + " AND ".join(f"({f})" for f in where_fragments)

    # ── GROUP BY ──
    group_by_clause = ""
    if group_by_parts:
        group_by_clause = " GROUP BY " + ", ".join(group_by_parts)

    # ── ORDER BY ──
    order_by_clause = ""
    # Skip ORDER BY for simple aggregates (no GROUP BY) — the result is a
    # single row so ordering is meaningless and causes SQL errors.
    if plan.order_by and not (plan.intent == "aggregate" and not group_by_parts):
        order_parts = []
        for o in plan.order_by:
            spec = schema.column(o.column)
            # Allow ordering by aggregate alias "Value" when intent=aggregate
            if spec is None and o.column.lower() == "value" and plan.intent == "aggregate":
                order_parts.append(f"Value {('ASC' if o.direction == 'asc' else 'DESC')}")
                continue
            if spec is None:
                raise CompileError(f"Unknown order column: {o.column!r}")
            order_parts.append(
                f"{_check_ident(spec.name)} {('ASC' if o.direction == 'asc' else 'DESC')}",
            )
        order_by_clause = " ORDER BY " + ", ".join(order_parts)
    elif plan.intent == "rank" and plan.aggregate_column:
        spec = _check_column(plan.aggregate_column, schema, must_be={"aggregatable"})
        order_by_clause = f" ORDER BY {_check_ident(spec.name)} DESC"
    elif plan.intent != "aggregate" and schema.default_order_by:
        # Only apply default ordering for list/rank — not simple aggregates.
        spec = _check_column(schema.default_order_by, schema)
        order_by_clause = f" ORDER BY {_check_ident(spec.name)} DESC"

    # ── TOP (SQL Server) — preferred over LIMIT for compatibility ──
    # Skip TOP for simple aggregates (single-row result).
    if plan.intent == "aggregate" and not group_by_parts:
        top_clause = ""
    else:
        effective_limit = min(plan.limit or 50, hard_row_cap)
        top_clause = f" TOP ({int(effective_limit)})"

    sql = f"SELECT{top_clause} {select_clause} FROM {table}{where_clause}{group_by_clause}{order_by_clause}"

    # ── Final guardrails ──
    if ";" in sql:
        raise CompileError("Compiled SQL must not contain `;`.")
    if "--" in sql:
        raise CompileError("Compiled SQL must not contain `--`.")
    if not sql.upper().lstrip().startswith("SELECT"):
        raise CompileError("Compiled SQL must start with SELECT.")

    return sql, params


def explain_query_plan(plan: QueryPlan, schema: TableSchema) -> str:
    """Human-readable summary of what we ran (for the synthesize node)."""
    bits: list[str] = []
    if plan.intent == "aggregate":
        agg = (plan.aggregate or "count").upper()
        col = plan.aggregate_column or "*"
        bits.append(f"{agg}({col})")
        if plan.group_by:
            bits.append(f"grouped by {', '.join(plan.group_by)}")
    elif plan.intent == "rank":
        bits.append(f"top {plan.limit} by {plan.aggregate_column or 'measure'}")
    else:
        bits.append(f"list of up to {plan.limit} rows")

    if plan.filters:
        filt_strs = []
        for f in plan.filters:
            if f.fy_label:
                filt_strs.append(f"{f.column} in {f.fy_label}{f' ' + f.fq_label if f.fq_label else ''}")
            elif f.values:
                filt_strs.append(f"{f.column} {f.op} [{', '.join(map(str, f.values))}]")
            else:
                filt_strs.append(f"{f.column} {f.op} {f.value}")
        bits.append(f"where {', '.join(filt_strs)}")

    return f"Querying {schema.table}: " + "; ".join(bits) + "."
