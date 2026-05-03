"""
Static descriptions of the analytical tables that the LLM is allowed
to query.

These mirror the DDL in ``sql/create_agent_tables.sql``. Adding or
renaming a column = updating it in the DDL AND here, in the same
commit.

The descriptions are deliberately compact — they are spliced into the
agent prompts, so every extra word costs tokens. The KPI semantics for
the scoreboard are inlined so the LLM can map natural-language phrases
("highest ANSR", "weakest margin", "best utilisation") to the right
columns without guessing.
"""
from __future__ import annotations

from services.text_to_predicate import ColumnSpec, TableSchema


# ── UserExpenses ──────────────────────────────────────────────────────

EXPENSE_SCHEMA = TableSchema(
    table="UserExpenses",
    description=(
        "Per-line expense report rows from Concur, ingested from the "
        "MENA Expense Report Excel template. One row per line item on a "
        "report. Use this table for ANY question about expense totals, "
        "filters, vendors, locations, engagements, approval status, or "
        "rankings. The reimbursement currency may differ row-to-row — "
        "for cross-row totals prefer ReimbursementAmount and acknowledge "
        "the currency mix in the answer."
    ),
    default_order_by="TransactionDate",
    columns=(
        # ── Identity ──
        ColumnSpec("EmployeeId", "string", "Employee identifier (Workday/HR id).",
                   filterable=True, groupable=True),
        ColumnSpec("EmployeeName", "string", "Display name (free-text).",
                   filterable=True, groupable=True),
        ColumnSpec("EmployeeRank", "string", "Employee rank / band (e.g. Senior Manager).",
                   filterable=True, groupable=True,
                   sample_values=("Staff", "Senior", "Manager", "Senior Manager", "Partner")),

        # ── Org / cost-centre ──
        ColumnSpec("CompanyCode", "string", "ERP company code.",
                   filterable=True, groupable=True),
        ColumnSpec("CompanyCodeDescription", "string", "Human-readable company name.",
                   filterable=True, groupable=True),
        ColumnSpec("CostCenterId", "string", "Numeric cost-centre identifier.",
                   filterable=True, groupable=True),
        ColumnSpec("CostCenter", "string", "Cost-centre display name.",
                   filterable=True, groupable=True),

        # ── Geography ──
        ColumnSpec("CountryName", "string", "Employee country.",
                   filterable=True, groupable=True,
                   sample_values=("United Arab Emirates", "Saudi Arabia", "Egypt", "Qatar")),
        ColumnSpec("CountryCode", "string", "ISO country code.",
                   filterable=True, groupable=True,
                   sample_values=("AE", "SA", "EG", "QA")),
        ColumnSpec("WorkLocationCountry", "string", "Country where the work was performed.",
                   filterable=True, groupable=True),
        ColumnSpec("WorkLocationRegion", "string", "Region within the work-location country.",
                   filterable=True, groupable=True),
        ColumnSpec("WorkLocationCity", "string", "City where the work was performed.",
                   filterable=True, groupable=True),
        ColumnSpec("CountryOfPurchase", "string", "Country where the expense was incurred.",
                   filterable=True, groupable=True),
        ColumnSpec("CityOfPurchase", "string", "City where the expense was incurred.",
                   filterable=True, groupable=True),

        # ── Report / engagement linkage ──
        ColumnSpec("ReportId", "string", "Concur report identifier.",
                   filterable=True, groupable=True),
        ColumnSpec("ReportName", "string", "Report title.",
                   filterable=True, groupable=True),
        ColumnSpec("Policy", "string", "Concur policy name applied to the report.",
                   filterable=True, groupable=True),
        ColumnSpec("EngagementCode", "string", "Engagement / project code.",
                   filterable=True, groupable=True),
        ColumnSpec("EngagementName", "string", "Engagement display name.",
                   filterable=True, groupable=True),
        ColumnSpec("EngagementPercentage", "decimal", "% of the line allocated to the engagement.",
                   filterable=True, aggregatable=True),

        # ── Lifecycle / status ──
        ColumnSpec("ApprovalStatus", "string", "Approval lifecycle state.",
                   filterable=True, groupable=True,
                   sample_values=("Submitted", "Approved", "Pending", "Rejected")),
        ColumnSpec("ApprovedBy", "string", "Approver display name.",
                   filterable=True, groupable=True),
        ColumnSpec("PaymentStatus", "string", "Payment lifecycle state.",
                   filterable=True, groupable=True,
                   sample_values=("Paid", "Pending Payment", "Not Paid")),
        ColumnSpec("ReceiptStatus", "string", "Receipt attachment status.",
                   filterable=True, groupable=True),

        # ── Dates ──
        ColumnSpec("TransactionDate", "date",
                   "Date the expense was incurred (PRIMARY date for FY/period filters).",
                   filterable=True, groupable=True,
                   sample_values=("2025-08-15", "2026-02-03")),
        ColumnSpec("TripStartDate", "date", "Trip start date when applicable.",
                   filterable=True, groupable=False),
        ColumnSpec("TripEndDate", "date", "Trip end date when applicable.",
                   filterable=True, groupable=False),
        ColumnSpec("FromDate", "date", "Generic date-range start (e.g. per-diem expenses).",
                   filterable=True, groupable=False),
        ColumnSpec("ToDate", "date", "Generic date-range end.",
                   filterable=True, groupable=False),
        ColumnSpec("OriginalSubmissionDateTime", "date", "First time the expense was submitted.",
                   filterable=True, groupable=False),
        ColumnSpec("LastSubmittedDateTime", "date", "Most recent submission timestamp.",
                   filterable=True, groupable=False),

        # ── Categorisation ──
        ColumnSpec("ExpenseType", "string", "Top-level expense category.",
                   filterable=True, groupable=True,
                   sample_values=("Air Travel", "Lodging", "Meals", "Ground Transport", "Office Supplies")),
        ColumnSpec("ExpenseSubType1", "string", "Sub-category level 1.",
                   filterable=True, groupable=True),
        ColumnSpec("ExpenseSubType2", "string", "Sub-category level 2.",
                   filterable=True, groupable=True),
        ColumnSpec("Vendor", "string", "Merchant / supplier name.",
                   filterable=True, groupable=True),
        ColumnSpec("BusinessPurpose", "string", "Free-text business purpose narrative.",
                   filterable=True, groupable=False),
        ColumnSpec("TransactionType", "string", "Transaction class (e.g. Cash, Card).",
                   filterable=True, groupable=True),

        # ── Money ──
        ColumnSpec("OriginalReimbursementAmount", "decimal",
                   "Original reimbursement amount before any adjustments.",
                   filterable=True, aggregatable=True),
        ColumnSpec("ReimbursementAmount", "decimal",
                   "Final reimbursement amount in ReimbursementCurrency. PRIMARY measure for spend totals.",
                   filterable=True, aggregatable=True),
        ColumnSpec("ReimbursementCurrency", "string",
                   "Currency of ReimbursementAmount (ISO-4217).",
                   filterable=True, groupable=True,
                   sample_values=("USD", "AED", "SAR", "EGP", "EUR")),
        ColumnSpec("TransactionAmount", "decimal",
                   "Amount in the original transaction currency (vendor invoice).",
                   filterable=True, aggregatable=True),
        ColumnSpec("TransactionCurrency", "string",
                   "Currency of TransactionAmount.",
                   filterable=True, groupable=True),

        # ── Misc ──
        ColumnSpec("Origin", "string", "Trip origin (for travel rows).",
                   filterable=True, groupable=True),
        ColumnSpec("Destination", "string", "Trip destination (for travel rows).",
                   filterable=True, groupable=True),
        ColumnSpec("NumberOfAttendees", "int", "Attendee count for entertainment / meals.",
                   filterable=True, aggregatable=True),
        ColumnSpec("TripOver3Months", "string", "'Y'/'N' flag for long trips.",
                   filterable=True, groupable=True),
        ColumnSpec("GLAccount", "string", "GL account assigned to the line.",
                   filterable=True, groupable=True),
    ),
)


