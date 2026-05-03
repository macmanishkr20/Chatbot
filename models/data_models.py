"""
Pydantic models for the analytical data store (UserExpenses /
UserScoreboard / AgentUserRoles).

These mirror the SQL columns in ``sql/create_agent_tables.sql``. Used
by the Excel ETL loaders for input validation and by the agents for
typed responses.
"""
from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ── UserExpenses ─────────────────────────────────────────────────────

class UserExpenseRecord(BaseModel):
    """One UserExpenses row as ingested or returned."""
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    id: Optional[int] = Field(default=None, alias="Id")

    # ── Geography / org ──
    country_name: Optional[str] = Field(default=None, alias="CountryName")
    country_code: Optional[str] = Field(default=None, alias="CountryCode")
    company_code: Optional[str] = Field(default=None, alias="CompanyCode")
    company_code_description: Optional[str] = Field(default=None, alias="CompanyCodeDescription")
    cost_center_id: Optional[str] = Field(default=None, alias="CostCenterId")
    cost_center: Optional[str] = Field(default=None, alias="CostCenter")

    # ── Identity ──
    employee_id: str = Field(alias="EmployeeId")
    employee_name: Optional[str] = Field(default=None, alias="EmployeeName")
    home_address: Optional[str] = Field(default=None, alias="HomeAddress")
    employee_rank: Optional[str] = Field(default=None, alias="EmployeeRank")

    # ── Report ──
    report_id: Optional[str] = Field(default=None, alias="ReportId")
    report_key: Optional[int] = Field(default=None, alias="ReportKey")
    report_name: Optional[str] = Field(default=None, alias="ReportName")
    policy: Optional[str] = Field(default=None, alias="Policy")
    approval_status: Optional[str] = Field(default=None, alias="ApprovalStatus")
    approved_by: Optional[str] = Field(default=None, alias="ApprovedBy")
    payment_status: Optional[str] = Field(default=None, alias="PaymentStatus")

    # ── Dates ──
    trip_start_date: Optional[_date] = Field(default=None, alias="TripStartDate")
    trip_end_date: Optional[_date] = Field(default=None, alias="TripEndDate")
    original_submission_datetime: Optional[datetime] = Field(default=None, alias="OriginalSubmissionDateTime")
    last_submitted_datetime: Optional[datetime] = Field(default=None, alias="LastSubmittedDateTime")
    approval_status_change_datetime: Optional[datetime] = Field(default=None, alias="ApprovalStatusChangeDateTime")
    payment_status_change_date: Optional[datetime] = Field(default=None, alias="PaymentStatusChangeDate")
    transaction_date: Optional[datetime] = Field(default=None, alias="TransactionDate")

    # ── Categorisation ──
    expense_type: Optional[str] = Field(default=None, alias="ExpenseType")
    expense_sub_type1: Optional[str] = Field(default=None, alias="ExpenseSubType1")
    expense_sub_type2: Optional[str] = Field(default=None, alias="ExpenseSubType2")

    # ── Trip details ──
    origin: Optional[str] = Field(default=None, alias="Origin")
    destination: Optional[str] = Field(default=None, alias="Destination")
    from_date: Optional[_date] = Field(default=None, alias="FromDate")
    to_date: Optional[_date] = Field(default=None, alias="ToDate")
    business_purpose: Optional[str] = Field(default=None, alias="BusinessPurpose")

    # ── Money ──
    original_reimbursement_amount: Optional[Decimal] = Field(default=None, alias="OriginalReimbursementAmount")
    reimbursement_amount: Optional[Decimal] = Field(default=None, alias="ReimbursementAmount")
    reimbursement_currency: Optional[str] = Field(default=None, alias="ReimbursementCurrency")
    transaction_amount: Optional[Decimal] = Field(default=None, alias="TransactionAmount")
    transaction_currency: Optional[str] = Field(default=None, alias="TransactionCurrency")

    # ── Locations ──
    work_location_country: Optional[str] = Field(default=None, alias="WorkLocationCountry")
    work_location_region: Optional[str] = Field(default=None, alias="WorkLocationRegion")
    work_location_city: Optional[str] = Field(default=None, alias="WorkLocationCity")
    country_of_purchase: Optional[str] = Field(default=None, alias="CountryOfPurchase")
    region_of_purchase: Optional[str] = Field(default=None, alias="RegionOfPurchase")
    city_of_purchase: Optional[str] = Field(default=None, alias="CityOfPurchase")

    # ── Misc ──
    vendor: Optional[str] = Field(default=None, alias="Vendor")
    receipt_status: Optional[str] = Field(default=None, alias="ReceiptStatus")
    gl_account: Optional[str] = Field(default=None, alias="GLAccount")
    engagement_name: Optional[str] = Field(default=None, alias="EngagementName")
    engagement_code: Optional[str] = Field(default=None, alias="EngagementCode")
    engagement_percentage: Optional[Decimal] = Field(default=None, alias="EngagementPercentage")
    transaction_type: Optional[str] = Field(default=None, alias="TransactionType")
    number_of_attendees: Optional[int] = Field(default=None, alias="NumberOfAttendees")
    trip_over_3_months: Optional[str] = Field(default=None, alias="TripOver3Months")


