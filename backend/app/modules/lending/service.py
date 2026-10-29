"""Lending service: loan pricing, affordability and origination.

`originate` is the only way a loan comes into existence. It re-applies every control,
whoever calls it: the customer is KYC-verified, the disbursement account is theirs, open
and in their currency, the underwriter holds `loans:approve` (or, for a loan within the
automation limit and below the committee limit, the policy engine's
`loans:approve_low_risk`) and did not apply, and a loan
above the credit-committee limit also has an approval by a third person holding
`loans:approve_large`. The principal is then posted from the loan receivable to the
customer's account in one balanced ledger entry.

The credit bureau is synthetic: a deterministic score derived from the applicant's name
and date of birth, so the same synthetic person always has the same history.
"""

import hashlib
import math
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, NotFoundError, PermissionDeniedError
from app.core.money import minor_unit_exponent, to_minor_units
from app.core.pagination import PageParams, paginate
from app.core.permissions import Permission
from app.modules.accounts.models import Account, AccountStatus
from app.modules.customers.models import Customer, KycStatus
from app.modules.identity.models import User
from app.modules.identity.service import AuthenticatedUser
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, LedgerAccountType
from app.modules.lending import servicing
from app.modules.lending.models import (
    LOAN_NUMBER_SEQUENCE,
    InstalmentStatus,
    Loan,
    LoanInstalment,
    LoanStatus,
)
from app.modules.lending.schemas import LoanOut

LOANS_RECEIVABLE_PREFIX = "1300"
MIN_PRINCIPAL_MAJOR = 1_000
MAX_PRINCIPAL_MAJOR = 50_000
COMMITTEE_LIMIT_MAJOR = 25_000  # above this, the credit committee must also approve
AUTOMATION_LIMIT_MAJOR = 15_000  # the policy engine may underwrite up to this
MIN_TERM, MAX_TERM = 6, 84
# Product pricing by bureau score band: (minimum score, annual rate in basis points).
PRICING = ((760, 690), (700, 890), (640, 1190), (580, 1590))
MIN_SCORE = 580  # below this the product is not offered
MAX_DEBT_TO_INCOME = 0.45  # including the new loan's payment


# --- Synthetic credit bureau --------------------------------------------------------------


def bureau_report(name: str, date_of_birth: date) -> dict:
    """A synthetic bureau file: same person, same report. Not a real credit check."""
    key = f"{' '.join(name.casefold().split())}|{date_of_birth.isoformat()}"
    digest = hashlib.sha256(key.encode()).digest()
    score = 300 + int.from_bytes(digest[:2], "big") % 551  # 300..850
    defaults = 0 if score >= 640 else 1 + digest[2] % 2 if score < 560 else digest[2] % 2
    return {
        "bureau": "atlas-synthetic-bureau-v1",
        "score": score,
        "recent_defaults": defaults,
        "open_credit_lines": digest[3] % 6,
    }


def income_estimate(name: str, date_of_birth: date) -> int:
    """The synthetic bureau's estimate of the applicant's gross monthly income, in major
    units (2,500 to 12,000). Like real income estimators it is a model, not a payslip:
    self-employed and irregular earners can legitimately declare more."""
    key = f"income|{' '.join(name.casefold().split())}|{date_of_birth.isoformat()}"
    digest = hashlib.sha256(key.encode()).digest()
    return 2_500 + int.from_bytes(digest[:2], "big") % 9_501


# --- Pricing and affordability ------------------------------------------------------------


def rate_for(score: int) -> int | None:
    for minimum, rate in PRICING:
        if score >= minimum:
            return rate
    return None


def monthly_payment(principal: int, annual_rate_bps: int, term_months: int) -> int:
    """Level monthly instalment in minor units, rounded up."""
    if annual_rate_bps == 0:
        return math.ceil(principal / term_months)
    r = annual_rate_bps / 10_000 / 12
    return math.ceil(principal * r / (1 - (1 + r) ** -term_months))


def principal_limits(currency: str) -> tuple[int, int]:
    return to_minor_units(MIN_PRINCIPAL_MAJOR, currency), to_minor_units(
        MAX_PRINCIPAL_MAJOR, currency
    )


def needs_committee(principal: int, currency: str) -> bool:
    return principal > to_minor_units(COMMITTEE_LIMIT_MAJOR, currency)


def within_automation_limit(principal: int, currency: str) -> bool:
    """Small enough for the policy engine to underwrite (never a committee loan)."""
    return principal <= to_minor_units(AUTOMATION_LIMIT_MAJOR, currency) and not needs_committee(
        principal, currency
    )


def debt_to_income(
    monthly_income: int, existing_monthly_debt: int, new_payment: int
) -> float | None:
    if monthly_income <= 0:
        return None
    return (existing_monthly_debt + new_payment) / monthly_income


def format_amount(amount: int, currency: str) -> str:
    exponent = minor_unit_exponent(currency)
    return f"{amount / 10**exponent:,.{exponent}f} {currency}"


