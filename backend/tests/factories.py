"""Helpers that create test data through the real services (so rules and audit apply)."""

import itertools
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.permissions import RoleCode
from app.core.security import create_access_token
from app.modules.countries.models import Country, Region
from app.modules.employees.models import Employee
from app.modules.employees.schemas import EmployeeCreate
from app.modules.employees.service import create_employee
from app.modules.identity.models import User
from app.modules.identity.schemas import UserCreate
from app.modules.identity.service import create_user
from app.modules.organizations.models import Organization, OrganizationType
from app.modules.organizations.schemas import OrganizationCreate
from app.modules.organizations.service import create_organization

PASSWORD = "correct-horse-battery-staple"
_counter = itertools.count(1)


def country(db: Session, code: str) -> Country:
    return db.execute(select(Country).where(Country.iso_country_code == code)).scalar_one()


def make_user(db: Session, role: RoleCode, username: str | None = None) -> User:
    username = username or f"{role.value.replace('_', '-')}-{next(_counter)}"
    return create_user(
        db,
        UserCreate(
            username=username,
            email=f"{username}@atlasbank.example",
            display_name=username.title(),
            password=PASSWORD,
            role=role,
        ),
        actor_id=None,
    )


def token_for(user: User, ttl: timedelta = timedelta(minutes=5)) -> str:
    secret = get_settings().jwt_secret.get_secret_value()
    return create_access_token(user.id, secret, ttl).token


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(user)}"}


def make_org(
    db: Session,
    name: str,
    org_type: OrganizationType,
    parent: Organization | None = None,
    *,
    country_code: str | None = None,
    region: Region | None = None,
) -> Organization:
    return create_organization(
        db,
        OrganizationCreate(
            name=name,
            organization_type=org_type,
            parent_organization_id=parent.id if parent else None,
            country_id=country(db, country_code).id if country_code else None,
            region=region,
        ),
        actor_id=None,
    )


@dataclass
class OrgTree:
    bank: Organization
    americas: Organization
    europe: Organization
    asia: Organization
    us: Organization
    us_retail: Organization
    us_onboarding: Organization  # department
    us_kyc_team: Organization  # team inside onboarding
    jp: Organization
    jp_retail: Organization
    jp_onboarding: Organization  # department


def make_org_tree(db: Session) -> OrgTree:
    t = OrganizationType
    bank = make_org(db, "ATLAS Global Bank", t.GLOBAL_BANK)
    americas = make_org(db, "Americas HQ", t.REGIONAL_HEADQUARTERS, bank, region=Region.AMERICAS)
    europe = make_org(db, "Europe HQ", t.REGIONAL_HEADQUARTERS, bank, region=Region.EUROPE)
    asia = make_org(
        db, "Asia-Pacific HQ", t.REGIONAL_HEADQUARTERS, bank, region=Region.ASIA_PACIFIC
    )
    us = make_org(db, "ATLAS US", t.COUNTRY_SUBSIDIARY, americas, country_code="US")
    us_retail = make_org(db, "Retail Banking", t.BUSINESS_DIVISION, us)
    us_onboarding = make_org(db, "Customer Onboarding", t.DEPARTMENT, us_retail)
    us_kyc_team = make_org(db, "KYC Review Team", t.TEAM, us_onboarding)
    jp = make_org(db, "ATLAS Japan", t.COUNTRY_SUBSIDIARY, asia, country_code="JP")
    jp_retail = make_org(db, "Retail Banking", t.BUSINESS_DIVISION, jp)
    jp_onboarding = make_org(db, "Customer Onboarding", t.DEPARTMENT, jp_retail)
    return OrgTree(
        bank,
        americas,
        europe,
        asia,
        us,
        us_retail,
        us_onboarding,
        us_kyc_team,
        jp,
        jp_retail,
        jp_onboarding,
    )


def make_employee(
    db: Session,
    organization: Organization,
    *,
    first_name: str = "Avery",
    last_name: str | None = None,
    manager: Employee | None = None,
    compensation: int = 9_500_000,
    job_title: str = "Analyst",
    role: RoleCode = RoleCode.BANKING_EMPLOYEE,
) -> Employee:
    return create_employee(
        db,
        EmployeeCreate(
            first_name=first_name,
            last_name=last_name or unique_surname(),
            organization_id=organization.id,
            manager_id=manager.id if manager else None,
            job_title=job_title,
            role=role,
            annual_compensation=compensation,
        ),
        actor_id=None,
    )


