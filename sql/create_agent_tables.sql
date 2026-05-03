-- Multi-Agent Extension: Data tables for Expense, Scoreboard, and Role-based access
-- Run against the same Azure SQL database used by the chatbot.
-- Column structures derived from the actual Excel templates.

-- ── UserExpenses ──
-- Source: "MENA Expense Report" Excel (77 columns — key columns below)
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='UserExpenses' AND xtype='U')
CREATE TABLE UserExpenses (
    Id                          INT IDENTITY(1,1) PRIMARY KEY,
    CountryName                 NVARCHAR(100),
    CountryCode                 NVARCHAR(10),
    CompanyCode                 NVARCHAR(20),
    CompanyCodeDescription      NVARCHAR(200),
    CostCenterId                NVARCHAR(50),
    CostCenter                  NVARCHAR(200),
    EmployeeId                  NVARCHAR(100) NOT NULL,
    EmployeeName                NVARCHAR(200),
    HomeAddress                 NVARCHAR(500),
    EmployeeRank                NVARCHAR(100),
    ReportId                    NVARCHAR(100),
    ReportKey                   BIGINT,
    ReportName                  NVARCHAR(200),
    Policy                      NVARCHAR(200),
    ApprovalStatus              NVARCHAR(50),
    ApprovedBy                  NVARCHAR(200),
    PaymentStatus               NVARCHAR(50),
    TripStartDate               DATE,
    TripEndDate                 DATE,
    OriginalSubmissionDateTime  DATETIME2,
    LastSubmittedDateTime        DATETIME2,
    ApprovalStatusChangeDateTime DATETIME2,
    PaymentStatusChangeDate     DATETIME2,
    TransactionDate             DATETIME2,
    ExpenseType                 NVARCHAR(100),
    ExpenseSubType1             NVARCHAR(100),
    ExpenseSubType2             NVARCHAR(100),
    Origin                      NVARCHAR(200),
    Destination                 NVARCHAR(200),
    FromDate                    DATE,
    ToDate                      DATE,
    BusinessPurpose             NVARCHAR(500),
    OriginalReimbursementAmount DECIMAL(18,2),
    ReimbursementAmount         DECIMAL(18,2),
    ReimbursementCurrency       NVARCHAR(10),
    TransactionAmount           DECIMAL(18,2),
    TransactionCurrency         NVARCHAR(10),
    WorkLocationCountry         NVARCHAR(100),
    WorkLocationRegion          NVARCHAR(100),
    WorkLocationCity            NVARCHAR(100),
    CountryOfPurchase           NVARCHAR(100),
    RegionOfPurchase            NVARCHAR(100),
    CityOfPurchase              NVARCHAR(100),
    Vendor                      NVARCHAR(200),
    ReceiptStatus               NVARCHAR(50),
    GLAccount                   NVARCHAR(50),
    EngagementName              NVARCHAR(500),
    EngagementCode              NVARCHAR(100),
    EngagementPercentage        DECIMAL(5,2),
    TransactionType             NVARCHAR(50),
    NumberOfAttendees           INT,
    TripOver3Months             NVARCHAR(10)
);

-- ── UserScoreboard ──
-- Source: "MENA Scorecard data_Template_v3" Excel — Template sheet
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='UserScoreboard' AND xtype='U')
CREATE TABLE UserScoreboard (
    Id                  INT IDENTITY(1,1) PRIMARY KEY,
    GUI                 NVARCHAR(50),
    GPN                 NVARCHAR(50),
    EmployeeName        NVARCHAR(200),
    EmployeeId          NVARCHAR(100) NOT NULL,   -- mapped from GUI
    Country             NVARCHAR(100),
    SL                  NVARCHAR(100),            -- Service Line
    SSL                 NVARCHAR(100),            -- Sub-Service Line
    CurrentRank         NVARCHAR(100),
    Role                NVARCHAR(200),
    AdditionalRole      NVARCHAR(200),
    GTER                DECIMAL(18,2),
    GTERPlan            DECIMAL(18,2),
    GTERPlanAchievedPct DECIMAL(10,4),
    GlobalMargin        DECIMAL(18,2),
    GlobalMarginPct     DECIMAL(10,4),
    GlobalSales         DECIMAL(18,2),
    WeightedPipeline    DECIMAL(18,2),
    TER                 DECIMAL(18,2),
    ANSR                DECIMAL(18,2),
    ANSRGTERRatio       DECIMAL(10,4),
    EngMargin           DECIMAL(18,2),
    EngMarginPct        DECIMAL(10,4),
    FYTDBacklogTER      DECIMAL(18,2),
    TotalBacklogTER     DECIMAL(18,2),
    UtilizationPct      DECIMAL(10,4),
    Billing             DECIMAL(18,2),
    Collection          DECIMAL(18,2),
    AR                  DECIMAL(18,2),            -- Accounts Receivable
    ARReserve           DECIMAL(18,2),
    TotalNUI            DECIMAL(18,2),            -- Net Unbilled Inventory
    AgedNUIAbove180Days DECIMAL(18,2),
    AgedNUIAbove365Days DECIMAL(18,2),
    RevenueDays         DECIMAL(10,2),
    Period              NVARCHAR(20),             -- e.g. "FY26 P9"
    ReportDate          DATE                      -- date of the scorecard snapshot
);

-- ── AgentUserRoles ──
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='AgentUserRoles' AND xtype='U')
CREATE TABLE AgentUserRoles (
    Id      INT IDENTITY(1,1) PRIMARY KEY,
    UserId  NVARCHAR(100) NOT NULL,
    Role    NVARCHAR(20) NOT NULL DEFAULT 'user',
    CONSTRAINT UQ_AgentUserRoles_UserId UNIQUE(UserId)
);