# --- Origination ---------------------------------------------------------------------------


def _check_deciders(
    principal: int,
    currency: str,
    requested_by: uuid.UUID,
    underwriter: AuthenticatedUser,
    committee: AuthenticatedUser | None,
) -> None:
    if underwriter.id == requested_by:
        raise PermissionDeniedError(
            "Four-eyes rule: the person who applied cannot underwrite the loan.",
            {"rule": "four_eyes"},
        )
    if not underwriter.can(Permission.LOANS_APPROVE):
        if not (
            underwriter.can(Permission.LOANS_APPROVE_LOW_RISK)
            and within_automation_limit(principal, currency)
        ):
            raise PermissionDeniedError(
                "The underwriter lacks loans:approve.", {"rule": "underwriter_without_authority"}
            )
    if needs_committee(principal, currency):
        if committee is None:
            raise PermissionDeniedError(
                "Loans above the committee limit need a credit committee approval.",
                {"rule": "committee_required"},
            )
        if committee.id in (requested_by, underwriter.id):
            raise PermissionDeniedError(
                "Four-eyes rule: the committee approver must be a third person.",
                {"rule": "committee_four_eyes"},
            )
        if not committee.can(Permission.LOANS_APPROVE_LARGE):
            raise PermissionDeniedError(
                "The committee approver lacks loans:approve_large.",
                {"rule": "committee_without_authority"},
            )