# ── UserScoreboard ────────────────────────────────────────────────────

# KPI semantics — spliced into the schema description so the LLM can
# map fuzzy phrases to the right column. Lifted verbatim from the
# definitions you supplied.
_KPI_SEMANTICS = """\
KPI definitions (use these to map natural-language phrases to columns):
- GTER: Global Total Engagement Revenue — total of all TER excluding InterFirm Billing (IFB).
- GTERPlan: Planned/target value for GTER for the period.
- GTERPlanAchievedPct: Actual GTER as a % of GTERPlan ("plan attainment").
- GlobalMargin: Margin after deducting direct + technology costs from ANSR.
- GlobalMarginPct: GlobalMargin / ANSR (%).
- GlobalSales: Total value of new client contracts/deals signed in the period (forward-looking).
- WeightedPipeline: Probability-weighted value of qualified open pipeline.
- TER: Total Engagement Revenue = ANSR + Expenses (the full client fee).
- ANSR: Adjusted Net Standard Revenue = NSR × (1 + EAF%). Used to compute GlobalMargin.
- ANSRGTERRatio: ANSR / GTER (pricing & delivery mix quality).
- EngMargin: Engagement-level margin (profit on the engagement after direct costs).
- EngMarginPct: EngMargin as a % of NER/ANSR — engagement-level profitability.
- FYTDBacklogTER: Year-to-date backlog (contracted work not yet billed within current FY).
- TotalBacklogTER: Lifetime backlog across current + future periods.
- UtilizationPct: % of working hours charged to client work (productivity).
- Billing: Amount invoiced to clients during the period.
- Collection: Cash received against billed invoices.
- AR: Accounts Receivable (outstanding invoiced amounts).
- ARReserve: Provision for AR that may not be collectible.
- TotalNUI: Net Unbilled Inventory (revenue earned but not yet invoiced).
- AgedNUIAbove180Days: NUI outstanding > 180 days (billing risk).
- AgedNUIAbove365Days: NUI outstanding > 365 days (high billing risk).
- RevenueDays: Days from work performed → revenue / cash (billing efficiency).

Common phrasing mappings:
- "achievement %" / "plan attainment" → GTERPlanAchievedPct
- "margin %" / "margin rate" → GlobalMarginPct (firm-wide) or EngMarginPct (per-engagement)
- "best/highest performer" → typically GTERPlanAchievedPct, ANSR, or UtilizationPct depending on context — clarify if ambiguous
- "billing risk" / "old NUI" → AgedNUIAbove180Days or AgedNUIAbove365Days
- "FY26" filter → use Period LIKE 'FY26%' (Period values look like "FY26 P9")
- "FY26 P9" filter → use Period = 'FY26 P9' exactly
"""

