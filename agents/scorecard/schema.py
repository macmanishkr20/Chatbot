"""
UserScoreboard table schema — single source of truth for the Scorecard agent.

Mirrors ``sql/create_agent_tables.sql`` exactly. The PascalCase column
names align with the DDL. ``EmployeeId`` is the row-level-security key
(equal to the user's GUI).

KPI semantics are documented inline so the planner LLM can map natural-
language phrases ("plan attainment", "billing risk", "pricing & delivery
mix") to the right column.
"""
from __future__ import annotations

from agents._base.sql_planner.plan import ColumnSpec, TableSchema


SCORECARD_TABLE = "UserScoreboard"


# Columns surfaced in the default "show my scorecard" view (matches the
# label set on the user's reference card; image-order preserved).
SCORECARD_DEFAULT_VIEW_COLUMNS: tuple[str, ...] = (
    "EmployeeName",
    "WeightedPipeline",
    "GlobalSales",
    "GTER",
    "TER",
    "ANSR",
    "ANSRGTERRatio",
    "EngMargin",
    "EngMarginPct",
    "TotalBacklogTER",
    "AR",
    "TotalNUI",
    "UtilizationPct",
    "Period",
)


SCORECARD_SCHEMA = TableSchema(
    table=SCORECARD_TABLE,
    description=(
        "Per-employee performance snapshot for the EY MENA Scorecard. "
        "One row = one employee × one reporting period. "
        "Key: EmployeeId (= user's GUI). Monetary KPIs are in the firm's "
        "reporting currency. Percentages are stored as decimals (0.7846 = 78.46%)."
    ),
    default_order_by="GTER",
    columns=(
        # ── Identity / RLS ──
        ColumnSpec("EmployeeId",   "string", "GUI / Employee ID", groupable=True),
        ColumnSpec("GUI",          "string", "Same as EmployeeId — legacy alias", groupable=True),
        ColumnSpec("GPN",          "string", "Global Personnel Number", groupable=True),
        ColumnSpec("EmployeeName", "string", "Display name", groupable=True),
        # ── Org dimensions ──
        ColumnSpec("Country",        "string", "Country of work", groupable=True,
                   sample_values=("UAE", "Saudi Arabia", "Bahrain", "Kuwait")),
        ColumnSpec("SL",             "string", "Service Line",      groupable=True),
        ColumnSpec("SSL",            "string", "Sub-Service Line",  groupable=True),
        ColumnSpec("CurrentRank",    "string", "Employee rank",     groupable=True,
                   sample_values=("Partner", "Manager", "Senior", "Staff")),
        ColumnSpec("Role",           "string", "Primary role",      groupable=True),
        ColumnSpec("AdditionalRole", "string", "Secondary role",    groupable=True),
        # ── Period / snapshot ──
        ColumnSpec("Period",     "fy",   "Reporting period label, e.g. 'FY26 P9'",
                   sample_values=("FY26 P9", "FY26 P8", "FY25 P12"), groupable=True),
        ColumnSpec("ReportDate", "date", "Date of the scorecard snapshot"),
        # ── KPIs (numeric, all aggregatable) ──
        ColumnSpec("GTER", "decimal",
                   "Global Total Engagement Revenue — total of all TER excluding "
                   "InterFirm Billing (IFB).",
                   aggregatable=True),
        ColumnSpec("GTERPlan", "decimal",
                   "Planned / target GTER for the period.",
                   aggregatable=True),
        ColumnSpec("GTERPlanAchievedPct", "decimal",
                   "Actual GTER as a % of GTERPlan (plan attainment, 0.7846 = 78.46%).",
                   aggregatable=True),
        ColumnSpec("GlobalMargin", "decimal",
                   "Margin after deducting direct + technology costs from ANSR.",
                   aggregatable=True),
        ColumnSpec("GlobalMarginPct", "decimal",
                   "GlobalMargin / ANSR (%).",
                   aggregatable=True),
        ColumnSpec("GlobalSales", "decimal",
                   "Total value of new client contracts/deals signed in the period "
                   "(forward-looking).",
                   aggregatable=True),
        ColumnSpec("WeightedPipeline", "decimal",
                   "Probability-weighted value of qualified open pipeline.",
                   aggregatable=True),
        ColumnSpec("TER", "decimal",
                   "Total Engagement Revenue = ANSR + Expenses (full client fee).",
                   aggregatable=True),
        ColumnSpec("ANSR", "decimal",
                   "Adjusted Net Standard Revenue = NSR × (1 + EAF%). Drives GlobalMargin.",
                   aggregatable=True),
        ColumnSpec("ANSRGTERRatio", "decimal",
                   "ANSR / GTER (pricing & delivery mix quality).",
                   aggregatable=True),
        ColumnSpec("EngMargin", "decimal",
                   "Engagement-level margin (profit after direct costs).",
                   aggregatable=True),
        ColumnSpec("EngMarginPct", "decimal",
                   "EngMargin as a % of NER/ANSR (engagement profitability).",
                   aggregatable=True),
        ColumnSpec("FYTDBacklogTER", "decimal",
                   "Year-to-date backlog: contracted work not yet billed within the current FY.",
                   aggregatable=True),
        ColumnSpec("TotalBacklogTER", "decimal",
                   "Lifetime backlog across current + future periods.",
                   aggregatable=True),
        ColumnSpec("UtilizationPct", "decimal",
                   "% of working hours charged to client work (productivity).",
                   aggregatable=True),
        ColumnSpec("Billing", "decimal",
                   "Amount invoiced to clients during the period.",
                   aggregatable=True),
        ColumnSpec("Collection", "decimal",
                   "Cash received against billed invoices.",
                   aggregatable=True),
        ColumnSpec("AR", "decimal",
                   "Accounts Receivable (outstanding invoiced amounts).",
                   aggregatable=True),
        ColumnSpec("ARReserve", "decimal",
                   "Provision for AR that may not be collectible.",
                   aggregatable=True),
        ColumnSpec("TotalNUI", "decimal",
                   "Net Unbilled Inventory — revenue earned but not yet invoiced.",
                   aggregatable=True),
        ColumnSpec("AgedNUIAbove180Days", "decimal",
                   "NUI outstanding > 180 days (billing risk).",
                   aggregatable=True),
        ColumnSpec("AgedNUIAbove365Days", "decimal",
                   "NUI outstanding > 365 days (high billing risk).",
                   aggregatable=True),
        ColumnSpec("RevenueDays", "decimal",
                   "Days from work performed → revenue/cash (billing efficiency).",
                   aggregatable=True),
    ),
    synonyms={
        "Country": {
            "uae": ["UAE", "United Arab Emirates"],
            "ksa": ["Saudi Arabia", "KSA"],
            "saudi": ["Saudi Arabia"],
        },
    },
)