def originate(
    db: Session,
    *,
    customer_id: uuid.UUID,
    account_id: uuid.UUID,
    principal: int,
    annual_rate_bps: int,
    term_months: int,
    purpose: str,
    requested_by: uuid.UUID,
    underwriter: AuthenticatedUser,
    committee: AuthenticatedUser | None,
    workflow_execution_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> Loan:
    now = now or datetime.now(UTC)
    db.flush()
    account = (
        db.execute(
            select(Account)
            .where(Account.id == account_id)
            .with_for_update(of=Account)
            .execution_options(populate_existing=True)
        )
        .unique()
        .scalar_one_or_none()
    )
    customer = (
        db.execute(
            select(Customer)
            .where(Customer.id == customer_id)
            .with_for_update(of=Customer)
            .execution_options(populate_existing=True)
        )
        .unique()
        .scalar_one_or_none()
    )
    if account is None or customer is None:
        raise NotFoundError("Customer or account not found.")
    if customer.kyc_status != KycStatus.VERIFIED:
        raise BusinessRuleViolation(
            "Loans are only made to KYC-verified customers.", {"rule": "kyc_not_verified"}
        )
    if account.customer_id != customer.id:
        raise BusinessRuleViolation(
            "The disbursement account belongs to someone else.", {"rule": "account_owner"}
        )
    if account.status != AccountStatus.OPEN:
        raise BusinessRuleViolation(
            f"The disbursement account is {account.status}.", {"rule": "account_not_open"}
        )
    low, high = principal_limits(account.currency)
    if not low <= principal <= high:
        raise BusinessRuleViolation(
            "The principal is outside the product limits.",
            {"rule": "principal_limits", "min": low, "max": high},
        )
    if not MIN_TERM <= term_months <= MAX_TERM:
        raise BusinessRuleViolation("The term is outside the product limits.")
    _check_deciders(principal, account.currency, requested_by, underwriter, committee)

    number = db.execute(LOAN_NUMBER_SEQUENCE.next_value()).scalar_one()
    loan_number = f"LN-{number:08d}"
    receivable = ledger.ensure_ledger_account(
        db,
        code=f"{LOANS_RECEIVABLE_PREFIX}-{loan_number}",
        name=f"Loan receivable {loan_number}",
        account_type=LedgerAccountType.ASSET,
        currency=account.currency,
    )
    memo = f"Disbursement of {loan_number}"
    entry, _ = ledger.post_entry(
        db,
        idempotency_key=f"loan-disbursement:{loan_number}",
        currency=account.currency,
        description=f"Loan {loan_number} disbursed to {account.account_number}",
        source="loan_disbursement",
        lines=[
            ledger.LineSpec(receivable.id, Direction.DEBIT, principal, memo),
            ledger.LineSpec(account.ledger_account_id, Direction.CREDIT, principal, memo),
        ],
        actor_id=underwriter.id,
        effective_date=now.date(),
    )
    loan = Loan(
        loan_number=loan_number,
        customer_id=customer.id,
        disbursement_account_id=account.id,
        ledger_account_id=receivable.id,
        principal=principal,
        currency=account.currency,
        annual_rate_bps=annual_rate_bps,
        term_months=term_months,
        monthly_payment=monthly_payment(principal, annual_rate_bps, term_months),
        purpose=purpose,
        status=LoanStatus.ACTIVE.value,
        requested_by=requested_by,
        underwritten_by=underwriter.id,
        committee_approved_by=committee.id if committee else None,
        disbursement_entry_id=entry.id,
        workflow_execution_id=workflow_execution_id,
        disbursed_at=now,
    )
    db.add(loan)
    db.flush()
    servicing.ensure_schedule(db, loan)  # the repayment schedule exists from day one
    record_audit_event(
        db,
        actor_id=underwriter.id,
        action="loan.originated",
        entity_type="loan",
        entity_id=loan.id,
        metadata={
            "loan_number": loan_number,
            "principal": principal,
            "currency": account.currency,
            "committee": str(committee.id) if committee else None,
        },
    )
    return loan


# --- Reading -------------------------------------------------------------------------------


def get_loan(db: Session, loan_id: uuid.UUID) -> Loan:
    loan = db.get(Loan, loan_id)
    if loan is None:
        raise NotFoundError("Loan not found.")
    return loan


def list_loans(
    db: Session,
    params: PageParams,
    *,
    customer_id: uuid.UUID | None = None,
    status: str | None = None,
    q: str | None = None,
) -> tuple[list[Loan], int]:
    query = select(Loan).order_by(Loan.disbursed_at.desc(), Loan.loan_number.desc())
    if customer_id:
        query = query.where(Loan.customer_id == customer_id)
    if status:
        query = query.where(Loan.status == status)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.join(Customer, Customer.id == Loan.customer_id).where(
            Loan.loan_number.ilike(pattern) | Customer.name.ilike(pattern)
        )
    return paginate(db, query, params)


def loans_out(db: Session, loans: list[Loan]) -> list[LoanOut]:
    if not loans:
        return []
    customers = {
        c.id: c
        for c in db.execute(
            select(Customer).where(Customer.id.in_({loan.customer_id for loan in loans}))
        )
        .unique()
        .scalars()
    }
    numbers = dict(
        db.execute(
            select(Account.id, Account.account_number).where(
                Account.id.in_({loan.disbursement_account_id for loan in loans})
            )
        ).all()
    )
    receivables = [ledger.get_ledger_account(db, loan.ledger_account_id) for loan in loans]
    outstanding = ledger.balances(db, receivables)
    user_ids = {
        u
        for loan in loans
        for u in (loan.requested_by, loan.underwritten_by, loan.committee_approved_by)
        if u
    }
    user_ids |= {loan.written_off_by for loan in loans if loan.written_off_by}
    names = dict(db.execute(select(User.id, User.username).where(User.id.in_(user_ids))).all())
    on = servicing.business_date(db) or datetime.now(UTC).date()
    schedules: dict[uuid.UUID, list[LoanInstalment]] = {loan.id: [] for loan in loans}
    for instalment in db.execute(
        select(LoanInstalment)
        .where(LoanInstalment.loan_id.in_(schedules))
        .order_by(LoanInstalment.number)
    ).scalars():
        schedules[instalment.loan_id].append(instalment)

    def servicing_view(loan: Loan) -> dict:
        rows = schedules[loan.id]
        due = [i for i in rows if i.status == InstalmentStatus.DUE.value]
        upcoming = next((i for i in rows if i.status == InstalmentStatus.SCHEDULED.value), None)
        days = max(0, (on - min(i.due_date for i in due)).days) if due else 0
        return {
            "instalments_paid": sum(
                i.status in (InstalmentStatus.PAID.value, InstalmentStatus.PREPAID.value)
                for i in rows
            ),
            "instalments_total": len(rows),
            "next_due_date": upcoming.due_date if upcoming else None,
            "next_due_amount": upcoming.amount if upcoming else None,
            "days_past_due": days,
            "arrears_amount": sum(i.amount for i in due),
            "arrears_bucket": servicing.bucket_for(days) if due else "current",
            "closed_on": loan.closed_on,
            "written_off_by_username": names.get(loan.written_off_by)
            if loan.written_off_by
            else None,
        }

    return [
        LoanOut(
            id=loan.id,
            loan_number=loan.loan_number,
            customer_id=loan.customer_id,
            customer_number=customers[loan.customer_id].customer_number,
            customer_name=customers[loan.customer_id].name,
            disbursement_account_number=numbers[loan.disbursement_account_id],
            principal=loan.principal,
            currency=loan.currency,
            annual_rate_bps=loan.annual_rate_bps,
            term_months=loan.term_months,
            monthly_payment=loan.monthly_payment,
            purpose=loan.purpose,
            status=loan.status,
            outstanding=outstanding[loan.ledger_account_id],
            requested_by_username=names.get(loan.requested_by),
            underwritten_by_username=names.get(loan.underwritten_by),
            committee_approved_by_username=names.get(loan.committee_approved_by)
            if loan.committee_approved_by
            else None,
            workflow_execution_id=loan.workflow_execution_id,
            disbursed_at=loan.disbursed_at,
            **servicing_view(loan),
        )
        for loan in loans
    ]
