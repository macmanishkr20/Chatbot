"""
QueryPlan → safe parameterised SQL compiler.

Hard guarantees:
  - SELECT only (verified post-build).
  - All identifiers come from the whitelisted ``TableSchema``.
  - All values are parameterised (``?`` placeholders).
  - No semicolons, comments, or multi-statement SQL.
  - Mandatory ``security_predicates`` AND-injected for row-level security.
  - Hard ``TOP`` cap on result size.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from decimal import Decimal
from typing import Any, Sequence

from agents._base.sql_planner.fiscal import (
    fiscal_quarter_range,
    fiscal_year_range,
)
from agents._base.sql_planner.plan import (
    ColumnSpec,
    FilterClause,
    QueryPlan,
    TableSchema,
)

logger = logging.getLogger(__name__)


class CompileError(ValueError):
    """Raised when a QueryPlan is not safe to compile."""


_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _check_ident(name: str) -> str:
    """Reject anything that's not a plain SQL identifier."""
    if not isinstance(name, str) or not _SAFE_IDENT.match(name):
        raise CompileError(f"Unsafe identifier: {name!r}")
    return name


def _check_column(
    name: str,
    schema: TableSchema,
    *,
    must_be: set[str] | None = None,
) -> ColumnSpec:
    spec = schema.column(name)
    if spec is None:
        raise CompileError(
            f"Unknown column: {name!r}. Allowed: {[c.name for c in schema.columns]}"
        )
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


def _expand_synonyms(filter_: FilterClause, schema: TableSchema) -> FilterClause:
    """Rewrite ``eq "flight"`` → ``in ["Air Travel", "Airfare"]`` per schema synonyms."""
    syn = (schema.synonyms or {}).get(filter_.column)
    if not syn:
        for k, v in (schema.synonyms or {}).items():
            if k.lower() == filter_.column.lower():
                syn = v
                break
    if not syn:
        return filter_

    if filter_.op == "eq" and isinstance(filter_.value, str):
        canonical = syn.get(filter_.value.strip().lower())
        if canonical:
            return FilterClause(column=filter_.column, op="in", values=list(canonical))
    if filter_.op == "in" and filter_.values:
        expanded: list[Any] = []
        changed = False
        for v in filter_.values:
            if isinstance(v, str):
                canonical = syn.get(v.strip().lower())
                if canonical:
                    expanded.extend(canonical)
                    changed = True
                    continue
            expanded.append(v)
        if changed:
            seen: set = set()
            uniq: list = []
            for v in expanded:
                if v in seen:
                    continue
                seen.add(v)
                uniq.append(v)
            return FilterClause(column=filter_.column, op="in", values=uniq)
    return filter_


def _compile_filter(filter_: FilterClause, schema: TableSchema) -> tuple[str, list[Any]]:
    filter_ = _expand_synonyms(filter_, schema)
    spec = _check_column(filter_.column, schema, must_be={"filterable"})
    col_sql = _check_ident(spec.name)
    op = filter_.op

    # FY label equality on an FY-typed column (e.g. Period LIKE 'FY26%')
    if spec.py_type == "fy" and op == "eq" and filter_.fy_label:
        return f"{col_sql} = ?", [filter_.fy_label.upper()]

    if op == "is_null":
        return f"{col_sql} IS NULL", []
    if op == "is_not_null":
        return f"{col_sql} IS NOT NULL", []

    if op in {"eq", "ne", "lt", "lte", "gt", "gte"}:
        if filter_.value is None:
            raise CompileError(f"Operator {op} requires a value for {filter_.column!r}.")
        sql_op = {"eq": "=", "ne": "<>", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}[op]
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
        # FY / FQ → date range translation on a date-typed column
        if spec.py_type == "date" and filter_.fy_label and not filter_.values:
            if filter_.fq_label:
                lo, hi = fiscal_quarter_range(filter_.fy_label, filter_.fq_label)
            else:
                lo, hi = fiscal_year_range(filter_.fy_label)
            return f"{col_sql} BETWEEN ? AND ?", [lo, hi]
        if not filter_.values or len(filter_.values) != 2:
            raise CompileError(
                f"Operator BETWEEN on {filter_.column!r} requires exactly 2 values or fy_label."
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
    """Compile a validated ``QueryPlan`` to ``(sql, params)``.

    ``security_predicates`` are tuples of ``(sql_fragment, params)`` that
    are AND-ed onto WHERE unconditionally. Use this for row-level security
    (e.g. ``("EmployeeId = ?", [user_gui])``). Fragments are trusted code
    — they never come from the LLM.
    """
    table = _check_ident(schema.table)

    select_parts: list[str] = []
    group_by_parts: list[str] = []

    # ── SELECT ──
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
    else:
        cols_requested = [c for c in plan.select_columns if c != "*"]
        if not cols_requested:
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

    # Security predicates: mandatory, trusted, never from the LLM.
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
    if plan.order_by and not (plan.intent == "aggregate" and not group_by_parts):
        order_parts = []
        for o in plan.order_by:
            spec = schema.column(o.column)
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
        spec = _check_column(schema.default_order_by, schema)
        order_by_clause = f" ORDER BY {_check_ident(spec.name)} DESC"

    # ── TOP (SQL Server) ──
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
                filt_strs.append(
                    f"{f.column} in {f.fy_label}{' ' + f.fq_label if f.fq_label else ''}"
                )
            elif f.values:
                filt_strs.append(f"{f.column} {f.op} [{', '.join(map(str, f.values))}]")
            else:
                filt_strs.append(f"{f.column} {f.op} {f.value}")
        bits.append(f"where {', '.join(filt_strs)}")

    return f"Querying {schema.table}: " + "; ".join(bits) + "."
