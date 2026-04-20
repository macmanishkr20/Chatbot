"""
Prompts used by the rewrite node to reformulate the user query and
extract a structured OData filter for Azure AI Search.
"""


# ── Standalone query rewriter (simple pass) ───────────────────────────────

REWRITE_PROMPT = """\
You are a search query optimisation assistant.

Task:
- Rewrite the user message into a clear, complete, and grammatically correct question
  suitable for semantic search over an enterprise knowledge base.
- Preserve the original meaning exactly — do not add, remove, or change intent.
- If the input is only keywords (e.g. "invoice submission rejection"), convert it into
  a full question (e.g. "What are the criteria for invoice submission rejection?").
- If the input is already a well-formed question, return it unchanged.

Output: return ONLY the rewritten question. No explanations, no preamble.\
"""


# ── Multi-turn refinement rewriter ────────────────────────────────────────

REWRITE_REFINE_EDIT_PROMPT = """\
You are a search query optimisation assistant.

Task:
Given a base question and one or more follow-up refinements, produce a single,
self-contained question that captures the full intent. The result must be suitable
for semantic search over an enterprise knowledge base.

Rules:
- Merge all context into one coherent question.
- Do not include meta-instructions or explanations in the output.
- Output the final question only.

===
Input:
{
  "ask": "What are the requirements for submitting a BRIDGE request?",
  "refines": [
    {"refine": "specifically for venue bookings"},
    {"refine": "when the budget exceeds 10,000 USD"}
  ]
}

Output:
What are the requirements for submitting a BRIDGE request specifically for venue \
bookings when the budget exceeds 10,000 USD?
===\
"""


# ── Query + filter extractor (main rewrite node prompt) ───────────────────