SCOREBOARD_SCHEMA = TableSchema(
    table="UserScoreboard",
    description=(
        "Per-employee, per-period scoreboard from the MENA Scorecard "
        "template. Wide format: one row per (EmployeeId, Period) with all "
        "KPIs as columns. "
        "Use this table for any ranking / aggregation / comparison of "
        "performance metrics. Period values look like 'FY26 P9' "
        "(fiscal year + period number); filter on Period or use "
        "ReportDate for date-based filters.\n\n"
        + _KPI_SEMANTICS
    ),
    default_order_by="ReportDate",
    columns=(
        # ── Identity ──
        ColumnSpec("EmployeeId", "string", "Employee identifier (mapped from GUI).",
                   filterable=True, groupable=True),
        ColumnSpec("EmployeeName", "string", "Display name.",
                   filterable=True, groupable=True),
        ColumnSpec("GUI", "string", "Global User Identifier from the source workbook.",
                   filterable=True, groupable=True),
        ColumnSpec("GPN", "string", "Global Personnel Number.",
                   filterable=True, groupable=True),

        # ── Organisation ──
        ColumnSpec("Country", "string", "Employee country.",
                   filterable=True, groupable=True,
                   sample_values=("United Arab Emirates", "Saudi Arabia", "Egypt")),
        ColumnSpec("SL", "string", "Service Line.",
                   filterable=True, groupable=True,
                   sample_values=("Assurance", "Consulting", "Tax", "Strategy & Transactions")),
        ColumnSpec("SSL", "string", "Sub-Service Line.",
                   filterable=True, groupable=True),
        ColumnSpec("CurrentRank", "string", "Employee rank / band at scorecard date.",
                   filterable=True, groupable=True,
                   sample_values=("Senior", "Manager", "Senior Manager", "Partner")),
        ColumnSpec("Role", "string", "Primary role description.",
                   filterable=True, groupable=True),
        ColumnSpec("AdditionalRole", "string", "Secondary role description.",
                   filterable=True, groupable=True),

        # ── Period ──
        ColumnSpec("Period", "string",
                   "Fiscal period label, e.g. 'FY26 P9'. Use LIKE for FY filters and = for exact period.",
                   filterable=True, groupable=True,
                   sample_values=("FY25 P12", "FY26 P1", "FY26 P9")),
        ColumnSpec("ReportDate", "date",
                   "Date of the scorecard snapshot (use for date-range filters).",
                   filterable=True, groupable=True),

        # ── KPIs (numeric measures) ──
        ColumnSpec("GTER", "decimal", "Global Total Engagement Revenue (excludes IFB).",
                   filterable=True, aggregatable=True),
        ColumnSpec("GTERPlan", "decimal", "Plan / target value for GTER.",
                   filterable=True, aggregatable=True),
        ColumnSpec("GTERPlanAchievedPct", "decimal",
                   "GTER actuals as a percentage of GTERPlan.",
                   filterable=True, aggregatable=True),
        ColumnSpec("GlobalMargin", "decimal", "Margin after direct + tech costs from ANSR.",
                   filterable=True, aggregatable=True),
        ColumnSpec("GlobalMarginPct", "decimal", "GlobalMargin / ANSR (%).",
                   filterable=True, aggregatable=True),
        ColumnSpec("GlobalSales", "decimal", "Value of new client contracts signed.",
                   filterable=True, aggregatable=True),
        ColumnSpec("WeightedPipeline", "decimal", "Probability-weighted open pipeline value.",
                   filterable=True, aggregatable=True),
        ColumnSpec("TER", "decimal", "Total Engagement Revenue = ANSR + expenses.",
                   filterable=True, aggregatable=True),
        ColumnSpec("ANSR", "decimal", "Adjusted Net Standard Revenue = NSR × (1 + EAF%).",
                   filterable=True, aggregatable=True),
        ColumnSpec("ANSRGTERRatio", "decimal", "ANSR / GTER ratio.",
                   filterable=True, aggregatable=True),
        ColumnSpec("EngMargin", "decimal", "Engagement margin (profit per engagement).",
                   filterable=True, aggregatable=True),
        ColumnSpec("EngMarginPct", "decimal", "EngMargin as % of NER/ANSR.",
                   filterable=True, aggregatable=True),
        ColumnSpec("FYTDBacklogTER", "decimal",
                   "Year-to-date backlog (contracted, unbilled within current FY).",
                   filterable=True, aggregatable=True),
        ColumnSpec("TotalBacklogTER", "decimal", "Lifetime contracted but undelivered backlog.",
                   filterable=True, aggregatable=True),
        ColumnSpec("UtilizationPct", "decimal", "% of available hours charged to clients.",
                   filterable=True, aggregatable=True),
        ColumnSpec("Billing", "decimal", "Amount invoiced to clients during the period.",
                   filterable=True, aggregatable=True),
        ColumnSpec("Collection", "decimal", "Cash received against billed invoices.",
                   filterable=True, aggregatable=True),
        ColumnSpec("AR", "decimal", "Accounts Receivable — outstanding invoiced.",
                   filterable=True, aggregatable=True),
        ColumnSpec("ARReserve", "decimal", "Provision for uncollectible AR.",
                   filterable=True, aggregatable=True),
        ColumnSpec("TotalNUI", "decimal", "Net Unbilled Inventory — earned but not invoiced.",
                   filterable=True, aggregatable=True),
        ColumnSpec("AgedNUIAbove180Days", "decimal", "NUI outstanding > 180 days.",
                   filterable=True, aggregatable=True),
        ColumnSpec("AgedNUIAbove365Days", "decimal", "NUI outstanding > 365 days (high risk).",
                   filterable=True, aggregatable=True),
        ColumnSpec("RevenueDays", "decimal", "Days from work performed → revenue/cash.",
                   filterable=True, aggregatable=True),
    ),
)
