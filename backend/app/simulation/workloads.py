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

from sqlalchemy import Text, Uuid, and_, cast, func, select
from sqlalchemy.orm import Session

from app.core.money import to_minor_units
from app.core.permissions import Permission, RoleCode, permissions_for
from app.modules.accounts.models import Account, AccountRequest, AccountType
from app.modules.accounts.service import approve_request, deposit, submit_request
from app.modules.compliance.screening import SANCTIONS_LISTS
from app.modules.countries.models import Country
from app.modules.customers.models import Customer, CustomerType, KycStatus, RiskRating
from app.modules.customers.schemas import CustomerCreate, CustomerReview
from app.modules.customers.service import create_customer, review_customer
from app.modules.identity.models import Role, User
from app.modules.ledger import service as ledger
from app.modules.lending import service as lending
from app.modules.lending.models import Loan
from app.modules.payments import service as payments
from app.modules.payments.models import Payment, PaymentStatus
from app.modules.workflows.models import Realm, WorkflowExecution
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


# Workflows whose business key is the id of the customer the case is about (WF-0002 keys
# payments by payment number, WF-0004 by loan id).
CUSTOMER_KEYED_WORKFLOWS = ("WF-0001", "WF-0003")


def customer_keyed(executions_filter):
    """Customer ids of the executions matching `executions_filter` that key on one."""
    return select(func.cast(WorkflowExecution.business_key, Uuid)).where(
        executions_filter,
        WorkflowExecution.workflow_id.in_(CUSTOMER_KEYED_WORKFLOWS),
        WorkflowExecution.business_key.is_not(None),
    )


