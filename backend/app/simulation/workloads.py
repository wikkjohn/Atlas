"""Workloads: what a scenario simulates, beyond the workflow it runs.

A workload knows how to produce a scenario's synthetic cases with their ground truth
(creating any pre-existing customers and accounts the cases need), which simulated staff
role decides each approval step, where the AI step and the automated decision live in an
execution's context, and how to re-check every decision its cases made against the bank's
authorization rules. The runner and the experiment measurements stay workflow-neutral.

Every random draw comes from `case_random(seed, index, purpose)`, so the same seed always
produces the same cases. Account numbers and other database identifiers differ between
runs; nothing that must reproduce depends on them.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import Text, cast, select
from sqlalchemy.orm import Session

from app.core.money import to_minor_units
from app.core.permissions import Permission, RoleCode, permissions_for
from app.modules.accounts.models import Account, AccountRequest, AccountType
from app.modules.accounts.service import approve_request, deposit, submit_request
from app.modules.countries.models import Country
from app.modules.customers.models import Customer, CustomerType, KycStatus, RiskRating
from app.modules.customers.schemas import CustomerCreate, CustomerReview
from app.modules.customers.service import create_customer, review_customer
from app.modules.identity.models import Role, User
from app.modules.lending import service as lending
from app.modules.lending.models import Loan
from app.modules.payments import service as payments
from app.modules.payments.models import Payment, PaymentStatus
from app.modules.workflows.models import WorkflowExecution
from app.simulation.generators import (
    FIRST_NAMES,
    LAST_NAMES,
    WATCHLIST_NAMES,
    ApplicationGenerator,
    case_random,
)
from app.simulation.scenarios import ApplicationMix, Scenario, normalized

if TYPE_CHECKING:
    from app.simulation.runner import _Simulation


@dataclass(frozen=True)
class WaitSignal:
    """A signal the simulated customer sends while a case waits (e.g. late documents)."""

    delay_seconds: int
    signal: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class SyntheticCase:
    index: int
    kind: str  # one of the workload's case kinds
    expected_outcome: str  # ground truth: "approved" or "rejected"
    arrival_offset_seconds: int
    payload: dict[str, Any]
    wait_signal: WaitSignal | None = None


@dataclass
class ControlCheck:
    """The decisions a run's cases made and every authorization rule they broke."""

    decisions: int = 0
    violations: list[dict[str, Any]] = field(default_factory=list)


class Workload:
    key: ClassVar[str]
    workflow_id: ClassVar[str]
    kinds: ClassVar[frozenset[str]]
    # Approval step -> simulated staff role that decides it.
    reviewer_roles: ClassVar[dict[str, str]]
    job_titles: ClassVar[dict[str, str]]
    ai_step: ClassVar[str | None] = None  # context key of the advisory AI step
    automated_path: ClassVar[str | None] = None  # context path: truthy = decided by policy
    escalation_steps: ClassVar[frozenset[str]] = frozenset()

    def customers(self, cases: int) -> int:
        """How many synthetic customers a run of this size creates."""
        return cases

    def cases(self, sim: "_Simulation") -> list[SyntheticCase]:
        raise NotImplementedError

    def check_controls(self, db: Session, run_id: uuid.UUID) -> ControlCheck:
        raise NotImplementedError

    def validate(self, scenario: Scenario) -> None:
        unknown = set(scenario.config.mix) - self.kinds
        if unknown:
            raise ValueError(f"{scenario.scenario_id}: unknown case kinds {sorted(unknown)}")
        steps = set(scenario.config.reviewers)
        if steps != set(self.reviewer_roles):
            raise ValueError(f"{scenario.scenario_id}: reviewers must cover {self.reviewer_roles}")
        missing = set(self.reviewer_roles.values()) - set(scenario.config.staff_mix)
        if missing or "teller" not in scenario.config.staff_mix:
            raise ValueError(f"{scenario.scenario_id}: the staff mix lacks {sorted(missing)}")


def _roles(db: Session) -> dict[uuid.UUID, frozenset[Permission]]:
    return {
        role_id: permissions_for(code) for role_id, code in db.execute(select(Role.id, Role.code))
    }


def _pick(rng, mix: dict[str, float]) -> str:
    kinds = sorted(mix)
    return rng.choices(kinds, weights=[mix[k] for k in kinds])[0]