# ── UserScoreboard ───────────────────────────────────────────────────

class UserScoreboardRecord(BaseModel):
    """One UserScoreboard row — wide format with all KPIs as columns."""
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    id: Optional[int] = Field(default=None, alias="Id")

    # ── Identity ──
    gui: Optional[str] = Field(default=None, alias="GUI")
    gpn: Optional[str] = Field(default=None, alias="GPN")
    employee_name: Optional[str] = Field(default=None, alias="EmployeeName")
    employee_id: str = Field(alias="EmployeeId")

    # ── Org ──
    country: Optional[str] = Field(default=None, alias="Country")
    sl: Optional[str] = Field(default=None, alias="SL")
    ssl: Optional[str] = Field(default=None, alias="SSL")
    current_rank: Optional[str] = Field(default=None, alias="CurrentRank")
    role: Optional[str] = Field(default=None, alias="Role")
    additional_role: Optional[str] = Field(default=None, alias="AdditionalRole")

    # ── KPIs ──
    gter: Optional[Decimal] = Field(default=None, alias="GTER")
    gter_plan: Optional[Decimal] = Field(default=None, alias="GTERPlan")
    gter_plan_achieved_pct: Optional[Decimal] = Field(default=None, alias="GTERPlanAchievedPct")
    global_margin: Optional[Decimal] = Field(default=None, alias="GlobalMargin")
    global_margin_pct: Optional[Decimal] = Field(default=None, alias="GlobalMarginPct")
    global_sales: Optional[Decimal] = Field(default=None, alias="GlobalSales")
    weighted_pipeline: Optional[Decimal] = Field(default=None, alias="WeightedPipeline")
    ter: Optional[Decimal] = Field(default=None, alias="TER")
    ansr: Optional[Decimal] = Field(default=None, alias="ANSR")
    ansr_gter_ratio: Optional[Decimal] = Field(default=None, alias="ANSRGTERRatio")
    eng_margin: Optional[Decimal] = Field(default=None, alias="EngMargin")
    eng_margin_pct: Optional[Decimal] = Field(default=None, alias="EngMarginPct")
    fytd_backlog_ter: Optional[Decimal] = Field(default=None, alias="FYTDBacklogTER")
    total_backlog_ter: Optional[Decimal] = Field(default=None, alias="TotalBacklogTER")
    utilization_pct: Optional[Decimal] = Field(default=None, alias="UtilizationPct")
    billing: Optional[Decimal] = Field(default=None, alias="Billing")
    collection: Optional[Decimal] = Field(default=None, alias="Collection")
    ar: Optional[Decimal] = Field(default=None, alias="AR")
    ar_reserve: Optional[Decimal] = Field(default=None, alias="ARReserve")
    total_nui: Optional[Decimal] = Field(default=None, alias="TotalNUI")
    aged_nui_above_180_days: Optional[Decimal] = Field(default=None, alias="AgedNUIAbove180Days")
    aged_nui_above_365_days: Optional[Decimal] = Field(default=None, alias="AgedNUIAbove365Days")
    revenue_days: Optional[Decimal] = Field(default=None, alias="RevenueDays")

    # ── Period ──
    period: Optional[str] = Field(default=None, alias="Period")
    report_date: Optional[_date] = Field(default=None, alias="ReportDate")


# ── ETL run audit ────────────────────────────────────────────────────

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