def _in_run(run_id: uuid.UUID):
    """The run's executions, all in the simulation partition."""
    return and_(
        WorkflowExecution.realm == Realm.SIMULATION, WorkflowExecution.simulation_run_id == run_id
    )


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
            rules=sim.country_rules,
        )
        out = []
        for app in generator.generate_indices(sim.case_indices):
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
            .where(_in_run(run_id))
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
        rules = sim.country_rules
        for index in sim.case_indices:
            rng = case_random(sim.seed, index, "payment")
            kind = _pick(rng, mix)
            country = rng.choice(sim.countries)
            currency = currencies[country]
            name, born = _person(rng, today)
            if rules is not None:
                # Amounts on the country's own scale (Phase 28): ordinary balances stay below
                # its high-value threshold, high-value payments sit between the threshold and
                # the payment limit.
                threshold = rules[country]["high_value_major"]
                limit = rules[country]["max_payment_major"]
                high_value_major = rng.randint(threshold, min(4 * threshold, limit))
                major = (
                    high_value_major * rng.randint(2, 4)
                    if kind == "high_value"
                    else rng.randint(max(1, threshold // 5), max(1, threshold - 1))
                )
            else:
                major = (
                    rng.randint(50_000, 200_000)
                    if kind == "high_value"
                    else rng.randint(2_000, 10_000)
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
                names = WATCHLIST_NAMES
                if rules is not None:
                    # A name on a list the payer's country screens against.
                    names = tuple(
                        sorted(
                            n.title()
                            for list_id in rules[country]["lists"]
                            for n in SANCTIONS_LISTS[list_id][1]
                        )
                    )
                creditor = watchlist_payee(country, rng.choice(names))
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
            if kind == "high_value" and rules is not None:
                amount = to_minor_units(high_value_major, currency)
            elif kind == "high_value":
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
                _in_run(run_id),
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
            high_value = payments.payment_is_high_value(payment)
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
        for index in sim.case_indices:
            rng = case_random(sim.seed, index, "loan")
            kind = _pick(rng, mix)
            country = rng.choice(sim.countries)
            currency = currencies[country]
            low, high = SCORE_BANDS[kind]
            for _ in range(2_000):  # names are drawn until the bureau file fits the kind
                name, born = _person(rng, today, 25, 64)
                if low <= lending.bureau_report(name, born)["score"] <= high and self.fits(
                    kind, name, born
                ):
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
            income = self.declared_income(sim.seed, index, kind, name, born, income)
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

    def fits(self, kind: str, name: str, born: date) -> bool:
        """Further conditions on a synthetic applicant beyond the score band."""
        return True

    def declared_income(
        self, seed: int, index: int, kind: str, name: str, born: date, drawn: int
    ) -> int:
        """The monthly income (major units) the applicant declares."""
        return drawn

    def check_controls(self, db: Session, run_id: uuid.UUID) -> ControlCheck:
        """Every loan against four-eyes, underwriting authority and the committee rule."""
        underwriter, committee = User.__table__.alias(), User.__table__.alias()
        rows = db.execute(
            select(Loan, underwriter.c.role_id, committee.c.role_id)
            .join(WorkflowExecution, WorkflowExecution.id == Loan.workflow_execution_id)
            .join(underwriter, underwriter.c.id == Loan.underwritten_by)
            .outerjoin(committee, committee.c.id == Loan.committee_approved_by)
            .where(_in_run(run_id))
        ).all()
        roles = _roles(db)
        check = ControlCheck(decisions=len(rows))
        for loan, underwriter_role, committee_role in rows:
            found = []
            if loan.underwritten_by == loan.requested_by:
                found.append("four_eyes")
            authority = roles.get(underwriter_role, frozenset())
            if Permission.LOANS_APPROVE not in authority and not (
                Permission.LOANS_APPROVE_LOW_RISK in authority
                and lending.within_automation_limit(loan.principal, loan.currency)
            ):
                found.append("underwriter_without_authority")
            if lending.needs_committee(loan.principal, loan.currency):
                if loan.committee_approved_by is None:
                    found.append("committee_missing")
                elif Permission.LOANS_APPROVE_LARGE not in roles.get(committee_role, frozenset()):
                    found.append("committee_without_authority")
            check.violations += [{"rule": rule, "loan_number": loan.loan_number} for rule in found]
        return check


# Declared income / the bureau's income estimate, by kind (personal-loans v2). Honest
# applicants declare about what the estimate says; self-employed ones legitimately vary
# more; inflated incomes are well above it.
INCOME_RATIOS = {
    "self_employed": (0.9, 1.6),
    "inflated_income": (1.5, 2.3),
}
HONEST_INCOME_RATIO = (0.8, 1.12)
LARGE_LOAN_MIN_ESTIMATE = 7_000  # large loans go to applicants who can afford them


class PersonalLoansWithIncomeCheck(PersonalLoans):
    """WF-0003 v2: incomes are declared relative to the bureau's income estimate, so the
    income check (and the AI underwriting assistant that uses it) has something to find."""

    key = "personal_loans_income"
    ai_step = "ai_underwriting_review"
    automated_path = "policy_underwrite.approved"

    def fits(self, kind: str, name: str, born: date) -> bool:
        return (
            kind != "large_loan" or lending.income_estimate(name, born) >= LARGE_LOAN_MIN_ESTIMATE
        )

    def declared_income(
        self, seed: int, index: int, kind: str, name: str, born: date, drawn: int
    ) -> int:
        low, high = INCOME_RATIOS.get(kind, HONEST_INCOME_RATIO)
        ratio = case_random(seed, index, "loan-income").uniform(low, high)
        return round(lending.income_estimate(name, born) * ratio)


# --- Retail overdrafts (WF-1003 v2, Phase 30) -----------------------------------------------------

OVERDRAFT_SHOULD_REJECT = frozenset(
    {"stretched", "habitual_overdraft", "irregular_income", "over_maximum"}
)
# Salary days before the simulated start: one in each 30-day window of the last 90 days.
SALARY_DAYS = (88, 58, 28)


def _usd(amount: float, currency: str) -> int:
    """Whole US dollars as minor units of `currency`, at the FX anchor rate."""
    from decimal import Decimal

    from app.core.money import minor_unit_exponent
    from app.modules.fx import rates

    units = Decimal(str(amount)) * rates.units_per_usd(currency, rates.ANCHOR_DATE)
    return int(units * 10 ** minor_unit_exponent(currency))


class RetailOverdrafts(Workload):
    """Arranged-overdraft requests through WF-1003 v2: existing customers with three months
    of account history in the ledger, asking for an overdraft a credit officer decides on,
    with the AGB Overdraft Affordability Assistant's advice in AI-assisted runs.

    Ground truth: affordable requests from steady earners are approved; limits large against
    income, irregular income, a customer already living in an overdraft, and limits above
    the product's maximum are declined."""

    key = "retail_overdrafts"
    workflow_id = "WF-1003"
    kinds = frozenset({"steady_small", "steady_large"} | OVERDRAFT_SHOULD_REJECT)
    reviewer_roles = {"credit_decision": "manager"}
    job_titles = {"teller": "Customer Service Officer", "manager": "Retail Credit Officer"}
    ai_step = "ai_review"
    automated_path = None  # no policy engine: a person always decides

    def cases(self, sim: "_Simulation") -> list[SyntheticCase]:
        from app.modules.ledger.models import Direction
        from app.modules.retail import service as retail

        db = sim.db
        mix = normalized(sim.config.mix)
        currencies = _currencies(db)
        start = sim.clock.start
        today = start.date()
        window = int(sim.config.arrival_window_hours * 3600)
        product = retail.get_product(db, "current")
        out: list[SyntheticCase] = []
        for index in sim.case_indices:
            rng = case_random(sim.seed, index, "overdraft")
            kind = _pick(rng, mix)
            country = rng.choice(sim.countries)
            currency = currencies[country]
            ceiling = retail.max_overdraft(product, currency)
            name, born = _person(rng, today)
            account = _customer_account(sim, name=name, born=born, country_code=country)
            account.opened_at = start - timedelta(days=120)
            cash = ledger.cash_account(db, currency)

            def post(
                amount: int, days_before: int, label: str, *, _a=account, _c=cash, _ccy=currency
            ) -> None:
                inbound = amount > 0
                ledger.post_entry(
                    db,
                    idempotency_key=f"sim-{sim.run_id}-{_a.id}-{label}",
                    currency=_ccy,
                    description="Salary" if inbound else "Card spending",
                    source="simulation",
                    lines=[
                        ledger.LineSpec(
                            _c.id, Direction.DEBIT if inbound else Direction.CREDIT, abs(amount)
                        ),
                        ledger.LineSpec(
                            _a.ledger_account_id,
                            Direction.CREDIT if inbound else Direction.DEBIT,
                            abs(amount),
                        ),
                    ],
                    actor_id=None,
                    effective_date=today - timedelta(days=days_before),
                )

            salary_usd = {
                "steady_small": rng.uniform(2_000, 6_000),
                "steady_large": rng.uniform(1_500, 2_600),
                "stretched": rng.uniform(600, 1_200),
                "habitual_overdraft": rng.uniform(2_500, 5_000),
                "irregular_income": rng.uniform(3_000, 6_000),
                "over_maximum": rng.uniform(5_000, 9_000),
            }[kind]
            salary = _usd(round(salary_usd), currency)
            share = {
                "steady_small": (0.1, 0.3),
                "steady_large": (0.6, 0.9),
                "stretched": (1.5, 2.0),
                "habitual_overdraft": (0.3, 0.5),
                "irregular_income": (0.4, 0.6),
            }.get(kind)
            if kind == "over_maximum":
                limit = int(ceiling * rng.uniform(1.2, 2.0))
            else:
                assert share is not None
                limit = min(int(salary * rng.uniform(*share)), int(ceiling * 0.95))
            paydays = SALARY_DAYS[1:2] if kind == "irregular_income" else SALARY_DAYS
            for n, days in enumerate(paydays):
                post(salary, days, f"salary-{n}")
                if kind == "habitual_overdraft":
                    # Spends the salary and more the next day: overdrawn almost every day.
                    account.overdraft_limit = max(account.overdraft_limit, limit // 2)
                    post(-(salary + limit // 3), days - 1, f"spend-{n}")
                else:
                    post(-int(salary * rng.uniform(0.6, 0.9)), days - 3, f"spend-{n}")
            out.append(
                SyntheticCase(
                    index=index,
                    kind=kind,
                    expected_outcome="rejected" if kind in OVERDRAFT_SHOULD_REJECT else "approved",
                    arrival_offset_seconds=rng.randint(0, window),
                    payload={
                        "customer_number": account.customer.customer_number,
                        "account_number": account.account_number,
                        "limit": max(0, limit),
                    },
                )
            )
        db.flush()
        return out

    def check_controls(self, db: Session, run_id: uuid.UUID) -> ControlCheck:
        """Every credit decision against four-eyes and authority, and every limit set
        only after an approval."""
        from app.modules.workflows.models import STEP_RUN_EXECUTION, WorkflowStepRun

        runs = db.execute(
            select(WorkflowStepRun, WorkflowExecution, User.role_id, User.username)
            .join(WorkflowExecution, STEP_RUN_EXECUTION)
            .outerjoin(User, User.id == WorkflowStepRun.actor_id)
            .where(
                _in_run(run_id),
                WorkflowStepRun.step_id.in_(["credit_decision", "set_limit"]),
                WorkflowStepRun.status == "completed",
            )
        ).all()
        roles = _roles(db)
        approved: set[uuid.UUID] = set()
        decisions = []
        for step_run, execution, role_id, username in runs:
            if step_run.step_id == "credit_decision":
                decisions.append((step_run, execution, role_id, username))
                if (step_run.output or {}).get("approved"):
                    approved.add(execution.id)
        check = ControlCheck(decisions=len(decisions))
        for step_run, execution, role_id, username in decisions:
            permissions = roles.get(role_id, frozenset())
            if step_run.actor_id == execution.initiated_by:
                check.violations.append({"rule": "four_eyes", "decided_by": username})
            if Permission.ACCOUNTS_APPROVE not in permissions:
                check.violations.append(
                    {"rule": "decider_without_authority", "decided_by": username}
                )
        for step_run, execution, _, _ in runs:
            if step_run.step_id == "set_limit" and execution.id not in approved:
                check.violations.append(
                    {"rule": "limit_without_approval", "execution_id": str(execution.id)}
                )
        return check


# --- Card fraud alerts (WF-1008 v2, Phase 32) ------------------------------------------------

FRAUD_KINDS = frozenset({"stolen_abroad", "account_takeover", "card_testing"})
# Countries purchases abroad happen in (any but the customer's own).
TRAVEL_COUNTRIES = ("FR", "ES", "IT", "PT", "GR", "TR", "TH", "MX", "JP", "AE", "US", "GB")
FRAUD_COUNTRIES = ("KY", "PA", "MT", "CY", "BZ", "SC")
HOME_MERCHANTS = (("5411", "Corner Grocer"), ("5812", "High Street Cafe"), ("5541", "City Fuel"),
                  ("5942", "Book Nook"), ("5912", "Pharmacy Plus"))  # fmt: skip
TRIP_MERCHANTS = (("5812", "Harbour Restaurant"), ("7011", "Seaview Hotel"),
                  ("4111", "Metro Transit"), ("5411", "Local Market"))  # fmt: skip


class CardFraudAlerts(Workload):
    """Cards blocked by the fraud rules, reviewed through WF-1008 v2: existing customers
    whose card history the workload builds through the real authorisation service, so the
    real fraud rules decline the last purchase and block the card. A fraud analyst decides
    whether to release the block, with the AGB Card Fraud Alert Assistant's advice in
    AI-assisted runs.

    Ground truth: travellers (a casino on a trip, or a large one) and a regular crypto buyer
    buying in a hurry are genuine, and the block is released; a stolen card used abroad, an
    account takeover spending fast in a new country, and card testing (tiny purchases, then
    a high-risk one, at home) are fraud, and the card stays blocked."""

    key = "card_fraud_alerts"
    workflow_id = "WF-1008"
    kinds = frozenset({"traveller", "big_spender_abroad", "crypto_investor"} | FRAUD_KINDS)
    reviewer_roles = {"fraud_review": "manager"}
    job_titles = {"teller": "Card Services Officer", "manager": "Card Fraud Analyst"}
    ai_step = "ai_review"
    automated_path = None  # a person always decides

    def cases(self, sim: "_Simulation") -> list[SyntheticCase]:
        from app.modules.cards import service as cards
        from app.modules.ledger.models import Direction

        db = sim.db
        mix = normalized(sim.config.mix)
        currencies = _currencies(db)
        start = sim.clock.start
        window = int(sim.config.arrival_window_hours * 3600)
        out: list[SyntheticCase] = []
        for index in sim.case_indices:
            rng = case_random(sim.seed, index, "card-fraud")
            kind = _pick(rng, mix)
            home = rng.choice(sim.countries)
            currency = currencies[home]
            name, born = _person(rng, start.date())
            account = _customer_account(sim, name=name, born=born, country_code=home)
            account.opened_at = start - timedelta(days=400)
            cash = ledger.cash_account(db, currency)
            funds = _usd(8_000, currency)
            ledger.post_entry(
                db,
                idempotency_key=f"sim-{sim.run_id}-{account.id}-salary",
                currency=currency,
                description="Salary",
                source="simulation",
                lines=[
                    ledger.LineSpec(cash.id, Direction.DEBIT, funds),
                    ledger.LineSpec(account.ledger_account_id, Direction.CREDIT, funds),
                ],
                actor_id=None,
                effective_date=(start - timedelta(days=100)).date(),
            )
            card = cards.issue_card(
                db, account, "debit-standard", None, now=start - timedelta(days=365)
            )
            # The declined purchase happens before the case arrives; history before that.
            at = start - timedelta(minutes=rng.randint(5, 90))

            def buy(category: str, merchant: str, country: str, usd: float, when: datetime,
                    *, _card=card, _ccy=currency) -> Any:  # fmt: skip
                amount = max(_usd(round(usd, 2), _ccy), 1)
                return cards.authorize(db, _card, merchant_name=merchant,
                                       merchant_category=category, merchant_country=country,
                                       amount=amount, now=when)  # fmt: skip

            usual = []
            for n in range(rng.randint(10, 14)):
                category, merchant = rng.choice(HOME_MERCHANTS)
                usd = rng.uniform(15, 90)
                usual.append(usd)
                buy(
                    category,
                    merchant,
                    home,
                    usd,
                    at - timedelta(days=6 + n * 6, hours=rng.randint(0, 9)),
                )
            median = sorted(usual)[len(usual) // 2]
            abroad = [c for c in TRAVEL_COUNTRIES if c != home]
            elsewhere = [c for c in FRAUD_COUNTRIES if c != home]
            if kind in ("traveller", "big_spender_abroad"):
                country = rng.choice(abroad)
                for n in range(rng.randint(3, 5)):
                    category, merchant = rng.choice(TRIP_MERCHANTS)
                    hours = 50 + n * rng.randint(8, 20)
                    buy(
                        category,
                        merchant,
                        country,
                        rng.uniform(20, 150),
                        at - timedelta(hours=hours),
                    )
                usd = median * (
                    rng.uniform(1.5, 3.5) if kind == "traveller" else rng.uniform(6.5, 9)
                )
                final = buy("7995", "Grand Casino", country, min(usd, 700), at)
            elif kind == "crypto_investor":
                for n in range(3):
                    buy(
                        "6051",
                        "Coin Exchange",
                        home,
                        rng.uniform(80, 200),
                        at - timedelta(days=20 + 25 * n),
                    )
                for n in range(5):
                    buy(
                        "6051",
                        "Coin Exchange",
                        home,
                        rng.uniform(60, 110),
                        at - timedelta(minutes=50 - 10 * n),
                    )
                final = buy("6051", "Coin Exchange", home, rng.uniform(60, 110), at)
            elif kind == "stolen_abroad":
                category = rng.choice(("6051", "7995"))
                final = buy(
                    category,
                    "Online Vault",
                    rng.choice(elsewhere),
                    median * rng.uniform(2, 4),
                    at,
                )
            elif kind == "account_takeover":
                country = rng.choice(elsewhere)
                for n in range(5):
                    buy(
                        "5732",
                        "Gadget Outlet",
                        country,
                        rng.uniform(20, 55),
                        at - timedelta(minutes=50 - 10 * n),
                    )
                # At least half the daily limit: a large amount on top of the burst abroad.
                final = cards.authorize(
                    db, card, merchant_name="Gadget Outlet", merchant_category="5732",
                    merchant_country=country, now=at,
                    amount=int(card.daily_limit * rng.uniform(0.55, 0.65)),
                )  # fmt: skip
            else:  # card_testing: tiny test purchases, then a high-risk one at home
                for n in range(5):
                    buy(
                        "5815",
                        "Digital Store",
                        home,
                        rng.uniform(0.5, 2.0),
                        at - timedelta(minutes=30 - 5 * n),
                    )
                final = buy("6051", "Coin Exchange", home, median * rng.uniform(1.5, 3), at)
            if final.decline_reason != "fraud_suspected":
                raise RuntimeError(
                    f"{kind} case {index}: expected a fraud block, got {final.status} "
                    f"({final.decline_reason}, score {final.fraud_score})"
                )
            out.append(
                SyntheticCase(
                    index=index,
                    kind=kind,
                    expected_outcome="rejected" if kind in FRAUD_KINDS else "approved",
                    arrival_offset_seconds=rng.randint(0, window),
                    payload={
                        "customer_number": account.customer.customer_number,
                        "card_number": card.card_number,
                    },
                )
            )
        db.flush()
        return out

    def check_controls(self, db: Session, run_id: uuid.UUID) -> ControlCheck:
        """Every fraud review against four-eyes and authority, and every release only after
        an approval."""
        from app.modules.workflows.models import STEP_RUN_EXECUTION, WorkflowStepRun

        runs = db.execute(
            select(WorkflowStepRun, WorkflowExecution, User.role_id, User.username)
            .join(WorkflowExecution, STEP_RUN_EXECUTION)
            .outerjoin(User, User.id == WorkflowStepRun.actor_id)
            .where(
                _in_run(run_id),
                WorkflowStepRun.step_id.in_(["fraud_review", "release"]),
                WorkflowStepRun.status == "completed",
            )
        ).all()
        roles = _roles(db)
        approved: set[uuid.UUID] = set()
        decisions = []
        for step_run, execution, role_id, username in runs:
            if step_run.step_id == "fraud_review":
                decisions.append((step_run, execution, role_id, username))
                if (step_run.output or {}).get("approved"):
                    approved.add(execution.id)
        check = ControlCheck(decisions=len(decisions))
        for step_run, execution, role_id, username in decisions:
            if step_run.actor_id == execution.initiated_by:
                check.violations.append({"rule": "four_eyes", "decided_by": username})
            if Permission.CARDS_MANAGE not in roles.get(role_id, frozenset()):
                check.violations.append(
                    {"rule": "decider_without_authority", "decided_by": username}
                )
        for step_run, execution, _, _ in runs:
            if step_run.step_id == "release" and execution.id not in approved:
                check.violations.append(
                    {"rule": "release_without_approval", "execution_id": str(execution.id)}
                )
        return check


# --- Mortgage applications (WF-1009 v2, Phase 34) ------------------------------------------

# The largest bureau income estimate (US dollars a month) an applicant may have: with the
# shapes below, every kind's loan then stays within its product's maximum (checked in the
# tests), whatever the case's draws.
MORTGAGE_MAX_ESTIMATE_USD = 9_000
MORTGAGE_SHOULD_REJECT = frozenset({"stretched", "inflated_income", "thin_credit",
                                    "retirement_term"})  # fmt: skip
# kind: (loan-to-value, payment / declared income, declared / estimated income)
MORTGAGE_SHAPES = {
    "prime": ((0.50, 0.70), (0.12, 0.22), (0.85, 1.05)),
    "high_ltv_strong": ((0.86, 0.89), (0.15, 0.22), (0.85, 1.05)),
    "stretched": ((0.86, 0.89), (0.31, 0.34), (0.85, 1.05)),
    "inflated_income": ((0.60, 0.74), (0.28, 0.30), (1.35, 1.45)),
    "thin_credit": ((0.81, 0.88), (0.18, 0.24), (0.85, 1.05)),
    "retirement_term": ((0.50, 0.70), (0.12, 0.22), (0.85, 1.05)),
}


class MortgageApplications(Workload):
    """Mortgage applications through WF-1009 v2 that pass every lending rule, so an
    underwriter decides each one, with the AGB Mortgage Underwriting Assistant's advice in
    AI-assisted runs. Each case is a creditworthy customer buying a house a surveyor has
    valued at its price.

    Ground truth: prime borrowers and strong borrowers at a high loan-to-value are approved;
    a stretched borrower (a large payment on a high loan-to-value), income declared well
    above the bureau's estimate, a thin credit file at a high loan-to-value, and a term
    running far past retirement are declined."""

    key = "mortgage_applications"
    workflow_id = "WF-1009"
    kinds = frozenset(MORTGAGE_SHAPES)
    reviewer_roles = {"underwriting": "manager"}
    job_titles = {"teller": "Mortgage Adviser", "manager": "Mortgage Underwriter"}
    ai_step = "ai_review"
    automated_path = None  # an underwriter always decides

    def cases(self, sim: "_Simulation") -> list[SyntheticCase]:
        from app.modules.lending import service as lending
        from app.modules.mortgages import service as mortgages

        db = sim.db
        mix = normalized(sim.config.mix)
        today = sim.clock.start.date()
        window = int(sim.config.arrival_window_hours * 3600)
        surveyor = sim.population_staff()[1].id
        out: list[SyntheticCase] = []
        for index in sim.case_indices:
            rng = case_random(sim.seed, index, "mortgage")
            kind = _pick(rng, mix)
            country = rng.choice(sim.countries)
            ages = (56, 64) if kind == "retirement_term" else (25, 45)
            band = (620, 659) if kind == "thin_credit" else (700, 850)
            while True:  # a name the synthetic bureau scores in the kind's band
                name, born = _person(rng, today, *ages)
                report = lending.bureau_report(name, born)
                if (
                    band[0] <= report["score"] <= band[1]
                    and report["recent_defaults"] == 0
                    # Incomes small enough that every kind's loan fits its product.
                    and lending.income_estimate(name, born) <= MORTGAGE_MAX_ESTIMATE_USD
                ):
                    break
            account = _customer_account(sim, name=name, born=born, country_code=country)
            customer = account.customer
            ltv, share, ratio = (rng.uniform(*r) for r in MORTGAGE_SHAPES[kind])
            product = mortgages.get_product(db, "home-90" if ltv > 0.75 else "home-75")
            years = rng.randint(30, 35) if kind == "retirement_term" else rng.randint(20, 30)
            currency = account.currency
            declared = int(mortgages.monthly_income_estimate(customer, currency) * ratio)
            r = product.annual_rate_bps / 10_000 / 12
            loan = int(declared * share * (1 - (1 + r) ** -(years * 12)) / r)
            price = int(loan / ltv)
            prop = mortgages.register_property(db, customer, "house", price, None)
            mortgages.value_property(db, prop, "surveyor", value=price, actor_id=surveyor,
                                     today=today - timedelta(days=rng.randint(3, 40)))  # fmt: skip
            quote = mortgages.quote(
                db, customer=customer, prop=prop, product=product, account=account,
                loan_amount=loan, term_years=years, declared_monthly_income=declared,
                today=today,
            )  # fmt: skip
            if not quote["eligible"]:
                failed = [c["rule"] for c in quote["checks"] if not c["passed"]]
                raise RuntimeError(f"{kind} case {index} fails the lending rules: {failed}")
            out.append(
                SyntheticCase(
                    index=index,
                    kind=kind,
                    expected_outcome="rejected" if kind in MORTGAGE_SHOULD_REJECT else "approved",
                    arrival_offset_seconds=rng.randint(0, window),
                    payload={
                        "customer_number": customer.customer_number,
                        "property_number": prop.property_number,
                        "account_number": account.account_number,
                        "product_code": product.product_code,
                        "loan_amount": loan,
                        "term_years": years,
                        "declared_monthly_income": declared,
                    },
                )
            )
        db.flush()
        return out

    def check_controls(self, db: Session, run_id: uuid.UUID) -> ControlCheck:
        """Every underwriting decision against four-eyes and authority, and every offer
        issued only after an approval."""
        from app.modules.workflows.models import STEP_RUN_EXECUTION, WorkflowStepRun

        runs = db.execute(
            select(WorkflowStepRun, WorkflowExecution, User.role_id, User.username)
            .join(WorkflowExecution, STEP_RUN_EXECUTION)
            .outerjoin(User, User.id == WorkflowStepRun.actor_id)
            .where(
                _in_run(run_id),
                WorkflowStepRun.step_id.in_(["underwriting", "issue"]),
                WorkflowStepRun.status == "completed",
            )
        ).all()
        roles = _roles(db)
        approved: set[uuid.UUID] = set()
        decisions = []
        for step_run, execution, role_id, username in runs:
            if step_run.step_id == "underwriting":
                decisions.append((step_run, execution, role_id, username))
                if (step_run.output or {}).get("approved"):
                    approved.add(execution.id)
        check = ControlCheck(decisions=len(decisions))
        for step_run, execution, role_id, username in decisions:
            if step_run.actor_id == execution.initiated_by:
                check.violations.append({"rule": "four_eyes", "decided_by": username})
            if Permission.LOANS_APPROVE not in roles.get(role_id, frozenset()):
                check.violations.append(
                    {"rule": "decider_without_authority", "decided_by": username}
                )
        for step_run, execution, _, _ in runs:
            if step_run.step_id == "issue" and execution.id not in approved:
                check.violations.append(
                    {"rule": "offer_without_approval", "execution_id": str(execution.id)}
                )
        return check


def _verified_business(sim: "_Simulation", name: str, country_code: str) -> Account:
    """A verified business with an open business current account (Phases 36 and 38)."""
    db = sim.db
    country_id = db.execute(
        select(Country.id).where(Country.iso_country_code == country_code)
    ).scalar_one()
    business = create_customer(
        db,
        CustomerCreate(customer_type=CustomerType.BUSINESS, name=name,
                       date_of_birth_or_incorporation=date(2008, 5, 1),
                       country_id=country_id),
        actor_id=None,
        today=sim.clock.start.date(),
    )  # fmt: skip
    review_customer(db, business, CustomerReview(kyc_status=KycStatus.PENDING), None)
    review_customer(db, business, CustomerReview(kyc_status=KycStatus.VERIFIED,
                                                 risk_rating=RiskRating.LOW), None)  # fmt: skip
    teller, manager = sim.population_staff()
    request = submit_request(db, customer_id=business.id,
                             account_type=AccountType.BUSINESS_CURRENT, currency=None,
                             requested_by=teller.id)  # fmt: skip
    return approve_request(db, request.id, manager, "Existing customer (simulation "
                           "population)", now=sim.history_at)  # fmt: skip


# --- Covenant breaches (WF-1013 v2, Phase 36) ------------------------------------------------

COVENANT_SHOULD_KEEP = frozenset({"structural_decline", "over_leveraged", "repeat_breach",
                                  "stretched_facility"})  # fmt: skip
TRADES = ("Engineering", "Logistics", "Foods", "Textiles", "Print", "Joinery", "Plastics")


class CovenantBreaches(Workload):
    """Covenant breaches on commercial facilities through WF-1013 v2: businesses with a
    revolving facility and two years of covenant tests behind it submit this year's
    figures, which breach, so the credit committee decides whether to waive the breach or
    keep the facility frozen, with the AGB Covenant Breach Assistant's advice in AI-assisted
    runs.

    Ground truth: a one-off dip after strong years and a near miss are waived; EBITDA
    falling year after year, leverage far over its limit, a second breach a year after a
    waiver, and thin cover on a facility drawn to its limit keep the facility frozen."""

    key = "covenant_breaches"
    workflow_id = "WF-1013"
    kinds = frozenset({"one_off_dip", "seasonal_borderline"} | COVENANT_SHOULD_KEEP)
    reviewer_roles = {"committee_review": "executive"}
    job_titles = {"teller": "Relationship Manager", "manager": "Credit Approver",
                  "executive": "Credit Committee Member"}  # fmt: skip
    ai_step = "ai_review"
    automated_path = None  # the credit committee always decides

    def cases(self, sim: "_Simulation") -> list[SyntheticCase]:
        from app.modules.commercial import service as commercial

        db = sim.db
        mix = normalized(sim.config.mix)
        start = sim.clock.start
        window = int(sim.config.arrival_window_hours * 3600)
        teller, manager = sim.population_staff()
        current = date(start.year - 1, 12, 31)
        periods = [current.replace(year=current.year - 2), current.replace(year=current.year - 1)]
        out: list[SyntheticCase] = []
        for index in sim.case_indices:
            rng = case_random(sim.seed, index, "covenant")
            kind = _pick(rng, mix)
            country = rng.choice(sim.countries)
            name = f"{rng.choice(LAST_NAMES)} {rng.choice(TRADES)} Ltd"
            account = _verified_business(sim, name, country)
            currency = account.currency
            facility = commercial.propose_facility(
                db, customer=account.customer, account=account, facility_type="revolving",
                credit_limit=_usd(rng.randint(200, 900) * 1_000, currency), term_months=48,
                purpose="Working capital", requested_by=teller.id,
            )  # fmt: skip
            commercial.approve_facility(db, facility, manager.id, now=start - timedelta(days=200))
            use = rng.uniform(0.92, 0.98) if kind == "stretched_facility" else rng.uniform(0.2, 0.6)
            commercial.draw(db, facility, int(facility.credit_limit * use), teller.id,
                            now=start - timedelta(days=10))  # fmt: skip
            # Debt service cover (EBITDA / debt service) for the two earlier years and this
            # one; leverage (debt / EBITDA) likewise.
            u = rng.uniform
            if kind == "one_off_dip":
                d2 = u(1.8, 2.2)
                cover = [d2, max(d2 * u(0.97, 1.05), 1.35), u(1.05, 1.20)]
            elif kind == "seasonal_borderline":
                cover = [u(1.35, 1.55), u(1.35, 1.55), u(1.15, 1.24)]
            elif kind == "structural_decline":
                d2 = u(1.85, 2.0)
                d1 = d2 * u(0.72, 0.80)
                cover = [d2, d1, min(d1 * u(0.70, 0.80), 1.20)]
            elif kind == "over_leveraged":
                cover = [u(1.4, 1.8), u(1.4, 1.8), u(1.35, 1.8)]
            elif kind == "repeat_breach":
                d1 = u(1.13, 1.20)
                cover = [u(1.45, 1.6), d1, d1 * u(0.97, 1.03)]
            else:  # stretched_facility
                cover = [u(1.35, 1.5), u(1.35, 1.5), u(1.00, 1.08)]
            lever = [u(2.0, 3.0), u(2.0, 3.0),
                     u(4.6, 6.0) if kind == "over_leveraged" else u(2.0, 3.2)]  # fmt: skip
            service = _usd(rng.randint(150, 500) * 1_000, currency)
            figures = [(int(service * c), service, int(service * c * lev))
                       for c, lev in zip(cover, lever, strict=True)]  # fmt: skip
            for period, (ebitda, debt_service, debt) in zip(periods, figures, strict=False):
                test = commercial.run_covenant_test(
                    db, facility, period_end=period, ebitda=ebitda, debt_service=debt_service,
                    total_debt=debt, actor_id=teller.id,
                )  # fmt: skip
                if test.breached:  # only a repeat breach has one: the committee waived it
                    commercial.waive_breach(db, test, manager.id, now=start - timedelta(days=300))
            ebitda, debt_service, debt = figures[2]
            breached = ebitda * 100 < 125 * debt_service or debt * 100 > 350 * ebitda
            if facility.status != "active" or not breached:
                raise RuntimeError(f"{kind} case {index}: expected an active facility and a "
                                   "breach this year")  # fmt: skip
            out.append(
                SyntheticCase(
                    index=index,
                    kind=kind,
                    expected_outcome="rejected" if kind in COVENANT_SHOULD_KEEP else "approved",
                    arrival_offset_seconds=rng.randint(0, window),
                    payload={
                        "customer_number": account.customer.customer_number,
                        "facility_number": facility.facility_number,
                        "period_end": current.isoformat(),
                        "ebitda": ebitda,
                        "debt_service": debt_service,
                        "total_debt": debt,
                    },
                )
            )
        db.flush()
        return out

    def check_controls(self, db: Session, run_id: uuid.UUID) -> ControlCheck:
        """Every committee decision against four-eyes and authority, and every waiver only
        after an approval."""
        from app.modules.workflows.models import STEP_RUN_EXECUTION, WorkflowStepRun

        runs = db.execute(
            select(WorkflowStepRun, WorkflowExecution, User.role_id, User.username)
            .join(WorkflowExecution, STEP_RUN_EXECUTION)
            .outerjoin(User, User.id == WorkflowStepRun.actor_id)
            .where(
                _in_run(run_id),
                WorkflowStepRun.step_id.in_(["committee_review", "waive"]),
                WorkflowStepRun.status == "completed",
            )
        ).all()
        roles = _roles(db)
        approved: set[uuid.UUID] = set()
        decisions = []
        for step_run, execution, role_id, username in runs:
            if step_run.step_id == "committee_review":
                decisions.append((step_run, execution, role_id, username))
                if (step_run.output or {}).get("approved"):
                    approved.add(execution.id)
        check = ControlCheck(decisions=len(decisions))
        for step_run, execution, role_id, username in decisions:
            if step_run.actor_id == execution.initiated_by:
                check.violations.append({"rule": "four_eyes", "decided_by": username})
            if Permission.LOANS_APPROVE_LARGE not in roles.get(role_id, frozenset()):
                check.violations.append(
                    {"rule": "decider_without_authority", "decided_by": username}
                )
        for step_run, execution, _, _ in runs:
            if step_run.step_id == "waive" and execution.id not in approved:
                check.violations.append(
                    {"rule": "waiver_without_approval", "execution_id": str(execution.id)}
                )
        return check


# --- Discrepant presentations (WF-1016 v2, Phase 38) -----------------------------------------

PRESENTATION_SHOULD_REJECT = frozenset({"missing_document", "last_minute_shipment",
                                        "repeat_discrepancy", "stretched_applicant"})  # fmt: skip
GOODS = ("Coffee", "Cotton", "Machine Parts", "Ceramics", "Timber", "Rice", "Steel Coil")
DISCREPANCY_OF = {"late_presentation": "late_presentation", "wording_slip": "description_mismatch",
                  "missing_document": "missing_document", "last_minute_shipment": "late_shipment",
                  "stretched_applicant": "late_shipment"}  # fmt: skip


class DiscrepantPresentations(Workload):
    """Discrepant documents under letters of credit through WF-1016 v2: each business has an
    issued letter of credit, and the exporter presents documents with one discrepancy, so a
    trade officer decides whether to pay on the applicant's waiver, with the AGB Document
    Check Assistant's advice in AI-assisted runs.

    Ground truth: a late presentation or a wording slip is paid; a missing document, a late
    shipment presented in the last days of the credit, the same discrepancy presented again
    after the bank rejected it, and a late shipment the applicant can barely fund are
    rejected."""

    key = "discrepant_presentations"
    workflow_id = "WF-1016"
    kinds = frozenset({"late_presentation", "wording_slip"} | PRESENTATION_SHOULD_REJECT)
    reviewer_roles = {"applicant_waiver": "manager"}
    job_titles = {"teller": "Trade Documents Checker", "manager": "Trade Officer"}
    ai_step = "ai_review"
    automated_path = None  # a trade officer always decides

    def cases(self, sim: "_Simulation") -> list[SyntheticCase]:
        from app.modules.trade import service as trade

        db = sim.db
        mix = normalized(sim.config.mix)
        start = sim.clock.start
        today = start.date()
        window = int(sim.config.arrival_window_hours * 3600)
        teller, manager = sim.population_staff()
        out: list[SyntheticCase] = []
        for index in sim.case_indices:
            rng = case_random(sim.seed, index, "presentation")
            kind = _pick(rng, mix)
            name = f"{rng.choice(LAST_NAMES)} {rng.choice(TRADES)} Ltd"
            account = _verified_business(sim, name, rng.choice(sim.countries))
            currency = account.currency
            amount = _usd(rng.randint(50, 900) * 1_000, currency)
            requested_on = today - timedelta(days=60)
            expires = today + timedelta(
                days=rng.randint(1, 6) if kind == "last_minute_shipment" else rng.randint(60, 200)
            )
            share = rng.uniform(0.3, 0.7)
            draw = max(int(amount * share), 1)
            margin = amount * trade.MARGIN_BPS["letter_of_credit"] // 10_000
            if kind == "stretched_applicant":
                # After the margin is taken, funds (with the margin released on payment)
                # cover the payment 1.00-1.08 times.
                cover = rng.uniform(1.0, 1.08)
                funding = margin + int(draw * cover) - margin * draw // amount + 1
            else:
                funding = margin + 2 * amount
            key = f"sim-trade-{sim.run_id}-{index}"
            deposit(db, account.id, amount=funding, memo="Trading receipts (simulation)",
                    actor_id=teller.id, idempotency_key=key)  # fmt: skip
            instrument = trade.request_instrument(
                db, customer=account.customer, account=account, kind="letter_of_credit",
                beneficiary_name=f"{rng.choice(LAST_NAMES)} {rng.choice(GOODS)} Exports",
                beneficiary_country=rng.choice(("VN", "IN", "BR", "KE", "TR", "MX")),
                amount=amount, expires_on=expires, purpose=f"{rng.choice(GOODS)}, one shipment",
                requested_by=teller.id, today=requested_on,
            )  # fmt: skip
            trade.approve_instrument(db, instrument, manager.id, now=start - timedelta(days=59))
            if instrument.status != "issued":
                raise RuntimeError(f"{kind} case {index}: the letter of credit was not issued")
            if kind == "repeat_discrepancy":
                discrepancy = rng.choice(("late_presentation", "description_mismatch"))
                earlier = trade.receive_demand(
                    db, instrument, amount=draw, presented_on=today - timedelta(days=20),
                    discrepancies=[discrepancy], received_by=teller.id,
                )  # fmt: skip
                trade.reject_demand(db, earlier, manager.id, "Discrepancy not waived",
                                    now=start - timedelta(days=19))  # fmt: skip
            else:
                discrepancy = DISCREPANCY_OF[kind]
            out.append(
                SyntheticCase(
                    index=index,
                    kind=kind,
                    expected_outcome=(
                        "rejected" if kind in PRESENTATION_SHOULD_REJECT else "approved"
                    ),
                    arrival_offset_seconds=rng.randint(0, window),
                    payload={
                        "customer_number": account.customer.customer_number,
                        "instrument_number": instrument.instrument_number,
                        "amount": draw,
                        "discrepancy": discrepancy,
                    },
                )
            )
        db.flush()
        return out

    def check_controls(self, db: Session, run_id: uuid.UUID) -> ControlCheck:
        """Every waiver decision against four-eyes and authority, and every payment only
        after an approval."""
        from app.modules.workflows.models import STEP_RUN_EXECUTION, WorkflowStepRun

        runs = db.execute(
            select(WorkflowStepRun, WorkflowExecution, User.role_id, User.username)
            .join(WorkflowExecution, STEP_RUN_EXECUTION)
            .outerjoin(User, User.id == WorkflowStepRun.actor_id)
            .where(
                _in_run(run_id),
                WorkflowStepRun.step_id.in_(["applicant_waiver", "document_check", "pay",
                                             "pay_waived"]),
                WorkflowStepRun.status == "completed",
            )
        ).all()  # fmt: skip
        roles = _roles(db)
        approved: set[tuple[uuid.UUID, str]] = set()
        decisions = []
        for step_run, execution, role_id, username in runs:
            if step_run.step_id in ("applicant_waiver", "document_check"):
                decisions.append((step_run, execution, role_id, username))
                if (step_run.output or {}).get("approved"):
                    approved.add((execution.id, step_run.step_id))
        check = ControlCheck(decisions=len(decisions))
        for step_run, execution, role_id, username in decisions:
            if step_run.actor_id == execution.initiated_by:
                check.violations.append({"rule": "four_eyes", "decided_by": username})
            if Permission.TRADE_MANAGE not in roles.get(role_id, frozenset()):
                check.violations.append(
                    {"rule": "decider_without_authority", "decided_by": username}
                )
        needs = {"pay": "document_check", "pay_waived": "applicant_waiver"}
        for step_run, execution, _, _ in runs:
            if (
                step_run.step_id in needs
                and (execution.id, needs[step_run.step_id]) not in approved
            ):
                check.violations.append(
                    {"rule": "payment_without_approval", "execution_id": str(execution.id)}
                )
        return check


# --- Deal confirmations (WF-1018 v2, Phase 40) -----------------------------------------------

DEAL_SHOULD_CANCEL = frozenset({"off_market_rate", "weak_counterparty", "duplicate_booking",
                                "stretched_counterparty"})  # fmt: skip
DEAL_COUNTRY = {"USD": "US", "EUR": "DE", "GBP": "GB"}  # where the funding deposit is held


class DealConfirmations(Workload):
    """Interbank deals through WF-1018 v2: a dealer books a placement or a borrowing, and
    back office decides whether to confirm it, with the AGB Back-Office Check Assistant's
    advice in AI-assisted runs. Each case has its own synthetic counterparty, so cases do not
    share limits, and each placement is funded by a deposit, so cases do not share cash.

    Ground truth: deals on market terms are confirmed; an off-market rate against the bank, a
    long placement with a counterparty at the bottom of investment grade, a duplicate of a
    deal confirmed earlier the same day, and a long placement that uses almost all of a
    counterparty's limit are cancelled."""

    key = "deal_confirmations"
    workflow_id = "WF-1018"
    kinds = frozenset({"standard_placement", "standard_borrowing"} | DEAL_SHOULD_CANCEL)
    reviewer_roles = {"back_office": "manager"}
    job_titles = {"teller": "Treasury Dealer", "manager": "Back-Office Officer"}
    ai_step = "ai_review"
    automated_path = None  # back office always decides

    def cases(self, sim: "_Simulation") -> list[SyntheticCase]:
        from app.modules.treasury import service as treasury
        from app.modules.treasury.models import TreasuryCounterparty

        db = sim.db
        mix = normalized(sim.config.mix)
        start = sim.clock.start
        today = start.date()
        window = int(sim.config.arrival_window_hours * 3600)
        teller, manager = sim.population_staff()
        out: list[SyntheticCase] = []
        for index in sim.case_indices:
            rng = case_random(sim.seed, index, "deal")
            kind = _pick(rng, mix)
            currency = rng.choice(sorted(DEAL_COUNTRY))
            principal = treasury._from_usd(rng.randint(1, 20) * 1_000_000, currency)
            reference = treasury.reference_rate(currency)
            deal_kind = "borrowing" if kind == "standard_borrowing" else "placement"
            if kind == "off_market_rate":
                rate = reference - rng.randint(160, 300)  # lending far below the market
            else:
                rate = reference + rng.randint(-40, 40)
            if kind == "weak_counterparty":
                tenor, rating = rng.randint(181, 365), rng.choice(("BBB", "BBB-"))
            elif kind == "stretched_counterparty":
                tenor, rating = rng.randint(91, 150), rng.choice(("AA", "AA-", "A+", "A"))
            else:
                tenor, rating = rng.randint(7, 90), rng.choice(("AA", "AA-", "A+", "A"))
            # How much of the counterparty's limit this case's placements use.
            deals = 2 if kind == "duplicate_booking" else 1
            use = rng.uniform(0.90, 0.97) if kind == "stretched_counterparty" else rng.uniform(
                0.2, 0.6)  # fmt: skip
            value = treasury._usd(principal, currency, today, db)
            code = f"CP-S{sim.run_id.hex[:6].upper()}{index:05d}"
            counterparty = TreasuryCounterparty(
                code=code, name=f"Simulated {rng.choice(LAST_NAMES)} Bank",
                country_code=DEAL_COUNTRY[currency], rating=rating,
                limit_usd=int(value * deals / use) + 1,
            )  # fmt: skip
            db.add(counterparty)
            db.flush()
            if deal_kind == "placement":
                # Cash for the placement(s), held as a business deposit in the currency.
                account = _verified_business(sim, f"{rng.choice(LAST_NAMES)} Treasury Funding "
                                             "Ltd", DEAL_COUNTRY[currency])  # fmt: skip
                deposit(db, account.id, amount=principal * (deals + 1),
                        memo="Treasury funding (simulation)", actor_id=teller.id,
                        idempotency_key=f"sim-deal-{sim.run_id}-{index}")  # fmt: skip
            if kind == "duplicate_booking":
                # The same deal, booked and confirmed earlier the same day.
                first = treasury.book_deal(
                    db, counterparty=counterparty, kind=deal_kind, currency=currency,
                    principal=principal, rate_bps=rate, tenor_days=tenor,
                    booked_by=teller.id, today=today,
                )  # fmt: skip
                treasury.confirm_deal(db, first, manager.id, now=start - timedelta(hours=1))
            out.append(
                SyntheticCase(
                    index=index,
                    kind=kind,
                    expected_outcome="rejected" if kind in DEAL_SHOULD_CANCEL else "approved",
                    arrival_offset_seconds=rng.randint(0, window),
                    payload={
                        "counterparty_code": code,
                        "kind": deal_kind,
                        "currency": currency,
                        "principal": principal,
                        "rate_bps": rate,
                        "tenor_days": tenor,
                    },
                )  # fmt: skip
            )
        db.flush()
        return out

    def check_controls(self, db: Session, run_id: uuid.UUID) -> ControlCheck:
        """Every back-office decision against four-eyes and authority, and every settlement
        only after a confirmation."""
        from app.modules.workflows.models import STEP_RUN_EXECUTION, WorkflowStepRun

        runs = db.execute(
            select(WorkflowStepRun, WorkflowExecution, User.role_id, User.username)
            .join(WorkflowExecution, STEP_RUN_EXECUTION)
            .outerjoin(User, User.id == WorkflowStepRun.actor_id)
            .where(
                _in_run(run_id),
                WorkflowStepRun.step_id.in_(["back_office", "settle"]),
                WorkflowStepRun.status == "completed",
            )
        ).all()
        roles = _roles(db)
        approved: set[uuid.UUID] = set()
        decisions = []
        for step_run, execution, role_id, username in runs:
            if step_run.step_id == "back_office":
                decisions.append((step_run, execution, role_id, username))
                if (step_run.output or {}).get("approved"):
                    approved.add(execution.id)
        check = ControlCheck(decisions=len(decisions))
        for step_run, execution, role_id, username in decisions:
            if step_run.actor_id == execution.initiated_by:
                check.violations.append({"rule": "four_eyes", "decided_by": username})
            if Permission.TREASURY_CONFIRM not in roles.get(role_id, frozenset()):
                check.violations.append(
                    {"rule": "decider_without_authority", "decided_by": username}
                )
        for step_run, execution, _, _ in runs:
            if step_run.step_id == "settle" and execution.id not in approved:
                check.violations.append(
                    {"rule": "settlement_without_confirmation", "execution_id": str(execution.id)}
                )
        return check


# --- Recall triage (WF-1023 v2, Phase 42) ----------------------------------------------------

RECALL_SHOULD_WITHDRAW = frozenset({"claimed_duplicate_no_match", "fraud_on_known_payee",
                                    "serial_recaller", "stretched_tech"})  # fmt: skip
RECALL_REASON_OF = {"genuine_duplicate": "DUPL", "fraud_reported_fast": "FRAD",
                    "claimed_duplicate_no_match": "DUPL", "fraud_on_known_payee": "FRAD",
                    "serial_recaller": "CUST", "stretched_tech": "TECH"}  # fmt: skip


class RecallTriage(Workload):
    """Recalls of settled payments to other banks through WF-1023 v2: back office decides
    whether to send each recall to the beneficiary's bank, with the AGB Recall Assistant's
    advice in AI-assisted runs. Each case's payments, earlier payments and earlier recalls
    run through the real clearing service before the run.

    Ground truth: a genuine duplicate and a fraud reported within a day are sent; a claimed
    duplicate with no matching payment, a fraud claim against a beneficiary paid three or more
    times before, a customer with several earlier recalls (most refused) and a late technical
    recall of a high-value payment are withdrawn."""

    key = "recall_triage"
    workflow_id = "WF-1023"
    kinds = frozenset({"genuine_duplicate", "fraud_reported_fast"} | RECALL_SHOULD_WITHDRAW)
    reviewer_roles = {"approval": "manager"}
    job_titles = {"teller": "Payments Officer", "manager": "Payments Back Office"}
    ai_step = "ai_review"
    automated_path = None  # back office always decides

    def _settled_payment(self, sim: "_Simulation", rng, kind: str, today: date, teller,
                         manager):  # fmt: skip
        """One case's history and the settled payment its recall is about."""
        from app.modules.clearing import service as clearing

        db = sim.db
        # From the run's countries (PR #33 review).
        account = _verified_business(sim, f"{rng.choice(LAST_NAMES)} Trading Ltd",
                                     rng.choice(sim.countries))  # fmt: skip
        threshold, _ = payments.limits_for(db, account, today)
        key = f"sim-recall-{sim.run_id}-{account.id}"
        deposit(db, account.id, amount=threshold * 30, memo="Trading receipts (simulation)",
                actor_id=teller.id, idempotency_key=key)  # fmt: skip

        def beneficiary() -> tuple[str, str]:
            """A beneficiary: its bank and account (PR #33 review: both identify it)."""
            base = f"{rng.randint(10**11, 10**12 - 1)}"
            if base.endswith("00"):  # closed at the beneficiary's bank
                base = base[:-1] + "1"
            return rng.choice(sorted(clearing.BANKS)), clearing.account_number(base)

        def pay(amount: int, to: tuple[str, str], days_ago: int):
            on = today - timedelta(days=days_ago)
            payment = clearing.create_outgoing(
                db, debtor=account, beneficiary_name=f"{rng.choice(LAST_NAMES)} Supplies",
                beneficiary_bank=to[0], beneficiary_account=to[1], amount=amount,
                reference="Invoice", initiated_by=teller.id, today=on,
            )  # fmt: skip
            if payment.status == "awaiting_approval":
                clearing.approve_outgoing(db, payment, manager.id)
            # Only this payment: other pending payments are not the simulation's to clear
            # (PR #33 review).
            clearing.run_cycle(db, account.currency, None, today=on, only=[payment.id])
            return payment

        def small() -> int:
            return int(threshold * rng.uniform(0.05, 0.5))

        payee = beneficiary()
        if kind == "genuine_duplicate":
            days, amount = rng.randint(1, 6), small()
            pay(amount, payee, days)
            return pay(amount, payee, days)  # keyed twice the same day
        if kind == "fraud_reported_fast":
            for _ in range(rng.randint(0, 1)):
                pay(small(), payee, rng.randint(20, 80))
            return pay(small(), payee, rng.randint(0, 1))
        if kind == "claimed_duplicate_no_match":
            return pay(small(), payee, rng.randint(1, 6))
        if kind == "fraud_on_known_payee":
            for _ in range(rng.randint(3, 6)):
                pay(small(), payee, rng.randint(20, 80))
            return pay(small(), payee, rng.randint(0, 1))
        if kind == "serial_recaller":
            # Earlier recalls, all but one refused: answered after the five-day window.
            earlier = rng.randint(3, 5)
            for n in range(earlier):
                days_ago = rng.randint(15, 80)
                old = pay(small(), beneficiary(), days_ago)
                recall = clearing.request_recall(db, old, "CUST", teller.id)
                clearing.approve_recall(db, recall, manager.id)
                answered = today - timedelta(days=days_ago - (9 if n < earlier - 1 else 2))
                clearing.resolve_recall(db, recall, manager.id, today=answered)
            return pay(small(), payee, rng.randint(1, 2))
        # stretched_tech
        for _ in range(rng.randint(1, 3)):
            pay(small(), payee, rng.randint(20, 80))
        return pay(int(threshold * rng.uniform(1.5, 4)), payee, rng.randint(8, 9))

    def cases(self, sim: "_Simulation") -> list[SyntheticCase]:
        db = sim.db
        mix = normalized(sim.config.mix)
        today = sim.clock.start.date()
        window = int(sim.config.arrival_window_hours * 3600)
        teller, manager = sim.population_staff()
        out: list[SyntheticCase] = []
        for index in sim.case_indices:
            rng = case_random(sim.seed, index, "recall")
            kind = _pick(rng, mix)
            payment = self._settled_payment(sim, rng, kind, today, teller, manager)
            if payment.status != "settled":
                raise RuntimeError(f"{kind} case {index}: the payment did not settle")
            out.append(
                SyntheticCase(
                    index=index,
                    kind=kind,
                    expected_outcome=("rejected" if kind in RECALL_SHOULD_WITHDRAW else "approved"),
                    arrival_offset_seconds=rng.randint(0, window),
                    payload={
                        "payment_number": payment.payment_number,
                        "reason_code": RECALL_REASON_OF[kind],
                    },
                )  # fmt: skip
            )
        db.flush()
        return out

    def check_controls(self, db: Session, run_id: uuid.UUID) -> ControlCheck:
        """Every back-office decision against four-eyes and authority, and every recall sent
        to the beneficiary's bank only after an approval."""
        from app.modules.workflows.models import STEP_RUN_EXECUTION, WorkflowStepRun

        runs = db.execute(
            select(WorkflowStepRun, WorkflowExecution, User.role_id, User.username)
            .join(WorkflowExecution, STEP_RUN_EXECUTION)
            .outerjoin(User, User.id == WorkflowStepRun.actor_id)
            .where(
                _in_run(run_id),
                WorkflowStepRun.step_id.in_(["approval", "approve", "resolve"]),
                WorkflowStepRun.status == "completed",
            )
        ).all()
        roles = _roles(db)
        approved: set[uuid.UUID] = set()
        decisions = []
        for step_run, execution, role_id, username in runs:
            if step_run.step_id == "approval":
                decisions.append((step_run, execution, role_id, username))
                if (step_run.output or {}).get("approved"):
                    approved.add(execution.id)
        check = ControlCheck(decisions=len(decisions))
        for step_run, execution, role_id, username in decisions:
            if step_run.actor_id == execution.initiated_by:
                check.violations.append({"rule": "four_eyes", "decided_by": username})
            if Permission.PAYMENTS_APPROVE not in roles.get(role_id, frozenset()):
                check.violations.append(
                    {"rule": "decider_without_authority", "decided_by": username}
                )
        for step_run, execution, _, _ in runs:
            if step_run.step_id in ("approve", "resolve") and execution.id not in approved:
                check.violations.append(
                    {"rule": "recall_without_approval", "execution_id": str(execution.id)}
                )
        return check


# --- Order review (WF-1025 v2, Phase 44) -----------------------------------------------------

ORDER_SHOULD_REFUSE = frozenset({"large_gap", "complex_novice", "liquidity_drain",
                                 "serial_insister", "stretch_without_experience"})  # fmt: skip
# The customer's answers (objective, horizon, knowledge, capacity for loss) by kind.
ORDER_PROFILE_OF = {
    "experienced_small_step": ("balanced", 12, "informed", "high"),  # risk 4
    "serial_insister": ("balanced", 12, "informed", "high"),  # risk 4
    "safe_concentration": ("income", 8, "basic", "medium"),  # risk 3
    "large_gap": ("preservation", 6, "basic", "high"),  # risk 2
    "complex_novice": ("growth", 15, "basic", "high"),  # risk 6
    "liquidity_drain": ("balanced", 12, "informed", "high"),  # risk 4
    "stretch_without_experience": ("balanced", 12, "informed", "high"),  # risk 4
}


class OrderReview(Workload):
    """Unsuitable investment orders through WF-1025 v2: a manager decides whether each may go
    ahead at the client's insistence, with the AGB Suitability Review Assistant's advice in
    AI-assisted runs. Each customer's profile, portfolio and earlier orders run through the
    real wealth service before the run.

    Ground truth: a small step one level above an experienced customer's profile and a
    concentration in a low-risk bond go ahead; a security three or more levels above the
    profile, a complex product for a customer with basic knowledge, an order that leaves less
    than a tenth of the customer's assets in cash, a customer with several orders that went
    ahead against advice in the last 90 days, and a two-level step without experience are
    refused."""

    key = "order_review"
    workflow_id = "WF-1025"
    kinds = frozenset({"experienced_small_step", "safe_concentration"} | ORDER_SHOULD_REFUSE)
    reviewer_roles = {"approval": "manager"}
    job_titles = {"teller": "Investment Adviser", "manager": "Wealth Manager"}
    ai_step = "ai_review"
    automated_path = None  # a manager always decides

    def _order_case(self, sim: "_Simulation", rng, kind: str, today: date, teller,
                    manager) -> dict[str, Any]:  # fmt: skip
        """One customer's history, and the unsuitable order the case places."""
        from app.modules.customers.models import Customer
        from app.modules.wealth import service as wealth

        db = sim.db
        name, born = _person(rng, today, 30, 70)
        country = rng.choice(sim.countries)
        cash_usd = rng.randint(40, 400) * 1_000
        account = _customer_account(sim, name=name, born=born, country_code=country)
        currency = account.currency
        deposit(db, account.id, amount=_usd(cash_usd, currency),
                memo="Savings (simulation)", actor_id=teller.id,
                idempotency_key=f"sim-wealth-{sim.run_id}-{account.id}")  # fmt: skip
        customer = db.get(Customer, account.customer_id)
        objective, horizon, knowledge, loss = ORDER_PROFILE_OF[kind]
        assessed = today - timedelta(days=200)
        wealth.record_profile(db, customer, objective=objective, horizon_years=horizon,
                              knowledge=knowledge, loss_capacity=loss, assessed_by=teller.id,
                              today=assessed)  # fmt: skip
        portfolio = wealth.open_portfolio(db, account, teller.id)

        def units_for(code: str, share: float, on: date) -> tuple[Any, int]:
            """Units of the security worth about `share` of the customer's cash."""
            security = wealth.find_security(db, code)
            price = wealth.convert(db, wealth.price_on(security, on), security.currency,
                                   currency, on)  # fmt: skip
            target = int(wealth._cash_balance(db, account) * share)
            return security, max(1, target // max(price, 1))

        def insisted(code: str, share: float, days_ago: int, approve: bool = True) -> None:
            """An earlier unsuitable order, decided `days_ago` days before today."""
            on = today - timedelta(days=days_ago)
            security, units = units_for(code, share, on)
            order = wealth.place_order(db, portfolio=portfolio, security=security, side="buy",
                                       units=units, placed_by=teller.id, today=on)  # fmt: skip
            when = datetime.combine(on, datetime.min.time(), tzinfo=UTC) + timedelta(hours=11)
            if approve:
                wealth.approve_order(db, order, manager.id, "Insistent client", today=on,
                                     now=when)  # fmt: skip
            else:
                wealth.reject_order(db, order, manager.id, "Unsuitable", now=when)

        if kind == "experienced_small_step":
            insisted("AGB-GLOBAL-EQ", rng.uniform(0.03, 0.08), rng.randint(120, 190))
            code, share = "AGB-GLOBAL-EQ", rng.uniform(0.03, 0.08)
        elif kind == "serial_insister":
            insisted("AGB-GLOBAL-EQ", rng.uniform(0.03, 0.06), rng.randint(120, 190))
            for _ in range(rng.randint(3, 5)):
                insisted("AGB-GLOBAL-EQ", rng.uniform(0.02, 0.04), rng.randint(5, 85))
            if rng.random() < 0.5:
                insisted("AGB-EM-EQ", rng.uniform(0.02, 0.04), rng.randint(5, 85), approve=False)
            code, share = "AGB-GLOBAL-EQ", rng.uniform(0.03, 0.06)
        elif kind == "safe_concentration":
            code, share = "AGB-GOVT-2031", rng.uniform(0.5, 0.75)
        elif kind in ("large_gap", "stretch_without_experience"):
            code = rng.choice(("AGB-EM-EQ", "EQ-NORTHWIND", "EQ-HELIOS"))  # risk 6
            share = rng.uniform(0.03, 0.1)
        elif kind == "complex_novice":
            code, share = "SN-AUTOCALL-28", rng.uniform(0.03, 0.1)
        elif kind == "liquidity_drain":
            code, share = "AGB-GLOBAL-EQ", rng.uniform(0.92, 0.96)
        else:
            raise ValueError(kind)
        security, units = units_for(code, share, today)
        amount = wealth.convert(db, units * wealth.price_on(security, today), security.currency,
                                currency, today)  # fmt: skip
        if not wealth.suitability(db, portfolio, security, amount, today):
            raise RuntimeError(f"{kind}: the order would be suitable")
        return {"portfolio_number": portfolio.portfolio_number, "security_code": code,
                "side": "buy", "units": units}  # fmt: skip

    def cases(self, sim: "_Simulation") -> list[SyntheticCase]:
        from app.modules.wealth import service as wealth

        db = sim.db
        wealth.ensure_securities(db)
        mix = normalized(sim.config.mix)
        today = sim.clock.start.date()
        window = int(sim.config.arrival_window_hours * 3600)
        teller, manager = sim.population_staff()
        out: list[SyntheticCase] = []
        for index in sim.case_indices:
            rng = case_random(sim.seed, index, "order")
            kind = _pick(rng, mix)
            out.append(
                SyntheticCase(
                    index=index,
                    kind=kind,
                    expected_outcome="rejected" if kind in ORDER_SHOULD_REFUSE else "approved",
                    arrival_offset_seconds=rng.randint(0, window),
                    payload=self._order_case(sim, rng, kind, today, teller, manager),
                )
            )
        db.flush()
        return out

    def check_controls(self, db: Session, run_id: uuid.UUID) -> ControlCheck:
        """Every manager's decision against four-eyes and authority, and no order executed
        without an approval."""
        from app.modules.workflows.models import STEP_RUN_EXECUTION, WorkflowStepRun

        runs = db.execute(
            select(WorkflowStepRun, WorkflowExecution, User.role_id, User.username)
            .join(WorkflowExecution, STEP_RUN_EXECUTION)
            .outerjoin(User, User.id == WorkflowStepRun.actor_id)
            .where(
                _in_run(run_id),
                WorkflowStepRun.step_id.in_(["approval", "approve", "release"]),
                WorkflowStepRun.status == "completed",
            )
        ).all()
        roles = _roles(db)
        approved: set[uuid.UUID] = set()
        decisions = []
        for step_run, execution, role_id, username in runs:
            if step_run.step_id == "approval":
                decisions.append((step_run, execution, role_id, username))
                if (step_run.output or {}).get("approved"):
                    approved.add(execution.id)
        check = ControlCheck(decisions=len(decisions))
        for step_run, execution, role_id, username in decisions:
            if step_run.actor_id == execution.initiated_by:
                check.violations.append({"rule": "four_eyes", "decided_by": username})
            if Permission.WEALTH_APPROVE not in roles.get(role_id, frozenset()):
                check.violations.append(
                    {"rule": "decider_without_authority", "decided_by": username}
                )
        for step_run, execution, _, _ in runs:
            if step_run.step_id == "release" or (
                step_run.step_id == "approve" and execution.id not in approved
            ):
                check.violations.append(
                    {"rule": "order_without_approval", "execution_id": str(execution.id)}
                )
        return check


WORKLOADS: dict[str, Workload] = {
    w.key: w
    for w in (
        RetailOnboarding(),
        DomesticPayments(),
        PersonalLoans(),
        PersonalLoansWithIncomeCheck(),
        RetailOverdrafts(),
        CardFraudAlerts(),
        MortgageApplications(),
        CovenantBreaches(),
        DiscrepantPresentations(),
        DealConfirmations(),
        RecallTriage(),
        OrderReview(),
    )
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
