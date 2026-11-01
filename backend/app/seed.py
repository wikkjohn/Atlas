"""Demo data: a small synthetic bank across the five initial countries.

Run with `python -m app.cli seed-demo`. The seed is deterministic for a given `seed`
value and safe to run repeatedly: existing data is left untouched and only missing demo
users are added. Refuses to run in staging or production.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money import to_minor_units
from app.core.permissions import RoleCode, permissions_for
from app.modules.accounts.models import AccountType
from app.modules.accounts.service import (
    approve_request,
    deposit,
    submit_request,
    withdraw,
)
from app.modules.countries.models import Country, Region
from app.modules.customers.models import Customer, CustomerType, KycStatus, RiskRating
from app.modules.customers.schemas import CustomerCreate, CustomerReview
from app.modules.customers.service import create_customer, review_customer
from app.modules.employees.models import Employee
from app.modules.employees.schemas import EmployeeCreate
from app.modules.employees.service import create_employee
from app.modules.identity.models import User
from app.modules.identity.schemas import UserCreate
from app.modules.identity.service import AuthenticatedUser, create_user
from app.modules.organizations.blueprint import STRUCTURE
from app.modules.organizations.models import Organization, OrganizationType
from app.modules.organizations.schemas import OrganizationCreate
from app.modules.organizations.service import create_organization
from app.simulation.generators import SyntheticNameGenerator

DEFAULT_SEED = 2026

REGIONS = {
    Region.AMERICAS: ("Americas Regional Headquarters", ["US"]),
    Region.EUROPE: ("Europe Regional Headquarters", ["GB", "DE"]),
    Region.ASIA_PACIFIC: ("Asia-Pacific Regional Headquarters", ["SG", "JP"]),
}

SUBSIDIARY_NAMES = {
    "US": "ATLAS Bank USA",
    "GB": "ATLAS Bank UK",
    "DE": "ATLAS Bank Deutschland",
    "SG": "ATLAS Bank Singapore",
    "JP": "ATLAS Bank Japan",
}

# Annual salary bands in whole units of each country's currency (synthetic).
SALARY_BANDS = {
    "US": (62_000, 240_000),
    "GB": (42_000, 190_000),
    "DE": (48_000, 200_000),
    "SG": (60_000, 250_000),
    "JP": (5_000_000, 24_000_000),
}

DEMO_USERS = [
    ("admin", RoleCode.PLATFORM_ADMINISTRATOR, "Platform Administrator"),
    ("executive", RoleCode.GLOBAL_EXECUTIVE, "Global Executive"),
    ("regional", RoleCode.REGIONAL_EXECUTIVE, "Regional Executive"),
    ("manager", RoleCode.DEPARTMENT_MANAGER, "Department Manager"),
    ("employee", RoleCode.BANKING_EMPLOYEE, "Banking Employee"),
    ("compliance", RoleCode.COMPLIANCE_OFFICER, "Compliance Officer"),
    ("researcher", RoleCode.AI_RESEARCHER, "AI Researcher"),
    ("auditor", RoleCode.AUDITOR, "Auditor"),
]


CUSTOMERS_PER_COUNTRY = 30
BUSINESS_SHARE = 0.2
BUSINESS_WORDS = (
    "Northwind",
    "Bluehaven",
    "Crescent",
    "Summit",
    "Harbor",
    "Lumen",
    "Meridian",
    "Pinecrest",
    "Silverline",
    "Orion",
    "Cobalt",
    "Juniper",
    "Redwood",
    "Halcyon",
)
BUSINESS_SECTORS = (
    "Logistics",
    "Foods",
    "Analytics",
    "Textiles",
    "Energy",
    "Robotics",
    "Partners",
    "Pharma",
    "Holdings",
    "Studios",
    "Engineering",
    "Trading",
)
BUSINESS_SUFFIX = {"US": "Inc.", "GB": "Ltd", "DE": "GmbH", "SG": "Pte. Ltd.", "JP": "K.K."}
# Whole-unit deposit range per currency (synthetic).
DEPOSIT_RANGE = {"JPY": (10_000, 2_500_000)}
DEFAULT_DEPOSIT_RANGE = (100, 25_000)


WORKFLOW_CASES = 20
PAYMENT_CASES = 10
LOAN_CASES = 6


@dataclass
class SeedReport:
    organizations: int = 0
    employees: int = 0
    users: list[str] = field(default_factory=list)
    skipped_structure: bool = False
    customers: int = 0
    accounts: int = 0
    pending_requests: int = 0
    journal_entries: int = 0
    skipped_banking: bool = False
    workflow_cases: int = 0
    skipped_workflows: bool = False
    payment_cases: int = 0
    loan_cases: int = 0
    skipped_payments_and_loans: bool = False
    ai_tools: list[str] = field(default_factory=list)
    stored_definitions: list[str] = field(default_factory=list)
    templates: list[str] = field(default_factory=list)
    generated_variants: int = 0


def _org(
    db: Session,
    name: str,
    org_type: OrganizationType,
    parent: Organization | None,
    report: SeedReport,
    **kwargs: object,
) -> Organization:
    organization = create_organization(
        db,
        OrganizationCreate(
            name=name,
            organization_type=org_type,
            parent_organization_id=parent.id if parent else None,
            **kwargs,
        ),
        actor_id=None,
    )
    report.organizations += 1
    return organization


def _hire(
    db: Session,
    names: SyntheticNameGenerator,
    unit: Organization,
    country: Country,
    title: str,
    manager: Employee | None,
    report: SeedReport,
    role: RoleCode = RoleCode.BANKING_EMPLOYEE,
) -> Employee:
    first, last = names.name()
    low, high = SALARY_BANDS[country.iso_country_code]
    # Senior titles sit in the upper half of the band.
    if title.startswith(("Head", "Chief", "Director")):
        low = (low + high) // 2
    salary = names.integer(low, high) // 1000 * 1000
    employee = create_employee(
        db,
        EmployeeCreate(
            first_name=first,
            last_name=last,
            organization_id=unit.id,
            manager_id=manager.id if manager else None,
            job_title=title,
            role=role,
            annual_compensation=to_minor_units(salary, country.default_currency),
        ),
        actor_id=None,
    )
    report.employees += 1
    return employee


def _build_structure(db: Session, names: SyntheticNameGenerator, report: SeedReport) -> None:
    countries = {c.iso_country_code: c for c in db.execute(select(Country)).scalars()}
    bank = _org(db, "ATLAS Global Bank", OrganizationType.GLOBAL_BANK, None, report)
    for region, (hq_name, codes) in REGIONS.items():
        hq = _org(db, hq_name, OrganizationType.REGIONAL_HEADQUARTERS, bank, report, region=region)
        for code in codes:
            country = countries[code]
            subsidiary = _org(
                db,
                SUBSIDIARY_NAMES[code],
                OrganizationType.COUNTRY_SUBSIDIARY,
                hq,
                report,
                country_id=country.id,
            )
            for division_name, departments in STRUCTURE.items():
                division = _org(
                    db, division_name, OrganizationType.BUSINESS_DIVISION, subsidiary, report
                )
                for department_name, teams in departments.items():
                    department = _org(
                        db, department_name, OrganizationType.DEPARTMENT, division, report
                    )
                    head = _hire(
                        db,
                        names,
                        department,
                        country,
                        f"Head of {department_name}",
                        None,
                        report,
                        RoleCode.DEPARTMENT_MANAGER,
                    )
                    _hire(db, names, department, country, "Senior Analyst", head, report)
                    for team_name in teams:
                        team = _org(db, team_name, OrganizationType.TEAM, department, report)
                        lead = _hire(db, names, team, country, f"{team_name} Lead", head, report)
                        for _ in range(3):
                            _hire(db, names, team, country, f"{team_name} Analyst", lead, report)


def _principal(db: Session, username: str) -> AuthenticatedUser | None:
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        return None
    return AuthenticatedUser(
        id=user.id,
        username=user.username,
        role=user.role.code,
        permissions=permissions_for(user.role.code),
    )


def _kyc_outcome(names: SyntheticNameGenerator) -> tuple[KycStatus | None, RiskRating]:
    roll = names.integer(1, 100)
    risk_roll = names.integer(1, 100)
    risk = (
        RiskRating.LOW
        if risk_roll <= 60
        else RiskRating.MEDIUM
        if risk_roll <= 90
        else RiskRating.HIGH
    )
    if roll <= 70:
        return KycStatus.VERIFIED, risk
    if roll <= 82:
        return KycStatus.PENDING, risk
    if roll <= 92:
        return None, risk  # not started
    return KycStatus.REJECTED, risk


def _build_banking(db: Session, names: SyntheticNameGenerator, report: SeedReport) -> None:
    teller = _principal(db, "employee")
    manager = _principal(db, "manager")
    compliance = _principal(db, "compliance")
    if not (teller and manager and compliance):
        report.skipped_banking = True
        return
    countries = {c.iso_country_code: c for c in db.execute(select(Country)).scalars()}
    for code in SUBSIDIARY_NAMES:
        country = countries[code]
        for index in range(CUSTOMERS_PER_COUNTRY):
            business = index < CUSTOMERS_PER_COUNTRY * BUSINESS_SHARE
            if business:
                word = BUSINESS_WORDS[names.integer(0, len(BUSINESS_WORDS) - 1)]
                sector = BUSINESS_SECTORS[names.integer(0, len(BUSINESS_SECTORS) - 1)]
                name = f"{word} {sector} {BUSINESS_SUFFIX[code]}"
                founded = date(
                    names.integer(1980, 2023), names.integer(1, 12), names.integer(1, 28)
                )
            else:
                first, last = names.name()
                name = f"{first} {last}"
                founded = date(
                    names.integer(1950, 2004), names.integer(1, 12), names.integer(1, 28)
                )
            customer = create_customer(
                db,
                CustomerCreate(
                    customer_type=CustomerType.BUSINESS if business else CustomerType.INDIVIDUAL,
                    name=name,
                    date_of_birth_or_incorporation=founded,
                    country_id=country.id,
                ),
                actor_id=teller.id,
            )
            report.customers += 1
            kyc, risk = _kyc_outcome(names)
            if kyc is not None:
                review_customer(
                    db, customer, CustomerReview(kyc_status=KycStatus.PENDING), compliance.id
                )
            if kyc in (KycStatus.VERIFIED, KycStatus.REJECTED):
                review_customer(
                    db, customer, CustomerReview(kyc_status=kyc, risk_rating=risk), compliance.id
                )
            if kyc == KycStatus.VERIFIED:
                _open_and_fund(db, names, customer, teller, manager, compliance, report)


def _open_and_fund(
    db: Session,
    names: SyntheticNameGenerator,
    customer: Customer,
    teller: AuthenticatedUser,
    manager: AuthenticatedUser,
    compliance: AuthenticatedUser,
    report: SeedReport,
) -> None:
    if customer.customer_type == CustomerType.BUSINESS:
        types = [AccountType.BUSINESS_CURRENT]
    else:
        types = [AccountType.CURRENT]
        if names.integer(1, 100) <= 40:
            types.append(AccountType.SAVINGS)
    approver = compliance if customer.risk_rating == RiskRating.HIGH else manager
    currency = customer.country.default_currency
    low, high = DEPOSIT_RANGE.get(currency, DEFAULT_DEPOSIT_RANGE)
    for account_type in types:
        request = submit_request(
            db,
            customer_id=customer.id,
            account_type=account_type,
            currency=None,
            requested_by=teller.id,
        )
        # Leave some requests waiting so the approvals queue has work in it.
        if names.integer(1, 100) <= 12:
            report.pending_requests += 1
            continue
        account = approve_request(db, request.id, approver)
        report.accounts += 1
        for n in range(names.integer(1, 3)):
            deposit(
                db,
                account.id,
                amount=to_minor_units(names.integer(low, high), currency),
                memo="Synthetic cash deposit",
                idempotency_key=f"seed:{account.account_number}:d{n}",
                actor_id=teller.id,
            )
            report.journal_entries += 1
        if names.integer(1, 100) <= 50:
            withdraw(
                db,
                account.id,
                amount=to_minor_units(low, currency),
                memo="Synthetic cash withdrawal",
                idempotency_key=f"seed:{account.account_number}:w",
                actor_id=teller.id,
            )
            report.journal_entries += 1


def _build_workflow_cases(db: Session, names: SyntheticNameGenerator, report: SeedReport) -> None:
    """Run WF-0001 cases through the real engine, leaving a realistic mix of states."""
    from app.modules.workflows import engine
    from app.modules.workflows.models import WorkflowStepRun
    from app.modules.workflows.wf0001 import synthetic_document_number

    teller = _principal(db, "employee")
    manager = _principal(db, "manager")
    compliance = _principal(db, "compliance")
    if not (teller and manager and compliance):
        report.skipped_workflows = True
        return
    codes = list(SUBSIDIARY_NAMES)
    for index in range(WORKFLOW_CASES):
        first, last = names.name()
        name = f"{first} {last}"
        born = date(names.integer(1955, 2003), names.integer(1, 12), names.integer(1, 28))
        kinds = ["passport", "proof_of_address"]
        if index % 10 == 3:
            kinds = ["passport"]  # waits for documents
        documents = [
            {
                "document_type": kind,
                "document_number": synthetic_document_number(kind, names.integer(0, 9_999_999)),
                "name_on_document": name,
                "date_of_birth": born.isoformat() if kind == "passport" else None,
                "expiry_date": "2031-06-30" if kind == "passport" else None,
            }
            for kind in kinds
        ]
        execution, _ = engine.start(
            db,
            workflow_id="WF-0001",
            payload={
                "applicant_name": name,
                "date_of_birth": born.isoformat(),
                "country_code": codes[index % len(codes)],
                "account_type": "current" if index % 3 else "savings",
                "documents": documents,
                "politically_exposed": index % 7 == 5,
                "expected_monthly_deposits": 80_000 if index % 7 == 5 else names.integer(0, 20_000),
            },
            initiator=teller,
            idempotency_key=f"seed-wf0001-{index}",
        )
        report.workflow_cases += 1
        task = db.execute(
            select(WorkflowStepRun).where(
                WorkflowStepRun.execution_id == execution.id, WorkflowStepRun.status == "waiting"
            )
        ).scalar_one_or_none()
        if task is None or task.step_type != "approval" or index % 5 == 4:
            continue  # leave some cases waiting for a decision
        reviewer = compliance if task.step_id == "compliance_review" else manager
        decision = "reject" if index % 6 == 0 else "approve"
        engine.complete_task(db, task.id, reviewer, decision=decision, note="Seeded decision")


def _open_accounts(db: Session) -> list[tuple]:
    """Open current accounts of live (non-simulated) verified customers, with balances."""
    from app.modules.accounts.models import Account
    from app.modules.ledger import service as ledger
    from app.modules.ledger.models import LedgerAccount

    rows = db.execute(
        select(Account, LedgerAccount)
        .join(LedgerAccount, LedgerAccount.id == Account.ledger_account_id)
        .join(Customer, Customer.id == Account.customer_id)
        .where(
            Account.status == "open",
            Account.account_type == AccountType.CURRENT,
            Customer.kyc_status == KycStatus.VERIFIED,
            Account.currency != "JPY",  # product limits are set in two-decimal currencies
        )
        .order_by(Account.account_number)
    ).all()
    amounts = ledger.balances(db, [ledger_account for _, ledger_account in rows])
    return [(account, amounts[ledger_account.id]) for account, ledger_account in rows]


def _build_payment_and_loan_cases(
    db: Session, names: SyntheticNameGenerator, report: SeedReport
) -> None:
    """Run WF-0002 payments and WF-0003 loan applications between seeded customers."""
    from app.modules.workflows import engine
    from app.modules.workflows.models import WorkflowStepRun

    teller = _principal(db, "employee")
    manager = _principal(db, "manager")
    compliance = _principal(db, "compliance")
    accounts = _open_accounts(db)
    if not (teller and manager and compliance) or len(accounts) < 4:
        report.skipped_payments_and_loans = True
        return

    def waiting(execution_id) -> WorkflowStepRun | None:
        return db.execute(
            select(WorkflowStepRun).where(
                WorkflowStepRun.execution_id == execution_id, WorkflowStepRun.status == "waiting"
            )
        ).scalar_one_or_none()

    funded = [(a, balance) for a, balance in accounts if balance > 0]
    for index in range(PAYMENT_CASES):
        debtor, balance = funded[(index * 7) % len(funded)]
        payees = [a for a, _ in accounts if a.currency == debtor.currency and a.id != debtor.id]
        if not payees:
            continue
        creditor = payees[(index * 3) % len(payees)]
        share = 0.9 if index % 5 == 3 else names.integer(5, 30) / 100
        reference = "Gift card codes for the tax office" if index % 5 == 1 else f"Invoice {index}"
        execution, _ = engine.start(
            db,
            workflow_id="WF-0002",
            payload={
                "debtor_account_number": debtor.account_number,
                "creditor_account_number": creditor.account_number,
                "amount": max(1, int(balance * share)),
                "currency": debtor.currency,
                "reference": reference,
            },
            initiator=teller,
            idempotency_key=f"seed-wf0002-{index}",
        )
        report.payment_cases += 1
        task = waiting(execution.id)
        if task is None or index == 1:
            continue  # leave a scam waiting in the fraud review queue
        decision = "reject" if index % 5 == 1 else "approve"
        reviewer = compliance if task.step_id == "fraud_review" else manager
        engine.complete_task(db, task.id, reviewer, decision=decision, note="Seeded decision")

    for index in range(LOAN_CASES):
        account, _ = accounts[(index * 5 + 2) % len(accounts)]
        income = names.integer(4_000, 9_000)
        overextended = index % 3 == 2
        execution, _ = engine.start(
            db,
            workflow_id="WF-0003",
            payload={
                "customer_number": account.customer.customer_number,
                "disbursement_account_number": account.account_number,
                "amount": to_minor_units(names.integer(5, 20) * 1_000, account.currency),
                "term_months": 36,
                "purpose": "home_improvement" if index % 2 else "vehicle",
                "monthly_income": to_minor_units(income, account.currency),
                "monthly_debt_payments": to_minor_units(
                    income // 2 if overextended else income // 20, account.currency
                ),
                "employment_status": "employed",
            },
            initiator=teller,
            idempotency_key=f"seed-wf0003-{index}",
        )
        report.loan_cases += 1
        task = waiting(execution.id)
        if task is not None and index % 3 == 1:
            engine.complete_task(db, task.id, manager, decision="approve", note="Seeded decision")


def seed_demo(db: Session, password: str, seed: int = DEFAULT_SEED) -> SeedReport:
    report = SeedReport()
    names = SyntheticNameGenerator(seed)

    has_bank = db.execute(
        select(Organization.id).where(
            Organization.organization_type == OrganizationType.GLOBAL_BANK
        )
    ).first()
    if has_bank:
        report.skipped_structure = True
    else:
        _build_structure(db, names, report)

    # Link the department-manager demo account to a real department head.
    manager_employee = (
        db.execute(
            select(Employee)
            .where(Employee.job_title == "Head of Customer Onboarding")
            .order_by(Employee.employee_number)
        )
        .scalars()
        .first()
    )
    for username, role, display_name in DEMO_USERS:
        if db.execute(select(User.id).where(User.username == username)).first():
            continue
        employee_id = None
        if role == RoleCode.DEPARTMENT_MANAGER and manager_employee is not None:
            linked = db.execute(
                select(User.id).where(User.employee_id == manager_employee.id)
            ).first()
            employee_id = None if linked else manager_employee.id
        create_user(
            db,
            UserCreate(
                username=username,
                email=f"{username}@atlasbank.example",
                display_name=f"Demo {display_name}",
                password=password,
                role=role,
                employee_id=employee_id,
            ),
            actor_id=None,
        )
        report.users.append(username)

    # Banking activity uses its own generator so the workforce stays identical per seed.
    if db.execute(select(Customer.id).limit(1)).first():
        report.skipped_banking = True
    else:
        _build_banking(db, SyntheticNameGenerator(seed + 1), report)

    from app.modules.workflows.models import Realm, WorkflowExecution

    if db.execute(select(WorkflowExecution.id).limit(1)).first():
        report.skipped_workflows = True
    else:
        _build_workflow_cases(db, SyntheticNameGenerator(seed + 2), report)
    if db.execute(
        select(WorkflowExecution.id)
        .where(
            WorkflowExecution.workflow_id == "WF-0002",
            WorkflowExecution.realm == Realm.LIVE,
        )
        .limit(1)
    ).first():
        report.skipped_payments_and_loans = True
    else:
        _build_payment_and_loan_cases(db, SyntheticNameGenerator(seed + 3), report)
    # Tools may name stored workflows as compatible (WF-1003), and stored workflows may call
    # tools (WF-1003 v2): the examples without AI steps first, then the tools, then the rest.
    # Synthetic counterparty banks for the treasury (Phase 39); idempotent.
    from app.modules.treasury.service import ensure_counterparties

    ensure_counterparties(db)
    _import_examples(db, report, with_ai_steps=False)
    _register_ai_tools(db, report)
    _import_example_definitions(db, report)
    return report


def _uses_ai(document: dict) -> bool:
    return any(step.get("handler") == "ai.review" for step in document.get("steps", []))


def _import_examples(db: Session, report: SeedReport, *, with_ai_steps: bool) -> None:
    from app.modules.workflows import authoring, examples

    admin = db.execute(select(User.id).where(User.username == "admin")).scalar_one_or_none()
    if admin is None:
        return
    for document in examples.documents():
        if _uses_ai(document) != with_ai_steps:
            continue
        record, created, _ = authoring.import_definition(db, document, admin)
        if created:
            report.stored_definitions.append(f"{record.workflow_id} v{record.version}")


def _import_example_definitions(db: Session, report: SeedReport) -> None:
    """Import the example stored workflows (e.g. WF-1001), unless already there."""
    from app.modules.workflows import authoring, examples

    admin = db.execute(select(User.id).where(User.username == "admin")).scalar_one_or_none()
    if admin is None:
        return
    _import_examples(db, report, with_ai_steps=True)
    from app.modules.workflows import templates
    from app.modules.workflows.definition import Catalogue
    from app.modules.workflows.models import WorkflowCatalogueEntry

    classified = set(db.execute(select(WorkflowCatalogueEntry.workflow_id)).scalars())
    for workflow_id, catalogue in examples.EXAMPLE_CATALOGUE.items():
        if workflow_id not in classified:
            authoring.classify(db, workflow_id, Catalogue(**catalogue), admin)

    for document in examples.templates():
        template, created, _ = templates.import_template(db, document, admin)
        if created:
            report.templates.append(f"{template.template_id} v{template.version}")
    demo = examples.DEMO_GENERATION
    generated = templates.generate(
        db,
        demo["template_id"],
        templates.expand(demo["grid"], None, demo["fixed"]),
        admin,
    )
    report.generated_variants = generated.count("created") + generated.count("updated")


# The candidate tools of the AI Innovation Lab and a deliberately unreliable test double.
DEMO_AI_TOOLS = [
    {
        "tool_id": "agb-intelligent-kyc-assistant",
        "tool_name": "AGB Intelligent KYC Assistant",
        "tool_version": "1.0.0",
        "provider": "ATLAS Global Bank (in-house, rule-based proof of concept)",
        "description": "Analyses synthetic retail applications and documents, flags missing "
        "or inconsistent fields, proposes a risk classification with an explanation and "
        "recommends approve, reject or escalate. Advisory: it never approves accounts.",
        "adapter": "rule_based_kyc",
        "allowed_actions": [
            "analyze_application",
            "recommend_decision",
            "complete_low_risk_review",
        ],
        "permissions": ["customers:read"],
        "compatible_workflows": ["WF-0001"],
    },
    {
        "tool_id": "kyc-fault-injector",
        "tool_name": "KYC Fault Injector (test double)",
        "tool_version": "1.0.0",
        "provider": "ATLAS Global Bank (test harness)",
        "description": "Behaves like the KYC assistant but fails 10%, times out 5% and "
        "returns malformed output 5% of the time, reproducibly. It is not granted "
        "complete_low_risk_review, so automated mode demonstrates blocked actions.",
        "adapter": "fault_injection",
        "allowed_actions": ["analyze_application", "recommend_decision"],
        "permissions": ["customers:read"],
        "compatible_workflows": ["WF-0001"],
    },
    {
        "tool_id": "agb-payment-fraud-screener",
        "tool_name": "AGB Payment Fraud Screener",
        "tool_version": "1.0.0",
        "provider": "ATLAS Global Bank (in-house, rule-based proof of concept)",
        "description": "Reviews payments that screening has held: scam indicators in the "
        "reference, behavioural signals and sanctions results, with a risk classification, "
        "explanation and a release, reject or escalate recommendation. Advisory: it never "
        "releases or stops a payment.",
        "adapter": "rule_based_payment_screening",
        "allowed_actions": ["analyze_payment", "recommend_decision", "complete_low_risk_review"],
        "permissions": ["payments:read"],
        "compatible_workflows": ["WF-0002"],
    },
    {
        "tool_id": "agb-credit-underwriting-assistant",
        "tool_name": "AGB Credit Underwriting Assistant",
        "tool_version": "1.0.0",
        "provider": "ATLAS Global Bank (in-house, rule-based proof of concept)",
        "description": "Reviews loan applications the credit policy refers to an "
        "underwriter: declared income against the bureau's estimate, the bureau file and "
        "affordability, with a risk classification, explanation and an approve, reject or "
        "escalate recommendation. Advisory: it never approves or declines a loan.",
        "adapter": "rule_based_credit_underwriting",
        "allowed_actions": [
            "analyze_credit_application",
            "recommend_decision",
            "complete_low_risk_review",
        ],
        "permissions": ["loans:read"],
        "compatible_workflows": ["WF-0003"],
    },
    {
        "tool_id": "agb-overdraft-affordability-assistant",
        "tool_name": "AGB Overdraft Affordability Assistant",
        "tool_version": "1.0.0",
        "provider": "ATLAS Global Bank (in-house, rule-based proof of concept)",
        "description": "Reviews arranged-overdraft requests against the account's recent "
        "history: the limit against a month's money in, how regular that income is and "
        "how often the account is overdrawn, with an explanation and an approve, reject or "
        "escalate recommendation. Advisory: it never sets a limit (Phase 30).",
        "adapter": "rule_based_overdraft_affordability",
        "allowed_actions": ["recommend_decision"],
        "permissions": ["accounts:read"],
        "compatible_workflows": ["WF-1003"],
    },
    {
        "tool_id": "agb-card-fraud-assistant",
        "tool_name": "AGB Card Fraud Alert Assistant",
        "tool_version": "1.0.0",
        "provider": "ATLAS Global Bank (in-house, rule-based proof of concept)",
        "description": "Reviews cards blocked by the fraud rules against the card's history: "
        "where it has been used, its usual amounts, earlier high-risk purchases and bursts of "
        "attempts, with an explanation and a release, keep or escalate recommendation. "
        "Advisory: it never releases a card (Phase 32).",
        "adapter": "rule_based_card_fraud_review",
        "allowed_actions": ["recommend_decision"],
        "permissions": ["accounts:read"],
        "compatible_workflows": ["WF-1008"],
    },
    {
        "tool_id": "agb-mortgage-underwriting-assistant",
        "tool_name": "AGB Mortgage Underwriting Assistant",
        "tool_version": "1.0.0",
        "provider": "ATLAS Global Bank (in-house, rule-based proof of concept)",
        "description": "Reviews mortgage applications that passed the lending rules: stretched "
        "payments, affordability on the bureau's income estimate, income gaps, loan-to-value "
        "and credit, with an explanation and an approve, decline or escalate recommendation. "
        "Advisory: it never issues an offer (Phase 34).",
        "adapter": "rule_based_mortgage_underwriting",
        "allowed_actions": ["recommend_decision"],
        "permissions": ["loans:read"],
        "compatible_workflows": ["WF-1009"],
    },
    {
        "tool_id": "agb-covenant-breach-assistant",
        "tool_name": "AGB Covenant Breach Assistant",
        "tool_version": "1.0.0",
        "provider": "ATLAS Global Bank (in-house, rule-based proof of concept)",
        "description": "Reviews covenant breaches on commercial facilities: debt service cover, "
        "leverage, the EBITDA trend and how much is drawn, with an explanation and a waive, "
        "keep frozen or escalate recommendation. Advisory: it never waives a breach "
        "(Phase 36).",
        "adapter": "rule_based_covenant_review",
        "allowed_actions": ["recommend_decision"],
        "permissions": ["loans:read"],
        "compatible_workflows": ["WF-1013"],
    },
    {
        "tool_id": "agb-document-check-assistant",
        "tool_name": "AGB Document Check Assistant",
        "tool_version": "1.0.0",
        "provider": "ATLAS Global Bank (in-house, rule-based proof of concept)",
        "description": "Reviews discrepant presentations under letters of credit before the "
        "applicant's waiver: the discrepancy, days to expiry, how much is drawn and whether the "
        "applicant can pay, with an explanation and a pay, reject or escalate recommendation. "
        "Advisory: it never pays (Phase 38).",
        "adapter": "rule_based_document_check",
        "allowed_actions": ["recommend_decision"],
        "permissions": ["loans:read"],
        "compatible_workflows": ["WF-1016"],
    },
    {
        "tool_id": "agb-back-office-check-assistant",
        "tool_name": "AGB Back-Office Check Assistant",
        "tool_version": "1.0.0",
        "provider": "ATLAS Global Bank (in-house, rule-based proof of concept)",
        "description": "Checks booked interbank deals before back office confirms them: the rate "
        "against the market, the tenor, the counterparty's rating and limit use and liquidity "
        "cover, with an explanation and a confirm, cancel or escalate recommendation. Advisory: "
        "it never confirms a deal (Phase 40).",
        "adapter": "rule_based_back_office_check",
        "allowed_actions": ["recommend_decision"],
        "permissions": ["payments:read"],
        "compatible_workflows": ["WF-1018"],
    },
    {
        "tool_id": "agb-recall-assistant",
        "tool_name": "AGB Recall Assistant",
        "tool_version": "1.0.0",
        "provider": "ATLAS Global Bank (in-house, rule-based proof of concept)",
        "description": "Reviews recalls of settled payments before back office sends them: the "
        "reason's window, matching duplicates, the payer's history with the beneficiary and the "
        "payment's size, with an explanation and a send, withdraw or escalate recommendation. "
        "Advisory: it never sends a recall (Phase 42).",
        "adapter": "rule_based_recall_review",
        "allowed_actions": ["recommend_decision"],
        "permissions": ["payments:read"],
        "compatible_workflows": ["WF-1023"],
    },
]


def _register_ai_tools(db: Session, report: SeedReport) -> None:
    from app.modules.ai_tools.models import AITool
    from app.modules.ai_tools.schemas import ToolCreate
    from app.modules.ai_tools.service import register_tool

    for spec in DEMO_AI_TOOLS:
        exists = db.execute(
            select(AITool.id).where(
                AITool.tool_id == spec["tool_id"], AITool.tool_version == spec["tool_version"]
            )
        ).first()
        if not exists:
            register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
            report.ai_tools.append(f"{spec['tool_id']} {spec['tool_version']}")
