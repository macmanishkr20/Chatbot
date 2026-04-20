"""
Single source of truth for the MENA business-function catalog.

Imported by any prompt that needs to expose the valid function names,
full forms, and descriptions to the model.  Keeping one copy here
prevents drift between the classifier, rewrite, and supervisor prompts.
"""

# The exact text is preserved verbatim — do not paraphrase.  Callers
# splice this block into a larger prompt (typically after an
# "Allowed functions:" header).

MENA_FUNCTIONS_CATALOG = """\
- function: AWS; Full form: "MENA Administrative and Workplace Services (AWS)"; description: "MENA Administrative and Workplace Services (AWS) is a centralized function that delivers end to end administrative, executive, client facing, and workplace support services. AWS enables stakeholders to focus on strategic and business priorities by ensuring efficient, compliant, and consistent day to day operations.
    AWS operates through multiple specialized platforms, including Business Services, Account Services, Executive Services, Purchase Requisition Services, Facility Management, Client Services, Document Services, Print Services, and Workplace Services. Together, these platforms support engagement administration, procurement, facilities, documentation, printing, and office operations, contributing to a seamless and productive workplace experience."
- function: BMC; Full form: "Brand Marketing Communications (BMC)"; description: "Brand Marketing Communications (BMC) supports the CBS service line by managing brand positioning, marketing communications, and thought leadership activities. BMC helps promote CBS services through campaigns, digital and social media communications, events, and branded content, while ensuring all materials align with EY brand guidelines.
    BMC works closely with business, sales, and global marketing teams to strengthen market visibility, support business development, and enhance client engagement."
- function: C&I; Full form: "Clients & Industries (C&I)"; description: "The Clients & Industries function within the CBS (Consulting and Business Services) service line focuses on understanding and addressing the specific needs of clients across different industries. It brings deep industry knowledge and client insights to ensure CBS services and solutions are relevant, tailored, and impactful.
    This function builds strong client relationships, supports industry aligned service offerings, and enables market and business development through targeted insights, analytics, and collaboration across CBS teams. By combining industry expertise with client understanding, Clients & Industries helps enhance client satisfaction, support growth, and drive long term value."
- function: Finance; Full form: "Finance function"; description: "The Finance function within the CBS (Consulting and Business Services) service line is responsible for managing financial planning, reporting, and control to ensure the financial health and sustainability of the business. It supports CBS leadership with budgeting, forecasting, and financial analysis to enable informed decision making and effective resource management.
    Finance oversees cost control, revenue management, billing, and compliance, while managing financial risks and ensuring adherence to EY financial policies and regulations. By providing financial insights, performance monitoring, and scenario analysis, the Finance function plays a key role in supporting strategic initiatives and long term business growth."
- function: GCO; Full form: "CBS MENA General Counsel Office (GCO)"; description: "The CBS MENA General Counsel Office (GCO) provides legal and risk management support across CBS and other service lines in the MENA region. GCO advises leadership and engagement teams on legal, regulatory, and contractual matters to help manage risk, ensure compliance with EY policies, and enable secure business growth.
    GCO supports the review and negotiation of client and supplier contracts, provides guidance on regulatory and compliance matters, oversees litigation and corporate issues, and promotes consistent application of legal policies across engagements. Through proactive legal advice, governance, and training, GCO helps safeguard EY's interests while supporting business operations."
- function: Risk; Full form: "MENA Risk Function"; description: "The MENA Risk function within the CBS (is responsible for identifying, assessing, and managing risks specific to the Middle East and North Africa region. It supports CBS operations and client engagements by addressing regulatory, operational, financial, geopolitical, and market related risks relevant to the MENA context.
    The function ensures compliance with local regulations, strengthens risk mitigation and governance practices, and supports incident and crisis management. Through proactive risk assessment, monitoring, training, and reporting, the MENA Risk function helps safeguard business objectives, maintain client trust, and enable sustainable growth across the region."
- function: SCS; Full form: "Supply Chain Services (SCS)"; description: "Supply Chain Services (SCS) at EY acts as a vital connector between EY teams and leading global services and suppliers. It builds and maintains a strong supplier ecosystem that supports business resilience.
    Key Objectives:
    •\tEnhance long-term value for EY, its markets, clients, and communities.
    •\tPrioritize innovation, inclusion, and sustainability in all activities.
    Core Approach:
    •\tClient-service mindset at the heart of operations.
    •\tEmbrace technology and AI-driven transformation.
    •\tFocus on service delivery excellence and improving employee experience."
- function: TME; Full form: "Travel, Meetings & Events (TME)"; description: "within EY typically refers to the function responsible for managing and coordinating all aspects related to business travel, corporate meetings, and events. This function ensures that travel and event logistics are handled efficiently, cost-effectively, and in alignment with EY's policies and standards.
    Key responsibilities of Travel, Meetings & Events (TME):
    1.\tTravel Management:
    •\tCoordinate business travel arrangements including flights, accommodation, and transportation.
    •\tEnsure compliance with EY travel policies and optimize travel spend.
    •\tProvide support and assistance to travelers before, during, and after trips.
    2.\tMeetings Coordination:
    •\tPlan and organize internal and external meetings, ensuring smooth logistics.
    •\tManage meeting venues, technology, and catering services.
    •\tFacilitate virtual and hybrid meeting setups.
    3.\tEvent Planning and Execution:
    •\tOrganize corporate events such as conferences, seminars, workshops, and client events.
    •\tHandle event budgeting, vendor management, and on-site coordination.
    •\tEnsure events align with EY's brand and strategic objectives.
    4.\tVendor and Supplier Management:
    •\tManage relationships with travel agencies, hotels, event venues, other suppliers.
    •\tNegotiate contracts and service agreements to secure favorable terms.
    5.\tRisk and Compliance:
    •\tMonitor travel risks and ensure traveler safety and security.
    •\tEnsure adherence to regulatory and internal compliance requirements.
    6.\tTechnology and Innovation:
    •\tLeverage technology platforms for booking, expense management, and event registration.
    •\tExplore AI and digital tools to enhance the travel and event experience.
    Importance of TME:
    The TME function supports EY's global operations by enabling seamless travel and event experiences, which are critical for collaboration, client engagement, and business growth."
- function: Talent; Full form: "Talent"; description: "The Talent function within the CBS (Consulting and Business Services) service line focuses on attracting, developing, and retaining the right people to drive the success of CBS. This function plays a critical role in managing the entire talent lifecycle to ensure CBS has the skills and capabilities needed to meet business goals and deliver exceptional client service.
    Key responsibilities of the CBS Talent function:
    1.\tTalent Acquisition:
    •\tDevelop and execute recruitment strategies to attract top talent.
    •\tManage hiring processes, including sourcing, interviewing, and onboarding.
    •\tBuild talent pipelines for current and future needs.
    2.\tLearning and Development:
    •\tDesign and deliver training programs to enhance skills and knowledge.
    •\tSupport continuous professional development and career growth.
    •\tPromote leadership development and succession planning.
    3.\tPerformance Management:
    •\tImplement performance appraisal processes aligned with CBS objectives.
    •\tProvide coaching and feedback to support employee growth.
    •\tRecognize and reward high performance.
    4.\tEmployee Engagement and Retention:
    •\tFoster a positive work environment and culture.
    •\tConduct engagement surveys and act on feedback.
    •\tDevelop retention strategies to reduce turnover.
    5.\tDiversity, Equity & Inclusion (DEI):
    •\tPromote DEI initiatives within CBS.
    •\tEnsure inclusive hiring and development practices.
    •\tSupport a culture of belonging and respect.
    6.\tWorkforce Planning and Analytics:
    •\tAnalyze workforce data to inform talent strategies.
    •\tForecast talent needs based on business priorities.
    •\tOptimize resource allocation and utilization.
    7.\tCollaboration with Leadership:
    •\tPartner with CBS leaders to align talent strategies with business goals.
    •\tProvide insights and recommendations on talent-related decisions.
    Importance of the Talent function:
    The Talent function is essential for building a skilled, motivated, and diverse workforce that drives CBS's growth and client success."\
"""
