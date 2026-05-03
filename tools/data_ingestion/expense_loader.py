"""
Excel → Expenses ETL loader.

Idempotent: re-running the same source file produces the same DB state.
Each row's ``DedupeKey`` is the SHA-1 of a stable canonical tuple
(employee_id, expense_date ISO, amount cents, currency, vendor lower,
 description lower, source_file).

Usage:
    python -m tools.data_ingestion.expense_loader path/to/expenses.xlsx --fx 1.00 --triggered-by user@ey.com

The same function is exposed via ``import_expense_workbook`` so it can
be triggered from an admin endpoint.

Excel column mapping (case-insensitive, trimmed):
    Required: employee_id | employee id, expense_date | date, amount, currency
    Optional: employee_name, manager_id, department, location, category,
              vendor, description, status, receipt_url

If the sheet uses different headers, override via ``column_map``.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import math
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from helpers.fiscal import derive_fiscal_quarter, derive_fiscal_year
from models.data_models import ImportRunResult
from services.data_db import DataDB

logger = logging.getLogger(__name__)


_DEFAULT_COLUMN_MAP: dict[str, tuple[str, ...]] = {
    "employee_id":   ("employee_id", "employee id", "emp_id", "empid"),
    "employee_name": ("employee_name", "employee name", "name"),
    "manager_id":    ("manager_id", "manager id"),
    "department":    ("department", "dept"),
    "location":      ("location", "office", "country"),
    "expense_date":  ("expense_date", "date", "expense date", "txn_date", "transaction date"),
    "category":      ("category", "expense_category", "type"),
    "vendor":        ("vendor", "merchant", "supplier"),
    "description":   ("description", "memo", "details", "note"),
    "amount":        ("amount", "value", "expense_amount"),
    "currency":      ("currency", "ccy"),
    "status":        ("status", "state"),
    "receipt_url":   ("receipt_url", "receipt", "url"),
}


def _normalise_columns(headers: list[str]) -> dict[str, str]:
    """Map our canonical names → actual sheet header (preserving case)."""
    lookup = {h.lower().strip(): h for h in headers if isinstance(h, str)}
    resolved: dict[str, str] = {}
    for canonical, candidates in _DEFAULT_COLUMN_MAP.items():
        for c in candidates:
            if c in lookup:
                resolved[canonical] = lookup[c]
                break
    return resolved


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return Decimal(str(value))
    if isinstance(value, Decimal):
        return value
    s = str(value).strip().replace(",", "")
    if not s:
        return None
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _make_dedupe_key(row: Mapping[str, Any], source_file: str) -> str:
    canonical = "|".join([
        str(row.get("employee_id") or "").strip().lower(),
        (row.get("expense_date").isoformat() if isinstance(row.get("expense_date"), date) else ""),
        str(int(((row.get("amount") or Decimal("0")) * 100).to_integral_value())),
        str(row.get("currency") or "USD").strip().upper(),
        str(row.get("vendor") or "").strip().lower(),
        str(row.get("description") or "").strip().lower(),
        source_file,
    ])
    return hashlib.sha1(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()


def _read_workbook(path: Path) -> tuple[list[str], list[list[Any]]]:
    """Lazy import openpyxl so the loader stays optional in deployments
    that don't run ingestion."""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "openpyxl is required for Excel ingestion. "
            "Install it with `pip install openpyxl`.",
        ) from exc

    wb = load_workbook(filename=str(path), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], []
    headers = [(h or "") for h in rows[0]]
    headers = [str(h) if h is not None else "" for h in headers]
    return headers, [list(r) for r in rows[1:]]


async def _ensure_categories(category_names: list[str], db: DataDB) -> dict[str, int]:
    """Upsert ExpenseCategories and return name → CategoryId map."""
    distinct = sorted({n for n in category_names if n})
    if not distinct:
        return {}
    rows = [(n,) for n in distinct]
    await db.execute_many(
        """
        IF NOT EXISTS (SELECT 1 FROM ExpenseCategories WHERE Name = ?)
            INSERT INTO ExpenseCategories (Name) VALUES (?)
        """,
        [(n, n) for n in distinct],
    )
    fetched = await db.fetchall(
        "SELECT CategoryId, Name FROM ExpenseCategories",
    )
    return {r["Name"]: r["CategoryId"] for r in fetched}


