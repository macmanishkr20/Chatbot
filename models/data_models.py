"""
Pydantic models for the analytical data store (Expense / Scoreboard).

These mirror the SQL columns in services.data_db. Used by the Excel ETL
loaders for input validation and by the agents for typed responses.
"""
from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Expenses ──

class ExpenseRecord(BaseModel):
    """One Expenses row as ingested or returned."""
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    expense_id: Optional[int] = Field(default=None, alias="ExpenseId")
    employee_id: str = Field(alias="EmployeeId")
    employee_name: Optional[str] = Field(default=None, alias="EmployeeName")
    manager_id: Optional[str] = Field(default=None, alias="ManagerId")
    department: Optional[str] = Field(default=None, alias="Department")
    location: Optional[str] = Field(default=None, alias="Location")
    expense_date: _date = Field(alias="ExpenseDate")
    fiscal_year: str = Field(alias="FiscalYear")
    fiscal_quarter: str = Field(alias="FiscalQuarter")
    category_id: Optional[int] = Field(default=None, alias="CategoryId")
    category_name: Optional[str] = Field(default=None, alias="CategoryName")
    vendor: Optional[str] = Field(default=None, alias="Vendor")
    description: Optional[str] = Field(default=None, alias="Description")
    amount: Decimal = Field(alias="Amount")
    currency: str = Field(default="USD", alias="Currency")
    amount_usd: Decimal = Field(alias="AmountUsd")
    status: str = Field(default="submitted", alias="Status")
    receipt_url: Optional[str] = Field(default=None, alias="ReceiptUrl")
    source_file: Optional[str] = Field(default=None, alias="SourceFile")
    source_row: Optional[int] = Field(default=None, alias="SourceRow")
    dedupe_key: Optional[str] = Field(default=None, alias="DedupeKey")
    imported_at: Optional[datetime] = Field(default=None, alias="ImportedAt")

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return (v or "USD").strip().upper()[:3] or "USD"


# ── Scoreboards ──

class ScoreboardRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    scoreboard_id: Optional[int] = Field(default=None, alias="ScoreboardId")
    employee_id: str = Field(alias="EmployeeId")
    employee_name: Optional[str] = Field(default=None, alias="EmployeeName")
    manager_id: Optional[str] = Field(default=None, alias="ManagerId")
    department: Optional[str] = Field(default=None, alias="Department")
    location: Optional[str] = Field(default=None, alias="Location")
    fiscal_year: str = Field(alias="FiscalYear")
    fiscal_quarter: Optional[str] = Field(default=None, alias="FiscalQuarter")
    metric_name: str = Field(alias="MetricName")
    score: Decimal = Field(alias="Score")
    max_score: Optional[Decimal] = Field(default=None, alias="MaxScore")
    rank_in_group: Optional[int] = Field(default=None, alias="RankInGroup")
    notes: Optional[str] = Field(default=None, alias="Notes")
    source_file: Optional[str] = Field(default=None, alias="SourceFile")
    source_row: Optional[int] = Field(default=None, alias="SourceRow")
    dedupe_key: Optional[str] = Field(default=None, alias="DedupeKey")
    imported_at: Optional[datetime] = Field(default=None, alias="ImportedAt")


# ── ETL run audit ──

class ImportRunResult(BaseModel):
    """Summary returned by ETL loaders so callers (admin endpoints, CLI)
    can surface progress without scanning logs."""
    run_id: Optional[int] = None
    source_file: str
    rows_read: int = 0
    rows_inserted: int = 0
    rows_skipped: int = 0
    status: str = "ok"
    error_message: Optional[str] = None
