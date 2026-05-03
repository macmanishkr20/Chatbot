"""
Fiscal-year helpers — single source of truth for date → FY/FQ mapping.

EY's MENA fiscal year runs from **July 1** through **June 30** (standard
EY global convention). FY26 covers Jul 2025 – Jun 2026.

Override by setting ``FISCAL_YEAR_START_MONTH`` env var (1–12) if a
different convention is needed for testing or another business unit.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Tuple


_FISCAL_START_MONTH = int(os.getenv("FISCAL_YEAR_START_MONTH", "7"))
if not 1 <= _FISCAL_START_MONTH <= 12:
    raise ValueError(
        f"FISCAL_YEAR_START_MONTH must be 1-12, got {_FISCAL_START_MONTH}"
    )


def derive_fiscal_year(d: date | datetime) -> str:
    """Return ``FYNN`` (e.g. ``FY26``) for the given date.

    Convention: a fiscal year is named after the calendar year in which
    it ENDS. So Jul 2025 – Jun 2026 → FY26.
    """
    if isinstance(d, datetime):
        d = d.date()
    if d.month >= _FISCAL_START_MONTH:
        end_year = d.year + 1
    else:
        end_year = d.year
    return f"FY{end_year % 100:02d}"


def derive_fiscal_quarter(d: date | datetime) -> str:
    """Return ``Q1``-``Q4`` for the given date based on the fiscal year.

    Q1 = first 3 months of the fiscal year, Q2 next 3, etc.
    """
    if isinstance(d, datetime):
        d = d.date()
    months_into_fy = (d.month - _FISCAL_START_MONTH) % 12
    quarter = (months_into_fy // 3) + 1
    return f"Q{quarter}"


def fiscal_year_range(fy: str) -> Tuple[date, date]:
    """Return (inclusive_start, inclusive_end) for a fiscal-year label.

    >>> fiscal_year_range("FY26")
    (datetime.date(2025, 7, 1), datetime.date(2026, 6, 30))
    """
    fy = fy.strip().upper()
    if not (fy.startswith("FY") and len(fy) >= 3):
        raise ValueError(f"Invalid fiscal year label: {fy!r}")
    yy = int(fy[2:])
    end_year = 2000 + yy
    start_year = end_year - 1
    start = date(start_year, _FISCAL_START_MONTH, 1)
    # End is the day before the next FY's start
    end_month = _FISCAL_START_MONTH - 1 or 12
    end_year_actual = end_year if _FISCAL_START_MONTH != 1 else end_year - 1
    # Last day of end_month in end_year_actual
    if end_month == 12:
        next_month_first = date(end_year_actual + 1, 1, 1)
    else:
        next_month_first = date(end_year_actual, end_month + 1, 1)
    end = date.fromordinal(next_month_first.toordinal() - 1)
    return start, end


def fiscal_quarter_range(fy: str, fq: str) -> Tuple[date, date]:
    """Return (inclusive_start, inclusive_end) for a fiscal quarter."""
    fq = fq.strip().upper()
    if not (fq.startswith("Q") and fq[1:].isdigit()):
        raise ValueError(f"Invalid fiscal quarter label: {fq!r}")
    q = int(fq[1:])
    if not 1 <= q <= 4:
        raise ValueError(f"Quarter must be Q1-Q4, got {fq!r}")
    fy_start, fy_end = fiscal_year_range(fy)
    # Quarter offsets in months from fy_start
    months_offset = (q - 1) * 3
    # Compute start
    sm = ((fy_start.month - 1 + months_offset) % 12) + 1
    sy = fy_start.year + ((fy_start.month - 1 + months_offset) // 12)
    start = date(sy, sm, 1)
    # End = first day of next quarter - 1
    em_offset = months_offset + 3
    em = ((fy_start.month - 1 + em_offset) % 12) + 1
    ey = fy_start.year + ((fy_start.month - 1 + em_offset) // 12)
    next_q_first = date(ey, em, 1)
    end = date.fromordinal(next_q_first.toordinal() - 1)
    # Clamp to fiscal-year bounds (defensive — Q4 should naturally land on fy_end)
    if end > fy_end:
        end = fy_end
    return start, end