def new_id() -> str:
    return str(uuid.uuid4())


def unique_surname() -> str:
    """A letters-only surname that differs on every call (names may not contain digits)."""
    n = next(_counter)
    letters = ""
    while True:
        n, remainder = divmod(n, 26)
        letters = chr(ord("a") + remainder) + letters
        if n == 0:
            break
    return f"Sample{letters}"


# --- Phase 3: customers, accounts, ledger -------------------------------------------------

from datetime import date  # noqa: E402

from app.core.permissions import permissions_for  # noqa: E402
from app.modules.accounts.models import Account, AccountType  # noqa: E402
from app.modules.accounts.service import approve_request, submit_request  # noqa: E402
from app.modules.customers.models import Customer, CustomerType, KycStatus, RiskRating  # noqa: E402
from app.modules.customers.schemas import CustomerCreate, CustomerReview  # noqa: E402
from app.modules.customers.service import create_customer, review_customer  # noqa: E402
from app.modules.identity.service import AuthenticatedUser  # noqa: E402


def principal(user: User) -> AuthenticatedUser:
    """The service-layer identity of a user (what the API builds from a token)."""
    return AuthenticatedUser(
        id=user.id,
        username=user.username,
        role=user.role.code,
        permissions=permissions_for(user.role.code),
    )


def make_customer(
    db: Session,
    *,
    country_code: str = "US",
    customer_type: CustomerType = CustomerType.INDIVIDUAL,
    name: str | None = None,
    born: date = date(1985, 6, 15),
    kyc: KycStatus | None = KycStatus.VERIFIED,
    risk: RiskRating = RiskRating.LOW,
) -> Customer:
    """A customer, by default KYC-verified with a low risk rating."""
    customer = create_customer(
        db,
        CustomerCreate(
            customer_type=customer_type,
            name=name or f"Customer {unique_surname()}",
            date_of_birth_or_incorporation=born,
            country_id=country(db, country_code).id,
        ),
        actor_id=None,
    )
    if kyc in (KycStatus.PENDING, KycStatus.VERIFIED, KycStatus.REJECTED):
        review_customer(db, customer, CustomerReview(kyc_status=KycStatus.PENDING), None)
    if kyc in (KycStatus.VERIFIED, KycStatus.REJECTED):
        review_customer(db, customer, CustomerReview(kyc_status=kyc, risk_rating=risk), None)
    return customer


@dataclass
class Staff:
    employee: User  # requests accounts, transacts
    manager: User  # approves (not high risk)
    compliance: User  # approves high risk, reviews KYC
    admin: User


def make_staff(db: Session) -> Staff:
    return Staff(
        employee=make_user(db, RoleCode.BANKING_EMPLOYEE),
        manager=make_user(db, RoleCode.DEPARTMENT_MANAGER),
        compliance=make_user(db, RoleCode.COMPLIANCE_OFFICER),
        admin=make_user(db, RoleCode.PLATFORM_ADMINISTRATOR),
    )


def open_account(
    db: Session,
    staff: Staff,
    customer: Customer,
    account_type: AccountType = AccountType.CURRENT,
) -> Account:
    request = submit_request(
        db,
        customer_id=customer.id,
        account_type=account_type,
        currency=None,
        requested_by=staff.employee.id,
    )
    return approve_request(db, request.id, principal(staff.manager))


# --- Phase 4: WF-0001 applications ---------------------------------------------------------

from app.modules.workflows.wf0001 import synthetic_document_number  # noqa: E402


def application(
    *,
    name: str | None = None,
    born: str = "1988-05-04",
    country_code: str = "GB",
    account_type: str = "current",
    documents: list[str] = ("passport", "proof_of_address"),
    **overrides: object,
) -> dict:
    """A valid synthetic WF-0001 application (override fields to break it)."""
    name = name or f"Ada {unique_surname().title()}"
    serial = next(_counter)
    docs = [
        {
            "document_type": kind,
            "document_number": synthetic_document_number(kind, serial * 10 + i),
            "name_on_document": name,
            "date_of_birth": born if kind != "proof_of_address" else None,
            "expiry_date": "2031-01-01" if kind != "proof_of_address" else None,
        }
        for i, kind in enumerate(documents)
    ]
    return {
        "applicant_name": name,
        "date_of_birth": born,
        "country_code": country_code,
        "account_type": account_type,
        "documents": docs,
        **overrides,
    }