# --- Retail onboarding (WF-0001) -------------------------------------------------------------


class RetailOnboarding(Workload):
    key = "retail_onboarding"
    workflow_id = "WF-0001"
    kinds = frozenset(ApplicationMix.model_fields)
    reviewer_roles = {"account_approval": "manager", "compliance_review": "compliance"}
    job_titles = {
        "teller": "Customer Onboarding Officer",
        "manager": "Onboarding Team Manager",
        "compliance": "KYC Compliance Analyst",
    }
    ai_step = "ai_kyc_review"
    automated_path = "policy_approval.approved"
    escalation_steps = frozenset({"compliance_review"})

    def cases(self, sim: "_Simulation") -> list[SyntheticCase]:
        config = sim.config
        low, high = config.document_delay_hours or (2.0, 48.0)
        generator = ApplicationGenerator(
            seed=sim.seed,
            mix=normalized(config.mix),
            countries=sim.countries,
            arrival_window_seconds=int(config.arrival_window_hours * 3600),
            document_delay_seconds=(int(low * 3600), int(high * 3600)),
            today=sim.clock.start.date(),
        )
        out = []
        for app in generator.generate(sim.applications):
            late = app.payload.get("_late_document")
            payload = {k: v for k, v in app.payload.items() if not k.startswith("_")}
            signal = (
                WaitSignal(app.document_delay_seconds, "documents_submitted", {"documents": [late]})
                if late and app.document_delay_seconds is not None
                else None  # abandoned: the documents never arrive and the wait times out
            )
            out.append(
                SyntheticCase(
                    app.index,
                    app.kind,
                    app.expected_outcome,
                    app.arrival_offset_seconds,
                    payload,
                    signal,
                )
            )
        return out

    def check_controls(self, db: Session, run_id: uuid.UUID) -> ControlCheck:
        """Every account decision against four-eyes, authority and the risk rules."""
        request_id = WorkflowExecution.context["open_account"]["account_request_id"].astext
        rows = db.execute(
            select(AccountRequest, Customer.risk_rating, User.role_id, User.username)
            .join(WorkflowExecution, request_id == cast(AccountRequest.id, Text))
            .join(Customer, Customer.id == AccountRequest.customer_id)
            .join(User, User.id == AccountRequest.decided_by)
            .where(WorkflowExecution.simulation_run_id == run_id)
        ).all()
        roles = _roles(db)
        check = ControlCheck(decisions=len(rows))
        for request, risk, role_id, username in rows:
            permissions = roles.get(role_id, frozenset())
            found = []
            if request.decided_by == request.requested_by:
                found.append("four_eyes")
            full = Permission.ACCOUNTS_APPROVE in permissions
            if not full and Permission.ACCOUNTS_APPROVE_LOW_RISK not in permissions:
                found.append("decider_without_authority")
            if not full and risk != RiskRating.LOW:
                found.append("limited_approver_beyond_low_risk")
            if risk == RiskRating.HIGH and Permission.CUSTOMERS_REVIEW not in permissions:
                found.append("high_risk_without_compliance")
            check.violations += [
                {"rule": rule, "account_request_id": str(request.id), "decided_by": username}
                for rule in found
            ]
        return check


# --- Shared population helpers -----------------------------------------------------------------


def _currencies(db: Session) -> dict[str, str]:
    return dict(db.execute(select(Country.iso_country_code, Country.default_currency)).all())


def _customer_account(
    sim: "_Simulation",
    *,
    name: str,
    born: date,
    country_code: str,
    balance: int = 0,
) -> Account:
    """A pre-existing, KYC-verified customer of the bank with an open current account."""
    db = sim.db
    country_id = db.execute(
        select(Country.id).where(Country.iso_country_code == country_code)
    ).scalar_one()
    customer = create_customer(
        db,
        CustomerCreate(
            customer_type=CustomerType.INDIVIDUAL,
            name=name,
            date_of_birth_or_incorporation=born,
            country_id=country_id,
        ),
        actor_id=None,
        today=sim.clock.start.date(),
    )
    review_customer(db, customer, CustomerReview(kyc_status=KycStatus.PENDING), None)
    review_customer(
        db,
        customer,
        CustomerReview(kyc_status=KycStatus.VERIFIED, risk_rating=RiskRating.LOW),
        None,
    )
    teller, manager = sim.population_staff()
    request = submit_request(
        db,
        customer_id=customer.id,
        account_type=AccountType.CURRENT,
        currency=None,
        requested_by=teller.id,
    )
    account = approve_request(
        db, request.id, manager, "Existing customer (simulation population)", now=sim.history_at
    )
    if balance:
        deposit(
            db,
            account.id,
            amount=balance,
            memo="Opening balance (synthetic)",
            idempotency_key=f"sim-{sim.run_id}-{account.id}",
            actor_id=teller.id,
        )
    return account


