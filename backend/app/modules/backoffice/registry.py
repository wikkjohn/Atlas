"""The thin departments (Phase 61, roadmap Milestone D step 33): their processes, as data.

Each department has three processes. A process's request is approved by a second person or
not at all; when it carries an amount, a budget above which it is out of policy (a reviewer
should reject it, though nothing forbids approving it) and an amount above which only an
executive may approve it. Every department's first process carries an amount and needs
approval: the simulation workload drives it.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Process:
    code: str
    name: str
    description: str
    approval: bool  # approved by someone other than the requester
    sla_hours: int  # from submission to completion
    amount_label: str | None = None  # what the amount is, when the request carries one
    budget_usd: int | None = None  # out of policy above this (a judgement, not a rule)
    major_above_usd: int | None = None  # only an executive approves above this


@dataclass(frozen=True)
class Department:
    code: str
    name: str
    description: str
    processes: tuple[Process, Process, Process]


def _p(code, name, description, approval=True, sla_hours=72, amount_label=None,
       budget_usd=None, major_above_usd=None) -> Process:  # fmt: skip
    return Process(code, name, description, approval, sla_hours, amount_label, budget_usd,
                   major_above_usd)  # fmt: skip


DEPARTMENTS: tuple[Department, ...] = (
    Department("legal", "Legal", "Contracts, legal holds and litigation.", (
        _p("outside_counsel", "Outside counsel instruction", "Instruct external lawyers on a "
           "matter, against a fee estimate.", amount_label="Fee estimate", budget_usd=50_000,
           major_above_usd=150_000),
        _p("contract_review", "Contract review", "Review a contract before it is signed.",
           sla_hours=120),
        _p("legal_hold", "Legal hold", "Preserve records for a dispute or investigation.",
           approval=False, sla_hours=24),
    )),
    Department("internal_audit", "Internal Audit", "Independent assurance over the bank's "
               "controls.", (
        _p("audit_engagement", "Audit engagement", "Plan an audit with its budgeted days "
           "(as a cost).", amount_label="Budgeted cost", budget_usd=80_000,
           major_above_usd=200_000, sla_hours=240),
        _p("finding_closure", "Finding closure", "Close an audit finding once remediation is "
           "evidenced.", sla_hours=120),
        _p("follow_up", "Follow-up review", "Re-test a remediated control.", approval=False,
           sla_hours=240),
    )),
    Department("marketing", "Marketing", "Campaigns, promotions and the brand.", (
        _p("campaign", "Campaign approval", "Launch a campaign against its media budget.",
           amount_label="Media budget", budget_usd=100_000, major_above_usd=500_000),
        _p("promotion_review", "Financial promotion review", "Check a customer-facing "
           "promotion is fair, clear and not misleading.", sla_hours=48),
        _p("brand_asset", "Brand asset request", "Request artwork or templates.",
           approval=False, sla_hours=120),
    )),
    Department("facilities", "Facilities", "Buildings, maintenance and workplace services.", (
        _p("capex", "Capital works request", "Fit-out, refurbishment or equipment.",
           amount_label="Estimated cost", budget_usd=75_000, major_above_usd=250_000,
           sla_hours=240),
        _p("maintenance", "Maintenance request", "Repair something in a building.",
           approval=False, sla_hours=48),
        _p("space_change", "Space change", "Move a team or change a floor layout.",
           sla_hours=168),
    )),
    Department("information_security", "Information Security", "Access, vulnerabilities and "
               "security exceptions.", (
        _p("security_tooling", "Security tooling purchase", "Buy or renew a security tool.",
           amount_label="Annual cost", budget_usd=60_000, major_above_usd=200_000),
        _p("security_exception", "Security exception", "Accept a deviation from a security "
           "standard for a time.", sla_hours=48),
        _p("vulnerability_fix", "Vulnerability remediation", "Fix a reported vulnerability.",
           approval=False, sla_hours=72),
    )),
    Department("data_office", "Data Office", "Data governance, quality and retention.", (
        _p("data_purchase", "External data purchase", "License a third-party data set.",
           amount_label="Licence cost", budget_usd=40_000, major_above_usd=150_000),
        _p("data_access", "Data access request", "Access a governed data set.",
           sla_hours=48),
        _p("data_quality", "Data quality issue", "Log and fix a data quality defect.",
           approval=False, sla_hours=120),
    )),
    Department("business_continuity", "Business Continuity", "Continuity plans and recovery "
               "tests.", (
        _p("recovery_site", "Recovery site booking", "Book recovery capacity for a test or "
           "an invocation.", amount_label="Booking cost", budget_usd=30_000,
           major_above_usd=100_000, sla_hours=48),
        _p("plan_review", "Continuity plan review", "Review a department's continuity plan.",
           sla_hours=240),
        _p("recovery_test", "Recovery test report", "Record a recovery test's result.",
           approval=False, sla_hours=120),
    )),
    Department("communications", "Corporate Communications", "Press, internal news and "
               "media enquiries.", (
        _p("sponsorship", "Sponsorship", "Sponsor an event or organisation.",
           amount_label="Sponsorship fee", budget_usd=50_000, major_above_usd=200_000),
        _p("press_release", "Press release", "Publish a press release.", sla_hours=24),
        _p("media_enquiry", "Media enquiry", "Answer a journalist.", approval=False,
           sla_hours=8),
    )),
    Department("investor_relations", "Investor Relations", "Shareholders, analysts and "
               "results.", (
        _p("roadshow", "Investor roadshow", "Meet investors, against a travel and venue "
           "budget.", amount_label="Roadshow cost", budget_usd=40_000,
           major_above_usd=120_000, sla_hours=168),
        _p("disclosure", "Market disclosure", "Publish price-sensitive information.",
           sla_hours=4),
        _p("shareholder_query", "Shareholder query", "Answer a shareholder.",
           approval=False, sla_hours=72),
    )),
    Department("strategy", "Strategy", "Corporate strategy and development.", (
        _p("consultancy", "Strategy consultancy", "Engage advisers on a strategic question.",
           amount_label="Fee estimate", budget_usd=150_000, major_above_usd=500_000,
           sla_hours=168),
        _p("initiative", "Strategic initiative", "Propose a strategic initiative.",
           sla_hours=240),
        _p("market_study", "Market study", "Commission an internal market study.",
           approval=False, sla_hours=240),
    )),
    Department("tax", "Tax", "Tax filings, rulings and transfer pricing.", (
        _p("tax_advice", "External tax advice", "Instruct tax advisers.",
           amount_label="Fee estimate", budget_usd=40_000, major_above_usd=150_000),
        _p("filing", "Tax filing sign-off", "Sign off a tax return before filing.",
           sla_hours=120),
        _p("tax_query", "Tax query", "Answer a business query on tax treatment.",
           approval=False, sla_hours=72),
    )),
    Department("company_secretariat", "Company Secretariat", "Boards, directors and statutory "
               "filings.", (
        _p("board_event", "Board event", "Hold a board offsite or event.",
           amount_label="Event cost", budget_usd=30_000, major_above_usd=100_000,
           sla_hours=168),
        _p("board_paper", "Board paper", "Table a paper at the board.", sla_hours=72),
        _p("statutory_filing", "Statutory filing", "File with a companies registry.",
           approval=False, sla_hours=120),
    )),
    Department("model_risk", "Model Risk", "Model inventory, validation and change.", (
        _p("validation_vendor", "External validation", "Have a model validated externally.",
           amount_label="Validation fee", budget_usd=60_000, major_above_usd=200_000,
           sla_hours=240),
        _p("model_change", "Model change", "Change a model in production.", sla_hours=120),
        _p("model_inventory", "Model registration", "Register a model in the inventory.",
           approval=False, sla_hours=72),
    )),
    Department("operational_risk", "Operational Risk", "Loss events, assessments and control "
               "issues.", (
        _p("insurance", "Insurance purchase", "Insure against an operational risk.",
           amount_label="Annual premium", budget_usd=100_000, major_above_usd=400_000),
        _p("risk_acceptance", "Risk acceptance", "Accept a risk outside appetite for a time.",
           sla_hours=72),
        _p("loss_event", "Loss event", "Record an operational loss.", approval=False,
           sla_hours=48),
    )),
    Department("regulatory_affairs", "Regulatory Affairs", "Regulators, licences and rule "
               "changes.", (
        _p("licence_fee", "Licence fee payment", "Pay a regulator's licence or levy.",
           amount_label="Fee", budget_usd=75_000, major_above_usd=300_000, sla_hours=120),
        _p("regulator_response", "Regulator response", "Answer a regulator's request.",
           sla_hours=48),
        _p("rule_change", "Rule change assessment", "Assess a new or changed rule.",
           approval=False, sla_hours=240),
    )),
    Department("sustainability", "Sustainability", "ESG disclosure and green finance.", (
        _p("offsets", "Carbon offset purchase", "Buy certified carbon offsets.",
           amount_label="Purchase cost", budget_usd=50_000, major_above_usd=200_000,
           sla_hours=168),
        _p("green_label", "Green finance label", "Label a facility as green finance.",
           sla_hours=120),
        _p("esg_data", "ESG data return", "Answer an ESG data request.", approval=False,
           sla_hours=168),
    )),
)  # fmt: skip

BY_CODE = {d.code: d for d in DEPARTMENTS}
# The workflow each process runs: WF-1100 onwards, three per department in registry order.
WORKFLOW_BASE = 1100


def workflow_id(department: Department, process: Process) -> str:
    index = DEPARTMENTS.index(department) * 3 + department.processes.index(process)
    return f"WF-{WORKFLOW_BASE + index}"


def find(department_code: str, process_code: str) -> tuple[Department, Process] | None:
    department = BY_CODE.get(department_code)
    if department is None:
        return None
    process = next((p for p in department.processes if p.code == process_code), None)
    return (department, process) if process else None


def by_workflow(workflow: str) -> tuple[Department, Process] | None:
    for department in DEPARTMENTS:
        for process in department.processes:
            if workflow_id(department, process) == workflow:
                return department, process
    return None