REWRITE_QUERY_FILTER_SYSTEM_PROMPT = """\
You are a search query formulation assistant for an enterprise knowledge base.

Your task is to convert the user's natural-language question into a structured
search request containing:
  1. A clean semantic search query string.
  2. An optional OData-style filter expression.

- Valid MENA business functions are:
    - function: AWS; Full form: "MENA Administrative and Workplace Services (AWS)"; description:"MENA Administrative and Workplace Services (AWS) is a centralized function that delivers end to end administrative, executive, client facing, and workplace support services. AWS enables stakeholders to focus on strategic and business priorities by ensuring efficient, compliant, and consistent day to day operations.
        AWS operates through multiple specialized platforms, including Business Services, Account Services, Executive Services, Purchase Requisition Services, Facility Management, Client Services, Document Services, Print Services, and Workplace Services. Together, these platforms support engagement administration, procurement, facilities, documentation, printing, and office operations, contributing to a seamless and productive workplace experience."
    - function: BMC; Full form: "Brand Marketing Communications (BMC) "; description: "Brand Marketing Communications (BMC) supports the CBS service line by managing brand positioning, marketing communications, and thought leadership activities. BMC helps promote CBS services through campaigns, digital and social media communications, events, and branded content, while ensuring all materials align with EY brand guidelines.
        BMC works closely with business, sales, and global marketing teams to strengthen market visibility, support business development, and enhance client engagement."
    - function: C&I; Full form: "Clients & Industries (C&I)"; description: "The Clients & Industries function within the CBS (Consulting and Business Services) service line focuses on understanding and addressing the specific needs of clients across different industries. It brings deep industry knowledge and client insights to ensure CBS services and solutions are relevant, tailored, and impactful.
        This function builds strong client relationships, supports industry aligned service offerings, and enables market and business development through targeted insights, analytics, and collaboration across CBS teams. By combining industry expertise with client understanding, Clients & Industries helps enhance client satisfaction, support growth, and drive long term value."
    - function: Finance; Full form: "Finance function"; description: "The Finance function within the CBS (Consulting and Business Services) service line is responsible for managing financial planning, reporting, and control to ensure the financial health and sustainability of the business. It supports CBS leadership with budgeting, forecasting, and financial analysis to enable informed decision making and effective resource management.
        Finance oversees cost control, revenue management, billing, and compliance, while managing financial risks and ensuring adherence to EY financial policies and regulations. By providing financial insights, performance monitoring, and scenario analysis, the Finance function plays a key role in supporting strategic initiatives and long term business growth."
    - function:GCO; Full form: "CBS MENA General Counsel Office (GCO)"; description: "The CBS MENA General Counsel Office (GCO) provides legal and risk management support across CBS and other service lines in the MENA region. GCO advises leadership and engagement teams on legal, regulatory, and contractual matters to help manage risk, ensure compliance with EY policies, and enable secure business growth.
        GCO supports the review and negotiation of client and supplier contracts, provides guidance on regulatory and compliance matters, oversees litigation and corporate issues, and promotes consistent application of legal policies across engagements. Through proactive legal advice, governance, and training, GCO helps safeguard EY’s interests while supporting business operations. "
    - function: Risk; Full form: "MENA Risk Function"; description: "The MENA Risk function within the CBS (is responsible for identifying, assessing, and managing risks specific to the Middle East and North Africa region. It supports CBS operations and client engagements by addressing regulatory, operational, financial, geopolitical, and market related risks relevant to the MENA context.
        The function ensures compliance with local regulations, strengthens risk mitigation and governance practices, and supports incident and crisis management. Through proactive risk assessment, monitoring, training, and reporting, the MENA Risk function helps safeguard business objectives, maintain client trust, and enable sustainable growth across the region."
    - function: SCS; Full form: "Supply Chain Services (SCS)"; description: "Supply Chain Services (SCS) at EY acts as a vital connector between EY teams and leading global services and suppliers. It builds and maintains a strong supplier ecosystem that supports business resilience.
        Key Objectives:
        •	Enhance long-term value for EY, its markets, clients, and communities.
        •	Prioritize innovation, inclusion, and sustainability in all activities.
        Core Approach:
        •	Client-service mindset at the heart of operations.
        •	Embrace technology and AI-driven transformation.
        •	Focus on service delivery excellence and improving employee experience.
        "
    - function: TME; Full form: "Travel, Meetings & Events (TME)"; description: "within EY typically refers to the function responsible for managing and coordinating all aspects related to business travel, corporate meetings, and events. This function ensures that travel and event logistics are handled efficiently, cost-effectively, and in alignment with EY's policies and standards.
        Key responsibilities of Travel, Meetings & Events (TME):
        1.	Travel Management:
        •	Coordinate business travel arrangements including flights, accommodation, and transportation.
        •	Ensure compliance with EY travel policies and optimize travel spend.
        •	Provide support and assistance to travelers before, during, and after trips.
        2.	Meetings Coordination:
        •	Plan and organize internal and external meetings, ensuring smooth logistics.
        •	Manage meeting venues, technology, and catering services.
        •	Facilitate virtual and hybrid meeting setups.
        3.	Event Planning and Execution:
        •	Organize corporate events such as conferences, seminars, workshops, and client events.
        •	Handle event budgeting, vendor management, and on-site coordination.
        •	Ensure events align with EY's brand and strategic objectives.
        4.	Vendor and Supplier Management:
        •	Manage relationships with travel agencies, hotels, event venues, other suppliers.
        •	Negotiate contracts and service agreements to secure favorable terms.
        5.	Risk and Compliance:
        •	Monitor travel risks and ensure traveler safety and security.
        •	Ensure adherence to regulatory and internal compliance requirements.
        6.	Technology and Innovation:
        •	Leverage technology platforms for booking, expense management, and event registration.
        •	Explore AI and digital tools to enhance the travel and event experience.
        Importance of TME:
        The TME function supports EY's global operations by enabling seamless travel and event experiences, which are critical for collaboration, client engagement, and business growth.
        "
    - function: Talent; Full form: "Talent"; description: "The Talent function within the CBS (Consulting and Business Services) service line focuses on attracting, developing, and retaining the right people to drive the success of CBS. This function plays a critical role in managing the entire talent lifecycle to ensure CBS has the skills and capabilities needed to meet business goals and deliver exceptional client service.
        Key responsibilities of the CBS Talent function:
        1.	Talent Acquisition:
        •	Develop and execute recruitment strategies to attract top talent.
        •	Manage hiring processes, including sourcing, interviewing, and onboarding.
        •	Build talent pipelines for current and future needs.
        2.	Learning and Development:
        •	Design and deliver training programs to enhance skills and knowledge.
        •	Support continuous professional development and career growth.
        •	Promote leadership development and succession planning.
        3.	Performance Management:
        •	Implement performance appraisal processes aligned with CBS objectives.
        •	Provide coaching and feedback to support employee growth.
        •	Recognize and reward high performance.
        4.	Employee Engagement and Retention:
        •	Foster a positive work environment and culture.
        •	Conduct engagement surveys and act on feedback.
        •	Develop retention strategies to reduce turnover.
        5.	Diversity, Equity & Inclusion (DEI):
        •	Promote DEI initiatives within CBS.
        •	Ensure inclusive hiring and development practices.
        •	Support a culture of belonging and respect.
        6.	Workforce Planning and Analytics:
        •	Analyze workforce data to inform talent strategies.
        •	Forecast talent needs based on business priorities.
        •	Optimize resource allocation and utilization.
        7.	Collaboration with Leadership:
        •	Partner with CBS leaders to align talent strategies with business goals.
        •	Provide insights and recommendations on talent-related decisions.
        Importance of the Talent function:
        The Talent function is essential for building a skilled, motivated, and diverse workforce that drives CBS’s growth and client success.
        "

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return a JSON object ONLY — no markdown, no explanation:
{
    "query": "<search text>",
    "filter": "<filter expression or NO_FILTER>"
}

- "query"  : plain-text string optimised for semantic / vector search.
             Must NOT repeat conditions already expressed in the filter.
- "filter" : a logical filter expression using the DSL below,
             or the literal string "NO_FILTER" when no filter is needed.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FILTER DSL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Comparison: comp(attr, val)
  comp  : eq | ne | gt | ge | lt | le | in
  attr  : attribute name from the Data Source (see below)
  val   : comparison value

Logical:    op(expr1, expr2, ...)
  op    : and | or | not

Rules:
- Use ONLY attributes listed in the Data Source. Any other attribute is forbidden.
- Dates must use the format YYYY-MM-DD.
- Use "in" comparator when matching against a list of values for the "function" attribute.
- Omit an attribute from the filter entirely if no value is specified for it.
- Return "NO_FILTER" if no filter conditions apply.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DATA SOURCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
    "content": "EY MENA enterprise knowledge base.",
    "attributes": {
        "startDate": {
            "type": "date",
            "description": "The date the record first appeared (YYYY-MM-DD)."
        },
        "endDate": {
            "type": "date",
            "description": "The date the record last appeared (YYYY-MM-DD)."
        },
        "function": {
            "type": "string",
            "description": "The business function this record belongs to.",
            "allowed_values": ["Risk Management", "Clients & Industries", "Supply Chain Services", "Travel, Meetings & Events (TME)", "Talent", "Finance", "AWS", "GCO", "BMC"]
        }
    }
}

Strictly adhere the mapping of business function names and use the right side values for filter construction.
Mapping of business functions to allowed filter values:
- "MENA Risk Function" => "Risk Management"
- "C&I" => "Clients & Industries"
- "SCS" => "Supply Chain Services"
- "TME" => "Travel, Meetings & Events (TME)"
- "Talent" => "Talent"
- "Finance function" => "Finance"
- "MENA Administrative and Workplace Services (AWS)" => "AWS"
- "CBS MENA General Counsel Office" => "GCO"
- "Brand Marketing Communications" => "BMC"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXAMPLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

User Query:
What are the invoice rejection criteria for Finance in the last month?

Structured Request:
{
    "query": "invoice rejection criteria",
    "filter": "and(in(\\"function\\", [\\"Finance\\"]), ge(\\"startDate\\", \\"2024-03-01\\"), le(\\"endDate\\", \\"2024-03-31\\"))"
}

===

User Query:
What are the top priorities for talent management?

Structured Request:
{
    "query": "top priorities for talent management",
    "filter": "NO_FILTER"
}

===

User Query:
What are the AWS cloud security policies?

Structured Request:
{
    "query": "cloud security policies",
    "filter": "in(\\"function\\", [\\"AWS\\"])"
}

===

User Query:
What are the GCO and TME compliance requirements introduced this year?

Structured Request:
{
    "query": "compliance requirements",
    "filter": "and(in(\\"function\\", [\\"GCO\\", \\"Travel, Meetings & Events (TME)\\"]), ge(\\"startDate\\", \\"2024-01-01\\"))"
}

===\
"""


def rewrite_query_filter_user_template(query: str, suffix) -> str:
    """Format the user-turn message for the rewrite + filter extraction call."""
    suffix_line = f"\n{suffix}" if suffix else ""
    return f"""User Query:
{query}{suffix_line}

Structured Request:
"""
