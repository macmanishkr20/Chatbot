"""
Excel → Scoreboards ETL loader. Same idempotent pattern as the expense
loader.

Excel column mapping (case-insensitive, trimmed):
    Required: employee_id, fiscal_year, metric_name | metric, score
    Optional: employee_name, manager_id, department, location,
              fiscal_quarter | quarter, max_score, rank, notes
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

from models.data_models import ImportRunResult
from services.data_db import DataDB

logger = logging.getLogger(__name__)


_DEFAULT_COLUMN_MAP: dict[str, tuple[str, ...]] = {
    "employee_id":    ("employee_id", "employee id", "emp_id", "empid"),
    "employee_name":  ("employee_name", "employee name", "name"),
    "manager_id":     ("manager_id", "manager id"),
    "department":     ("department", "dept", "team"),
    "location":       ("location", "office", "country"),
    "fiscal_year":    ("fiscal_year", "fy", "year"),
    "fiscal_quarter": ("fiscal_quarter", "quarter", "fq"),
    "metric_name":    ("metric_name", "metric", "kpi"),
    "score":          ("score", "value", "points"),
    "max_score":      ("max_score", "max", "out_of"),
    "rank":           ("rank", "rank_in_group", "position"),
    "notes":          ("notes", "comments", "remarks"),
}


def _normalise_columns(headers: list[str]) -> dict[str, str]:
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


def _parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _make_dedupe_key(row: Mapping[str, Any], source_file: str) -> str:
    canonical = "|".join([
        str(row.get("employee_id") or "").strip().lower(),
        str(row.get("fiscal_year") or "").strip().upper(),
        str(row.get("fiscal_quarter") or "").strip().upper(),
        str(row.get("metric_name") or "").strip().lower(),
        source_file,
    ])
    return hashlib.sha1(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()


def _read_workbook(path: Path) -> tuple[list[str], list[list[Any]]]:
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
    headers = [str(h) if h is not None else "" for h in rows[0]]
    return headers, [list(r) for r in rows[1:]]


async def import_scoreboard_workbook(
    workbook_path: str | Path,
    *,
    triggered_by: str | None = None,
    column_map: dict[str, str] | None = None,
) -> ImportRunResult:
    """Load an Excel scoreboard workbook into the Scoreboards table."""
    path = Path(workbook_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)

    db = DataDB()
    await db.ensure()

    run_id_row = await db.fetchone(
        """
        INSERT INTO ScoreboardImportRuns (SourceFile, TriggeredBy)
        OUTPUT INSERTED.RunId
        VALUES (?, ?)
        """,
        [str(path.name), triggered_by],
    )
    run_id = (run_id_row or {}).get("RunId")

    headers, raw_rows = _read_workbook(path)
    resolved_cols = column_map or _normalise_columns(headers)
    required = {"employee_id", "fiscal_year", "metric_name", "score"}
    if not required.issubset(resolved_cols):
        await db.execute(
            """
            UPDATE ScoreboardImportRuns
            SET Status='failed', ErrorMessage=?, FinishedAt=SYSUTCDATETIME()
            WHERE RunId=?
            """,
            [f"Missing required columns. Found: {list(resolved_cols)}", run_id],
        )
        raise ValueError(
            f"Workbook is missing required columns "
            f"(employee_id / fiscal_year / metric_name / score). "
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

    parsed: list[dict[str, Any]] = []
    rows_skipped = 0
    for i, raw in enumerate(raw_rows, start=2):
        emp = col(raw, "employee_id")
        fy = col(raw, "fiscal_year")
        metric = col(raw, "metric_name")
        score = _parse_decimal(col(raw, "score"))
        if not emp or not fy or not metric or score is None:
            rows_skipped += 1
            continue

        record = {
            "employee_id": str(emp).strip(),
            "employee_name": col(raw, "employee_name"),
            "manager_id": col(raw, "manager_id"),
            "department": col(raw, "department"),
            "location": col(raw, "location"),
            "fiscal_year": str(fy).strip().upper(),
            "fiscal_quarter": (str(col(raw, "fiscal_quarter")).strip().upper() or None) if col(raw, "fiscal_quarter") else None,
            "metric_name": str(metric).strip(),
            "score": score.quantize(Decimal("0.01")),
            "max_score": (_parse_decimal(col(raw, "max_score")) or None),
            "rank_in_group": _parse_int(col(raw, "rank")),
            "notes": col(raw, "notes"),
            "source_file": path.name,
            "source_row": i,
        }
        record["dedupe_key"] = _make_dedupe_key(record, path.name)
        parsed.append(record)

    insert_sql = """
        IF NOT EXISTS (SELECT 1 FROM Scoreboards WHERE DedupeKey = ?)
        INSERT INTO Scoreboards
            (EmployeeId, EmployeeName, ManagerId, Department, Location,
             FiscalYear, FiscalQuarter, MetricName,
             Score, MaxScore, RankInGroup, Notes,
             SourceFile, SourceRow, DedupeKey)
        VALUES (?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?)
    """
    rows_for_insert = []
    for r in parsed:
        rows_for_insert.append((
            r["dedupe_key"],
            r["employee_id"], r["employee_name"], r["manager_id"], r["department"], r["location"],
            r["fiscal_year"], r["fiscal_quarter"], r["metric_name"],
            r["score"], r["max_score"], r["rank_in_group"], r["notes"],
            r["source_file"], r["source_row"], r["dedupe_key"],
        ))

    inserted = await db.execute_many(insert_sql, rows_for_insert)

    await db.execute(
        """
        UPDATE ScoreboardImportRuns
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
    parser = argparse.ArgumentParser(description="Import scoreboards Excel sheet into Azure SQL.")
    parser.add_argument("workbook", help="Path to the .xlsx file.")
    parser.add_argument("--triggered-by", default=None)
    args = parser.parse_args()
    result = asyncio.run(import_scoreboard_workbook(args.workbook, triggered_by=args.triggered_by))
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":  # pragma: no cover
    _cli()