async def import_expense_workbook(
    workbook_path: str | Path,
    *,
    default_currency: str = "USD",
    fx_to_usd: float = 1.0,
    triggered_by: str | None = None,
    column_map: dict[str, str] | None = None,
) -> ImportRunResult:
    """Load an Excel workbook into the Expenses table. Idempotent.

    Args:
        workbook_path: path to the .xlsx file.
        default_currency: applied when the row has no currency column.
        fx_to_usd: simple flat conversion rate when currency != USD.
            Replace with a real FX lookup later.
        triggered_by: stamped on the audit row.
        column_map: override the canonical → sheet-header mapping.
    """
    path = Path(workbook_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)

    db = DataDB()
    await db.ensure()

    # ── Open audit row ──
    run_id_row = await db.fetchone(
        """
        INSERT INTO ExpenseImportRuns (SourceFile, TriggeredBy)
        OUTPUT INSERTED.RunId
        VALUES (?, ?)
        """,
        [str(path.name), triggered_by],
    )
    run_id = (run_id_row or {}).get("RunId")

    headers, raw_rows = _read_workbook(path)
    resolved_cols = column_map or _normalise_columns(headers)
    if not {"employee_id", "expense_date", "amount"}.issubset(resolved_cols):
        await db.execute(
            """
            UPDATE ExpenseImportRuns
            SET Status='failed', ErrorMessage=?, FinishedAt=SYSUTCDATETIME()
            WHERE RunId=?
            """,
            [f"Missing required columns. Found: {list(resolved_cols)}", run_id],
        )
        raise ValueError(
            f"Workbook is missing required columns (employee_id / expense_date / amount). "
            f"Found columns: {headers}"
        )

    header_idx = {h: i for i, h in enumerate(headers)}

    def col(row: list[Any], canonical: str) -> Any:
        sheet_header = resolved_cols.get(canonical)
        if sheet_header is None:
            return None
        idx = header_idx.get(sheet_header)
        if idx is None or idx >= len(row):
            return None
        return row[idx]

    # ── Pass 1: parse rows; collect category names ──
    parsed: list[dict[str, Any]] = []
    category_names: list[str] = []
    rows_skipped = 0
    for i, raw in enumerate(raw_rows, start=2):  # +2 because Excel row 1 is header
        emp = col(raw, "employee_id")
        d = _parse_date(col(raw, "expense_date"))
        amt = _parse_decimal(col(raw, "amount"))
        if not emp or not d or amt is None:
            rows_skipped += 1
            continue

        currency = (col(raw, "currency") or default_currency or "USD")
        currency = str(currency).strip().upper()[:3] or "USD"
        amount_usd = (amt if currency == "USD" else amt * Decimal(str(fx_to_usd))).quantize(Decimal("0.01"))

        cat_name = (col(raw, "category") or None)
        if isinstance(cat_name, str):
            cat_name = cat_name.strip() or None

        record = {
            "employee_id": str(emp).strip(),
            "employee_name": col(raw, "employee_name"),
            "manager_id": col(raw, "manager_id"),
            "department": col(raw, "department"),
            "location": col(raw, "location"),
            "expense_date": d,
            "fiscal_year": derive_fiscal_year(d),
            "fiscal_quarter": derive_fiscal_quarter(d),
            "category_name": cat_name,
            "vendor": col(raw, "vendor"),
            "description": col(raw, "description"),
            "amount": amt.quantize(Decimal("0.01")),
            "currency": currency,
            "amount_usd": amount_usd,
            "status": (col(raw, "status") or "submitted"),
            "receipt_url": col(raw, "receipt_url"),
            "source_file": path.name,
            "source_row": i,
        }
        record["dedupe_key"] = _make_dedupe_key(record, path.name)
        parsed.append(record)
        if cat_name:
            category_names.append(cat_name)

    cat_map = await _ensure_categories(category_names, db)

    # ── Pass 2: insert with dedupe key collision skipped ──
    insert_sql = """
        IF NOT EXISTS (SELECT 1 FROM Expenses WHERE DedupeKey = ?)
        INSERT INTO Expenses
            (EmployeeId, EmployeeName, ManagerId, Department, Location,
             ExpenseDate, FiscalYear, FiscalQuarter,
             CategoryId, CategoryName, Vendor, Description,
             Amount, Currency, AmountUsd, Status, ReceiptUrl,
             SourceFile, SourceRow, DedupeKey)
        VALUES (?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?)
    """
    rows_for_insert = []
    for r in parsed:
        rows_for_insert.append((
            r["dedupe_key"],
            r["employee_id"], r["employee_name"], r["manager_id"], r["department"], r["location"],
            r["expense_date"], r["fiscal_year"], r["fiscal_quarter"],
            cat_map.get(r["category_name"]), r["category_name"], r["vendor"], r["description"],
            r["amount"], r["currency"], r["amount_usd"], r["status"], r["receipt_url"],
            r["source_file"], r["source_row"], r["dedupe_key"],
        ))

    inserted = await db.execute_many(insert_sql, rows_for_insert)

    await db.execute(
        """
        UPDATE ExpenseImportRuns
        SET RowsRead=?, RowsInserted=?, RowsSkipped=?, Status='ok',
            FinishedAt=SYSUTCDATETIME()
        WHERE RunId=?
        """,
        [len(raw_rows), inserted, rows_skipped, run_id],
    )

    return ImportRunResult(
        run_id=run_id,
        source_file=path.name,
        rows_read=len(raw_rows),
        rows_inserted=inserted,
        rows_skipped=rows_skipped,
        status="ok",
    )


def _cli() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Import expenses Excel sheet into Azure SQL.")
    parser.add_argument("workbook", help="Path to the .xlsx file.")
    parser.add_argument("--currency", default="USD", help="Default currency when missing in the sheet.")
    parser.add_argument("--fx", type=float, default=1.0, help="Flat FX rate to USD for non-USD rows.")
    parser.add_argument("--triggered-by", default=None, help="User identifier for audit row.")
    args = parser.parse_args()

    result = asyncio.run(
        import_expense_workbook(
            args.workbook,
            default_currency=args.currency,
            fx_to_usd=args.fx,
            triggered_by=args.triggered_by,
        )
    )
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":  # pragma: no cover
    _cli()