# --- Phase 9: payments and loans -----------------------------------------------------------

from app.modules.accounts.service import deposit  # noqa: E402
from app.modules.lending.service import bureau_report  # noqa: E402


def funded_account(
    db: Session,
    staff: Staff,
    *,
    balance: int = 0,
    name: str | None = None,
    born: date = date(1985, 6, 15),
    country_code: str = "US",
) -> Account:
    """An open current account of a new verified customer, with `balance` minor units."""
    customer = make_customer(db, name=name, born=born, country_code=country_code)
    account = open_account(db, staff, customer)
    if balance:
        deposit(
            db,
            account.id,
            amount=balance,
            memo="Opening balance (synthetic)",
            idempotency_key=f"factory-{account.id}",
            actor_id=staff.employee.id,
        )
    return account


def payment(debtor: Account, creditor: Account, amount: int, **overrides: object) -> dict:
    """A valid WF-0002 payment instruction."""
    return {
        "debtor_account_number": debtor.account_number,
        "creditor_account_number": creditor.account_number,
        "amount": amount,
        "currency": debtor.currency,
        "reference": "Invoice 1042",
        **overrides,
    }


def applicant_with_score(low: int, high: int, born: date = date(1980, 3, 9)) -> str:
    """A synthetic name whose (deterministic) bureau score lies in [low, high]."""
    for _ in range(20_000):
        name = f"Lena {unique_surname()}"
        if low <= bureau_report(name, born)["score"] <= high:
            return name
    raise AssertionError(f"No synthetic name scored {low}-{high}.")


def loan_application(
    customer: Customer, account: Account, amount: int, **overrides: object
) -> dict:
    """A valid WF-0003 application with comfortable affordability."""
    return {
        "customer_number": customer.customer_number,
        "disbursement_account_number": account.account_number,
        "amount": amount,
        "term_months": 36,
        "purpose": "home_improvement",
        "monthly_income": 600_000,
        "monthly_debt_payments": 20_000,
        "employment_status": "employed",
        **overrides,
    }


# --- Phase 10: loan servicing --------------------------------------------------------------

from datetime import UTC, datetime  # noqa: E402

from app.modules.accounts.service import withdraw  # noqa: E402
from app.modules.lending.models import Loan  # noqa: E402
from app.modules.lending.service import originate  # noqa: E402

principal_of = principal  # make_loan's `principal` argument shadows the helper


def make_loan(
    db: Session,
    staff: Staff,
    *,
    principal: int = 600_000,
    rate_bps: int = 1200,
    term: int = 12,
    disbursed: date = date(2040, 1, 10),
    keep_funds: bool = False,
) -> Loan:
    """An active loan disbursed on `disbursed` (far in the future, so the lending business
    date, not today's date, decides). Unless `keep_funds`, the borrower then withdraws the
    money, so instalments are missed until they deposit."""
    account = funded_account(db, staff)
    loan = originate(
        db,
        customer_id=account.customer_id,
        account_id=account.id,
        principal=principal,
        annual_rate_bps=rate_bps,
        term_months=term,
        purpose="other",
        requested_by=staff.employee.id,
        underwriter=principal_of(staff.manager),
        committee=None,
        now=datetime.combine(disbursed, datetime.min.time(), tzinfo=UTC).replace(hour=12),
    )
    if not keep_funds:
        withdraw(
            db,
            account.id,
            amount=principal,
            memo="Spent",
            idempotency_key=f"spend-{loan.id}",
            actor_id=staff.employee.id,
        )
    return loan


def top_up(db: Session, staff: Staff, loan: Loan, amount: int) -> None:
    deposit(
        db,
        loan.disbursement_account_id,
        amount=amount,
        memo="Top-up (synthetic)",
        idempotency_key=f"top-up-{loan.id}-{next(_counter)}",
        actor_id=staff.employee.id,
    )
