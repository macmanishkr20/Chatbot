MENA_FUNCTIONS_CATALOG = """\
- function: AWS; Full form: "MENA Administrative and Workplace Services (AWS)"; description: "MENA Administrative and Workplace Services (AWS) provides operational, administrative, workplace, and people‑support services across CBS. AWS is the primary function for Executive Assistants (EA), Account Support Associates (ASA), Facilities Management (FM), Purchase Requisition Services, office operations, and workplace logistics.
 
    AWS is responsible for hands‑on execution and coordination of day‑to‑day business support activities that enable Partners, engagement teams, and leadership to focus on client delivery.
 
    Includes:
    • Executive Assistant (EA) and Account Support Associate (ASA) services
    • Facilities Management (FM), office services, and workplace operations
    • Meeting room booking, reception, access cards, parking, office equipment
    • Purchase requisitions, PO creation support, shopping carts, goods receipt
    • Event logistics support (non‑branding, non‑marketing)
    • Travel coordination support via tools (Concur, Dnata) but not policy ownership
 
    Excludes:
    • Travel policy, billing, or invoice settlement (Finance)
    • Event branding, communications, or social media (BMC)
    • Supplier strategy, sourcing, or negotiations (SCS)
    • Recruitment policy, learning, or HR programs (Talent)
    • Legal contracts or regulatory interpretation (GCO)"
 
- function: BMC; Full form: "Brand Marketing Communications (BMC)"; description: "Brand Marketing Communications (BMC) owns brand governance, external communications, marketing strategy, social media, SCORE approvals, event branding, and reputation management for CBS.
 
    BMC is the single authority for anything externally visible that represents EY, including digital content, social media, events, publications, and promotional materials.
 
    Includes:
    • SCORE (System for Communication Oversight, Review and Evaluation)
    • Social media strategy, publishing, approvals, and analytics
    • Brand identity, templates, visuals, tone of voice
    • Event branding, invitations, signage, production support
    • Digital marketing, website content, campaigns
    • Alliance visibility and sponsorship governance
 
    Excludes:
    • Event logistics or venue booking (TME / AWS)
    • Commercial pricing or invoices (Finance)
    • Contract drafting or negotiations (GCO)
    • Administrative execution or office operations (AWS)"
 
- function: C&I; Full form: "Clients & Industries (C&I)"; description: "Clients & Industries (C&I) supports pursuit, proposal, account management, credentials, references, client strategy, and market intelligence across MENA.
 
    C&I is the go‑to function for RFPs, bids, proposals, credentials, client insights, CX programs, entity management, GCSP roles, and account governance.
 
    Includes:
    • RFP / proposal process and circulation policy
    • MENA Pursuit Excellence Portal and credentials
    • Client references, proposals, CVs, templates
    • GCSP, IGL, account roles, market segments
    • Client Experience (CX Lens, VoC, surveys)
    • Entity master data coordination (MDM, ARD – business side)
 
    Excludes:
    • Billing, invoicing, margin, or ETC (Finance)
    • Contract drafting and legal templates (GCO)
    • Brand design or SCORE approvals (BMC)
    • Independence rulings or compliance decisions (Risk)"
 
- function: Finance; Full form: "Finance"; description: "The Finance function manages financial operations, engagement economics, billing, invoicing, revenue, cost accounting, forecasting, and financial compliance across CBS.
 
    Finance is the owner of Mercury financial processes and supports engagement teams with budgeting, ETC, BTA, margins, invoicing, and collections.
 
    Includes:
    • Engagement Economics (NSR, ANSR, EAF, ETC, BTA)
    • Billing, invoices, credit notes, AR, write‑offs
    • Financial planning, forecasting, reporting
    • Cost accounting (GDS, EYG, travel, insurance)
    • Tax documentation, VAT, TRN, bank guarantees
    • IRD reports, financial dashboards
    • T&E policy ownership but not travel booking execution (TME / AWS)
 
    Excludes:
    • Legal contract review or interpretation (GCO)
    • Procurement sourcing or vendor onboarding (SCS)
    • Travel booking execution (TME)
    • HR policies or learning (Talent)"
 
- function: GCO; Full form: "CBS MENA General Counsel Office (GCO)"; description: "The CBS MENA General Counsel Office (GCO) provides legal, contractual, data protection, insurance, and regulatory guidance across CBS.
 
    GCO is responsible for legal templates, contracts, PII, NDAs, data protection, and legal risk interpretation.
 
    Includes:
    • Contract templates, NDAs, pre‑bid agreements
    • Legal review and contractual guidance
    • Professional Indemnity Insurance (PII)
    • Data protection and privacy guidance, AML/KYC compliance obligations
    • Legal policies and governance
    • GCO templates and policy finder support
 
    Excludes:
    • Financial approvals or billing (Finance)
    • Independence determinations (Risk)
    • Brand approvals or SCORE (BMC)
    • Procurement negotiations (SCS)"
 
- function: Risk; Full form: "MENA Risk Function"; description: "The MENA Risk function manages independence, regulatory, compliance, and risk governance across CBS and client engagements.
 
    Risk determines whether EY is permitted to pursue, accept, or continue work.
 
    Includes:
    • Independence (GIS, SORT, channel 1 / channel 2)
    • PACE submissions and approvals
    • BRIDGE third‑party risk assessments
    • PCIP (Global and local)
    • Conflicts of interest, AML, ABC
    • Health & Safety, gifts, hospitality risk
    • Whistleblowing and ethics
 
    Excludes:
    • Legal contract drafting (GCO)
    • Engagement economics or billing (Finance)
    • Brand communications (BMC)
    • Vendor sourcing (SCS)"
 
- function: SCS; Full form: "Supply Chain Services (SCS)"; description: "Supply Chain Services (SCS) governs procurement, supplier onboarding, CW and subcontractor engagement, and sourcing across CBS.
 
    SCS is the authority for how EY engages third‑party vendors.
 
    Includes:
    • Vendor onboarding and supplier setup
    • CW and subcontractor hiring
    • Procurement policy and thresholds
    • Smart Intake and category selection
    • Supplier contracts coordination (with GCO)
    • Procurement approvals and governance
 
    Excludes:
    • Invoice processing or payments (Finance)
    • Office purchase request initiation (AWS)
    • Legal contract interpretation (GCO)
    • Event branding or communications (BMC)"
 
- function: TME; Full form: "Travel, Meetings & Events (TME)"; description: "Travel, Meetings & Events (TME) manages business travel, meetings, and event execution from a logistics perspective.
 
    Includes:
    • Business travel booking tools and coordination
    • Meeting and event logistics execution
    • Travel vendors and compliance operations
    • Event logistics (non‑branding)
 
    Excludes:
    • Event branding and communications (BMC)
    • Travel policy ownership (Finance)
    • Supplier strategy (SCS)
    • Facilities and workplace operations (AWS)"
 
- function: Talent; Full form: "Talent"; description: "The Talent function manages the employee lifecycle, learning, immigration, benefits, and people policies for CBS.
 
    Includes:
    • Immigration, visas, labor compliance
    • Leave policies, benefits, allowances
    • Learning, SuccessFactors, badges
    • Recruitment, transfers, performance, PIP
    • Employee relations and grievances
 
    Excludes:
    • Engagement economics or billing (Finance)
    • Office administration (AWS)
    • Legal disputes (GCO)
    • External marketing or brand (BMC)"
"""

# ── Function name mapping ──
# Left: UI chip code (used by frontend & state["function"] from user selection)
# Right: Azure Search index value (used in OData filters)
#
# The function_gate LLM outputs the *search value* (right side).
# The frontend sends the *chip code* (left side).

CHIP_TO_SEARCH: dict[str, str] = {
    "Risk Management":                     "Risk",
    "Clients & Industries":                "C&I",
    "Supply Chain Services":               "SCS",
    "Travel, Meetings & Events (TME)":     "TME",
    "Talent":                              "Talent",
    "Finance":                             "Finance",
    "AWS":                                 "AWS",
    "GCO":                                 "GCO",
    "BMC":                                 "BMC",
}

SEARCH_TO_CHIP: dict[str, str] = {v: k for k, v in CHIP_TO_SEARCH.items()}