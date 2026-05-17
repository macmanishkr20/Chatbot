"""
UserExpenses table schema — single source of truth for the Expense agent.

Mirrors ``sql/create_agent_tables.sql`` exactly. Column metadata is what
the predicate-planner LLM sees: every column the agent is allowed to
filter / aggregate / select must be declared here.

Columns flagged ``aggregatable`` are numeric measures (amounts).
Columns flagged ``groupable`` are dimensions (employee, country, …).
``EmployeeId`` is the row-level-security key — security_predicates filter
on it for non-admin ranks.
"""
from __future__ import annotations

from agents._base.sql_planner.plan import ColumnSpec, TableSchema


EXPENSE_TABLE = "UserExpenses"


EXPENSE_SCHEMA = TableSchema(
    table=EXPENSE_TABLE,
    description=(
        "Per-line travel & business expense claims for EY MENA employees. "
        "One row = one expense line item on a submitted report. "
        "Key: EmployeeId (= user's GUI). Amounts are in ReimbursementCurrency."
    ),
    default_order_by="TransactionDate",
    columns=(
        # ── Identity / RLS keys ──
        ColumnSpec("EmployeeId", "string",
                   "GUI / Employee ID of the claimant",
                   groupable=True),
        ColumnSpec("EmployeeName", "string",
                   "Display name of the claimant",
                   sample_values=("Paton, Richard Alasdair", "Kozlovski, Art"),
                   groupable=True),
        ColumnSpec("EmployeeRank", "string",
                   "Rank / grade of the employee",
                   sample_values=("11-Partner/Principal", "42-Senior", "32-Manager"),
                   groupable=True),
        # ── Country / org dimensions ──
        ColumnSpec("CountryName", "string",
                   "Country of the booking entity",
                   sample_values=("United Arab Emirates", "Saudi Arabia", "Bahrain"),
                   groupable=True),
        ColumnSpec("CountryCode", "string",
                   "ISO-2 country code",
                   sample_values=("AE", "SA", "BH"),
                   groupable=True),
        ColumnSpec("CompanyCode", "string",
                   "Booking company code",
                   sample_values=("AE11", "SA09", "BH09"),
                   groupable=True),
        ColumnSpec("CostCenterId", "string", "Cost-center identifier", groupable=True),
        ColumnSpec("CostCenter", "string", "Cost-center description", groupable=True),
        # ── Report status ──
        ColumnSpec("ReportId", "string", "Concur report identifier"),
        ColumnSpec("ReportName", "string", "Display name of the report"),
        ColumnSpec("Policy", "string",
                   "Expense policy applied",
                   sample_values=("*EY AE General Expense Report", "*EY SA General Expense Report"),
                   groupable=True),
        ColumnSpec("ApprovalStatus", "string",
                   "Approval state",
                   sample_values=("Approved", "In Audit", "Pending", "Rejected"),
                   groupable=True),
        ColumnSpec("PaymentStatus", "string",
                   "Payment state",
                   sample_values=("Paid", "Pending", "Cancelled"),
                   groupable=True),
        # ── Dates ──
        ColumnSpec("TripStartDate", "date", "Start of the trip / engagement"),
        ColumnSpec("TripEndDate", "date", "End of the trip / engagement"),
        ColumnSpec("OriginalSubmissionDateTime", "date", "First submission timestamp"),
        ColumnSpec("LastSubmittedDateTime", "date", "Latest re-submission timestamp"),
        ColumnSpec("TransactionDate", "date",
                   "When the expense was incurred — use this for fiscal-period filters"),
        # ── Categorisation ──
        ColumnSpec("ExpenseType", "string",
                   "Top-level expense category",
                   sample_values=("Air Travel", "Hotel", "Meals", "Ground Transport"),
                   groupable=True),
        ColumnSpec("ExpenseSubType1", "string", "Secondary category", groupable=True),
        ColumnSpec("ExpenseSubType2", "string", "Tertiary category", groupable=True),
        ColumnSpec("Origin", "string", "Origin location for travel"),
        ColumnSpec("Destination", "string", "Destination location for travel"),
        ColumnSpec("Vendor", "string", "Vendor / supplier", groupable=True),
        ColumnSpec("BusinessPurpose", "string", "Free-text justification"),
        # ── Amounts (measures) ──
        ColumnSpec("OriginalReimbursementAmount", "decimal",
                   "Reimbursement amount in original currency",
                   aggregatable=True),
        ColumnSpec("ReimbursementAmount", "decimal",
                   "Reimbursement amount in EUR equivalent — primary measure",
                   aggregatable=True),
        ColumnSpec("ReimbursementCurrency", "string",
                   "Original currency code",
                   sample_values=("AED", "SAR", "BHD", "USD"),
                   groupable=True),
        ColumnSpec("TransactionAmount", "decimal",
                   "Original transaction amount before reimbursement adjustments",
                   aggregatable=True),
        ColumnSpec("TransactionCurrency", "string", "Transaction currency code"),
        # ── Locations ──
        ColumnSpec("WorkLocationCountry", "string", "Work location country", groupable=True),
        ColumnSpec("WorkLocationCity",    "string", "Work location city",    groupable=True),
        ColumnSpec("CountryOfPurchase",   "string", "Country where charge was incurred", groupable=True),
        ColumnSpec("CityOfPurchase",      "string", "City where charge was incurred"),
        # ── Engagement ──
        ColumnSpec("EngagementName", "string", "Engagement / project name"),
        ColumnSpec("EngagementCode", "string", "Engagement code", groupable=True),
        ColumnSpec("EngagementPercentage", "decimal",
                   "% of this line charged to the engagement", aggregatable=True),
        ColumnSpec("NumberOfAttendees", "int", "Attendee count (for client meals)",
                   aggregatable=True),
    ),
    # Lightweight synonyms — user-facing words → schema values
    synonyms={
        "ExpenseType": {
            "flight":       ["Air Travel"],
            "flights":      ["Air Travel"],
            "airfare":      ["Air Travel"],
            "plane":        ["Air Travel"],
            "hotel":        ["Hotel", "Lodging"],
            "stay":         ["Hotel", "Lodging"],
            "taxi":         ["Ground Transport", "Taxi"],
            "uber":         ["Ground Transport", "Taxi"],
            "transport":    ["Ground Transport"],
            "food":         ["Meals"],
            "dinner":       ["Meals"],
            "client meal":  ["Client Entertainment", "Meals"],
        },
        "ApprovalStatus": {
            "approved":   ["Approved"],
            "pending":    ["Pending", "In Audit"],
            "rejected":   ["Rejected"],
        },
    },
)
