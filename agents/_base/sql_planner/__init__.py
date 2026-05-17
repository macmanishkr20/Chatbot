"""
Shared predicate-planner infrastructure for analytical agents.

Why a typed predicate plan instead of free-form NL2SQL?
  - LLM-generated raw SQL is a footgun (injection, schema-drift, scope creep).
  - A whitelisted typed plan makes intent auditable and testable.
  - Compiling plan → SQL is deterministic, cacheable, and easy to lock down.

Public API:
    plan      — Pydantic models (QueryPlan, FilterClause, OrderClause, ColumnSpec, TableSchema)
    compiler  — compile_query_plan(plan, schema, security_predicates) → (sql, params)
                explain_query_plan(plan, schema) → human-readable summary
    fiscal    — derive_fiscal_year(), fiscal_year_range(), fiscal_quarter_range()
    executor  — execute_plan(plan, schema, data_source, security_predicates)
"""
from agents._base.sql_planner.plan import (
    ColumnSpec,
    FilterClause,
    OrderClause,
    QueryPlan,
    TableSchema,
)
from agents._base.sql_planner.compiler import (
    CompileError,
    compile_query_plan,
    explain_query_plan,
)
from agents._base.sql_planner.fiscal import (
    derive_fiscal_year,
    fiscal_quarter_range,
    fiscal_year_range,
)

__all__ = [
    "ColumnSpec",
    "FilterClause",
    "OrderClause",
    "QueryPlan",
    "TableSchema",
    "CompileError",
    "compile_query_plan",
    "explain_query_plan",
    "derive_fiscal_year",
    "fiscal_year_range",
    "fiscal_quarter_range",
]