def _person(rng, today: date, min_age: int = 21, max_age: int = 75) -> tuple[str, date]:
    age = rng.randint(min_age, max_age)
    born = date(today.year - age, rng.randint(1, 12), rng.randint(1, 28))
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}", born


# --- Domestic payments (WF-0002) ---------------------------------------------------------------

ORDINARY_REFERENCES = (
    "Rent",
    "Invoice {n}",
    "Groceries split",
    "Car repair",
    "Tuition instalment",
    "Holiday share",
    "Utilities",
    "Birthday present",
)
SCAM_REFERENCES = (
    "Gift card purchase",
    "Crypto wallet top-up",
    "Lottery release fee",
    "Investment opportunity deposit",
    "Customs fee for parcel",
    "Move to safe account",
)
PAYEES_PER_COUNTRY = 12
PAYMENT_SHOULD_REJECT = frozenset({"scam", "quiet_scam", "watchlisted_payee", "insufficient_funds"})
# Kinds that pay someone the debtor has paid before.
KNOWN_PAYEE = frozenset({"routine", "high_value", "insufficient_funds"})


class DomesticPayments(Workload):
    key = "domestic_payments"
    workflow_id = "WF-0002"
    kinds = frozenset(
        {
            "routine",
            "new_payee",
            "high_value",
            "large_share",
            "scam",
            "quiet_scam",
            "watchlisted_payee",
            "insufficient_funds",
        }
    )
    reviewer_roles = {"fraud_review": "compliance", "payment_approval": "manager"}
    job_titles = {
        "teller": "Payments Operations Officer",
        "manager": "Payments Team Manager",
        "compliance": "Fraud Analyst",
    }
    ai_step = "ai_fraud_review"
    automated_path = "policy_release.approved"
    escalation_steps = frozenset({"fraud_review"})

    def customers(self, cases: int) -> int:
        # One paying customer per case, plus the payees (bounded per country).
        return cases

    def cases(self, sim: "_Simulation") -> list[SyntheticCase]:
        db = sim.db
        mix = normalized(sim.config.mix)
        currencies = _currencies(db)
        today = sim.clock.start.date()
        window = int(sim.config.arrival_window_hours * 3600)
        payees: dict[tuple[str, int], Account] = {}
        watchlisted: dict[tuple[str, str], Account] = {}

        def payee(country: str, slot: int) -> Account:
            if (country, slot) not in payees:
                rng = case_random(sim.seed, slot, f"payee:{country}")
                name, born = _person(rng, today)
                payees[(country, slot)] = _customer_account(
                    sim, name=name, born=born, country_code=country
                )
            return payees[(country, slot)]

        def watchlist_payee(country: str, name: str) -> Account:
            if (country, name) not in watchlisted:
                watchlisted[(country, name)] = _customer_account(
                    sim, name=name, born=date(1970, 1, 1), country_code=country
                )
            return watchlisted[(country, name)]

        out: list[SyntheticCase] = []
        for index in range(sim.applications):
            rng = case_random(sim.seed, index, "payment")
            kind = _pick(rng, mix)
            country = rng.choice(sim.countries)
            currency = currencies[country]
            name, born = _person(rng, today)
            major = (
                rng.randint(50_000, 200_000) if kind == "high_value" else rng.randint(2_000, 10_000)
            )
            balance = to_minor_units(major, currency)
            debtor = _customer_account(
                sim, name=name, born=born, country_code=country, balance=balance
            )
            known, fresh = rng.sample(range(PAYEES_PER_COUNTRY), 2)
            if kind in KNOWN_PAYEE:
                creditor = payee(country, known)
                # A payment last week makes this a payee the customer already knows.
                history = max(1, balance // 100)
                earlier = payments.create_payment(
                    db,
                    debtor=debtor,
                    creditor=creditor,
                    amount=history,
                    reference="Previous payment",
                    initiated_by=sim.population_staff()[0].id,
                    now=sim.history_at,
                )
                payments.release(db, earlier.id, approver=None, now=sim.history_at)
                balance -= history
            elif kind == "watchlisted_payee":
                creditor = watchlist_payee(country, rng.choice(WATCHLIST_NAMES))
            else:
                creditor = payee(country, fresh)
            share = {
                "routine": (0.02, 0.2),
                "new_payee": (0.02, 0.3),
                "large_share": (0.85, 0.98),
                "scam": (0.3, 0.7),
                "quiet_scam": (0.85, 0.98),
                "watchlisted_payee": (0.1, 0.5),
                "insufficient_funds": (1.01, 1.5),
            }.get(kind)
            if kind == "high_value":
                amount = to_minor_units(rng.randint(10_000, 40_000), currency)
            else:
                assert share is not None
                amount = max(1, int(balance * rng.uniform(*share)))
            reference = (
                rng.choice(SCAM_REFERENCES)
                if kind == "scam"
                else rng.choice(ORDINARY_REFERENCES).format(n=rng.randint(1000, 9999))
            )
            out.append(
                SyntheticCase(
                    index=index,
                    kind=kind,
                    expected_outcome="rejected" if kind in PAYMENT_SHOULD_REJECT else "approved",
                    arrival_offset_seconds=rng.randint(0, window),
                    payload={
                        "debtor_account_number": debtor.account_number,
                        "creditor_account_number": creditor.account_number,
                        "amount": amount,
                        "currency": currency,
                        "reference": reference,
                        "channel": rng.choice(["online", "mobile", "branch"]),
                    },
                )
            )
        return out

    def check_controls(self, db: Session, run_id: uuid.UUID) -> ControlCheck:
        """Every released payment against four-eyes and the approval authority rules."""
        rows = db.execute(
            select(Payment, User.role_id, User.username)
            .join(WorkflowExecution, WorkflowExecution.id == Payment.workflow_execution_id)
            .outerjoin(User, User.id == Payment.approved_by)
            .where(
                WorkflowExecution.simulation_run_id == run_id,
                Payment.status == PaymentStatus.RELEASED,
            )
        ).all()
        roles = _roles(db)
        check = ControlCheck(decisions=len(rows))
        limited = (
            Permission.PAYMENTS_APPROVE,
            Permission.PAYMENTS_REVIEW,
            Permission.PAYMENTS_RELEASE_LOW_RISK,
        )
        for payment, role_id, username in rows:
            high_value = payments.is_high_value(payment.amount, payment.currency)
            permissions = roles.get(role_id, frozenset()) if role_id else frozenset()
            found = []
            if payment.approved_by is None:
                if high_value:
                    found.append("high_value_without_approval")
            else:
                if payment.approved_by == payment.initiated_by:
                    found.append("four_eyes")
                if high_value and Permission.PAYMENTS_APPROVE not in permissions:
                    found.append("high_value_without_authority")
                if not any(p in permissions for p in limited):
                    found.append("approver_without_authority")
            check.violations += [
                {"rule": rule, "payment_number": payment.payment_number, "decided_by": username}
                for rule in found
            ]
        return check


# --- Personal loans (WF-0003) ------------------------------------------------------------------

LOAN_SHOULD_REJECT = frozenset({"poor_credit", "overextended", "inflated_income"})
SCORE_BANDS = {
    "prime": (720, 850),
    "near_prime": (640, 719),
    "self_employed": (680, 850),
    "large_loan": (720, 850),
    "poor_credit": (300, 559),
    "overextended": (680, 850),
    "inflated_income": (660, 850),
}


class PersonalLoans(Workload):
    key = "personal_loans"
    workflow_id = "WF-0003"
    kinds = frozenset(SCORE_BANDS)
    reviewer_roles = {"underwriting_review": "manager", "credit_committee": "executive"}
    job_titles = {
        "teller": "Lending Officer",
        "manager": "Credit Underwriter",
        "executive": "Credit Committee Member",
    }
    escalation_steps = frozenset({"credit_committee"})

    def cases(self, sim: "_Simulation") -> list[SyntheticCase]:
        mix = normalized(sim.config.mix)
        currencies = _currencies(sim.db)
        today = sim.clock.start.date()
        window = int(sim.config.arrival_window_hours * 3600)
        out: list[SyntheticCase] = []
        for index in range(sim.applications):
            rng = case_random(sim.seed, index, "loan")
            kind = _pick(rng, mix)
            country = rng.choice(sim.countries)
            currency = currencies[country]
            low, high = SCORE_BANDS[kind]
            for _ in range(2_000):  # names are drawn until the bureau score fits the kind
                name, born = _person(rng, today, 25, 64)
                if low <= lending.bureau_report(name, born)["score"] <= high:
                    break
            else:
                raise ValueError(f"No synthetic applicant found for {kind}.")
            account = _customer_account(sim, name=name, born=born, country_code=country)
            if kind == "large_loan":
                amount, income = rng.randint(26_000, 50_000), rng.randint(12_000, 25_000)
                term = rng.choice([60, 72, 84])
            else:
                amount, income = rng.randint(5_000, 20_000), rng.randint(4_000, 9_000)
                term = rng.choice([24, 36, 48, 60])
            debt_share = rng.uniform(0.45, 0.6) if kind == "overextended" else rng.uniform(0, 0.1)
            employment = (
                "self_employed"
                if kind == "self_employed"
                else "retired"
                if rng.random() < 0.1
                else "employed"
            )
            out.append(
                SyntheticCase(
                    index=index,
                    kind=kind,
                    expected_outcome="rejected" if kind in LOAN_SHOULD_REJECT else "approved",
                    arrival_offset_seconds=rng.randint(0, window),
                    payload={
                        "customer_number": account.customer.customer_number,
                        "disbursement_account_number": account.account_number,
                        "amount": to_minor_units(amount, currency),
                        "term_months": term,
                        "purpose": rng.choice(
                            ["home_improvement", "vehicle", "education", "debt_consolidation"]
                        ),
                        "monthly_income": to_minor_units(income, currency),
                        "monthly_debt_payments": to_minor_units(int(income * debt_share), currency),
                        "employment_status": employment,
                    },
                )
            )
        return out

    def check_controls(self, db: Session, run_id: uuid.UUID) -> ControlCheck:
        """Every loan against four-eyes, underwriting authority and the committee rule."""
        underwriter, committee = User.__table__.alias(), User.__table__.alias()
        rows = db.execute(
            select(Loan, underwriter.c.role_id, committee.c.role_id)
            .join(WorkflowExecution, WorkflowExecution.id == Loan.workflow_execution_id)
            .join(underwriter, underwriter.c.id == Loan.underwritten_by)
            .outerjoin(committee, committee.c.id == Loan.committee_approved_by)
            .where(WorkflowExecution.simulation_run_id == run_id)
        ).all()
        roles = _roles(db)
        check = ControlCheck(decisions=len(rows))
        for loan, underwriter_role, committee_role in rows:
            found = []
            if loan.underwritten_by == loan.requested_by:
                found.append("four_eyes")
            if Permission.LOANS_APPROVE not in roles.get(underwriter_role, frozenset()):
                found.append("underwriter_without_authority")
            if lending.needs_committee(loan.principal, loan.currency):
                if loan.committee_approved_by is None:
                    found.append("committee_missing")
                elif Permission.LOANS_APPROVE_LARGE not in roles.get(committee_role, frozenset()):
                    found.append("committee_without_authority")
            check.violations += [{"rule": rule, "loan_number": loan.loan_number} for rule in found]
        return check


WORKLOADS: dict[str, Workload] = {
    w.key: w for w in (RetailOnboarding(), DomesticPayments(), PersonalLoans())
}
STAFF_ROLES = {
    "teller": RoleCode.BANKING_EMPLOYEE,
    "manager": RoleCode.DEPARTMENT_MANAGER,
    "compliance": RoleCode.COMPLIANCE_OFFICER,
    "executive": RoleCode.REGIONAL_EXECUTIVE,
}
POPULATION_HISTORY = timedelta(days=7)  # pre-existing accounts are a week old


def workload_for(scenario: Scenario) -> Workload:
    return WORKLOADS[scenario.workload]


def history_time(start: datetime) -> datetime:
    return (start - POPULATION_HISTORY).astimezone(UTC)
