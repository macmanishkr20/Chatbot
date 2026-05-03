"""
Static descriptions of the analytical tables that the LLM is allowed
to query. Adding a column = updating one place.

The descriptions are deliberately compact — they are spliced into agent
prompts, so every extra word costs tokens.
"""
from __future__ import annotations

from services.text_to_predicate import ColumnSpec, TableSchema


EXPENSE_SCHEMA = TableSchema(
    table="Expenses",
    description=(
        "Per-row expense submissions for EY MENA employees. One row per "
        "expense. Use this table for ANY question about totals, filters, "
        "sorts or rankings of expense data."
    ),
    default_order_by="ExpenseDate",
    columns=(
        ColumnSpec("EmployeeId", "string", "Employee identifier (Workday id).",
                   filterable=True, groupable=True),
        ColumnSpec("EmployeeName", "string", "Display name (free-text).",
                   filterable=True, groupable=True),
        ColumnSpec("Department", "string", "Department / cost-centre.",
                   filterable=True, groupable=True),
        ColumnSpec("Location", "string", "Office location / country.",
                   filterable=True, groupable=True),
        ColumnSpec("ExpenseDate", "date", "Date the expense was incurred.",
                   filterable=True, groupable=True,
                   sample_values=("2025-08-15", "2026-02-03")),
        ColumnSpec("FiscalYear", "fy", "Fiscal year label (FY26 covers Jul 2025–Jun 2026).",
                   filterable=True, groupable=True,
                   sample_values=("FY25", "FY26")),
        ColumnSpec("FiscalQuarter", "fq", "Fiscal quarter within the year.",
                   filterable=True, groupable=True,
                   sample_values=("Q1", "Q2", "Q3", "Q4")),
        ColumnSpec("CategoryName", "string", "Expense category (Travel, Meals, etc.).",
                   filterable=True, groupable=True,
                   sample_values=("Travel", "Meals", "Office", "Training")),
        ColumnSpec("Vendor", "string", "Merchant / supplier name.",
                   filterable=True, groupable=True),
        ColumnSpec("Description", "string", "Free-text memo on the expense.",
                   filterable=True, groupable=False),
        ColumnSpec("Amount", "decimal", "Original amount in submitted currency.",
                   filterable=True, aggregatable=True),
        ColumnSpec("Currency", "string", "ISO-4217 currency code of `Amount`.",
                   filterable=True, groupable=True,
                   sample_values=("USD", "AED", "SAR", "EUR")),
        ColumnSpec("AmountUsd", "decimal", "Amount converted to USD at import.",
                   filterable=True, aggregatable=True),
        ColumnSpec("Status", "string", "Lifecycle status.",
                   filterable=True, groupable=True,
                   sample_values=("submitted", "approved", "paid", "rejected")),
    ),
)


SCOREBOARD_SCHEMA = TableSchema(
    table="Scoreboards",
    description=(
        "Per-employee performance scoreboard entries. One row per "
        "(employee, fiscal period, metric). Use this table for ranking, "
        "filtering, or aggregating performance scores."
    ),
    default_order_by="Score",
    columns=(
        ColumnSpec("EmployeeId", "string", "Employee identifier.",
                   filterable=True, groupable=True),
        ColumnSpec("EmployeeName", "string", "Display name.",
                   filterable=True, groupable=True),
        ColumnSpec("Department", "string", "Department / team.",
                   filterable=True, groupable=True),
        ColumnSpec("Location", "string", "Office location.",
                   filterable=True, groupable=True),
        ColumnSpec("FiscalYear", "fy", "Fiscal year of the score.",
                   filterable=True, groupable=True,
                   sample_values=("FY25", "FY26")),
        ColumnSpec("FiscalQuarter", "fq", "Fiscal quarter.",
                   filterable=True, groupable=True,
                   sample_values=("Q1", "Q2", "Q3", "Q4")),
        ColumnSpec("MetricName", "string", "Name of the metric being scored.",
                   filterable=True, groupable=True,
                   sample_values=("Quality", "Efficiency", "CSAT", "Utilisation")),
        ColumnSpec("Score", "decimal", "Numeric score on this metric.",
                   filterable=True, aggregatable=True),
        ColumnSpec("MaxScore", "decimal", "Cap value for this metric (when applicable).",
                   filterable=True, aggregatable=True),
        ColumnSpec("RankInGroup", "int", "Pre-computed rank within department/quarter.",
                   filterable=True, aggregatable=False),
    ),
)
