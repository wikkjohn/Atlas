"""Loan servicing: repayment schedules, interest accrual, collection, arrears, repayment,
payoff and write-off.

The lending business date moves forward only through servicing runs. A run for date D:

1. accrues the interest of every instalment that fell due on or before D (one balanced
   entry per instalment, dated its due date: interest receivable → interest income);
2. collects due instalments from the borrower's disbursement account, oldest first, while
   the balance covers a whole instalment (deposit → interest receivable + loan receivable);
3. leaves the rest due: the loan is then in arrears, measured in days past due (D minus the
   oldest unpaid due date) and reported in buckets.

Every posting has an idempotency key derived from the instalment, so a run repeated for the
same date posts nothing twice. Listeners (the collections workflow) are told about every
loan's arrears after it was serviced, repaid or paid off.

Simplifications, documented: interest accrues in full on each due date (no daily accrual
between due dates), a payoff settles outstanding principal plus interest already accrued
(no interest for the running period), partial instalments are not collected, and there
are no late fees.
"""

import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import (
    BusinessRuleViolation,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.permissions import Permission
from app.modules.accounts.models import Account, AccountStatus
from app.modules.identity.service import AuthenticatedUser
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, LedgerAccountType
from app.modules.lending.models import (
    InstalmentStatus,
    Loan,
    LoanInstalment,
    LoanServicingRun,
    LoanStatus,
)

INTEREST_RECEIVABLE_PREFIX = "1310"
INTEREST_INCOME_PREFIX = "4100"
LOAN_LOSS_PREFIX = "5100"
WRITE_OFF_DAYS = 90  # a loan may be written off at 90 days past due
COLLECTIONS_DAYS = 30  # the collections workflow opens a case at 30 days past due
BUCKETS = ((90, "90+"), (60, "60-89"), (30, "30-59"), (1, "1-29"))
_SERVICING_LOCK = 41_000_010  # pg advisory lock: one servicing run at a time


# --- Schedule ------------------------------------------------------------------------------


def add_months(start: date, months: int) -> date:
    """Same day of month `months` later; days past the 28th move to the 28th."""
    years, month = divmod(start.month - 1 + months, 12)
    return date(start.year + years, month + 1, min(start.day, 28))


def period_interest(balance: int, annual_rate_bps: int) -> int:
    """One month's interest on `balance` minor units, rounded half up."""
    exact = Decimal(balance) * Decimal(annual_rate_bps) / Decimal(120_000)
    return int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def build_schedule(
    principal: int, annual_rate_bps: int, term_months: int, payment: int, first_due: date
) -> list[tuple[int, date, int, int]]:
    """(number, due date, principal, interest) for each level instalment. The last
    instalment takes whatever principal remains, so the principals sum to the loan."""
    balance = principal
    rows = []
    for number in range(1, term_months + 1):
        interest = period_interest(balance, annual_rate_bps)
        part = balance if number == term_months else max(0, min(balance, payment - interest))
        balance -= part
        rows.append((number, add_months(first_due, number - 1), part, interest))
    return rows


def first_due_date(loan: Loan) -> date:
    return add_months(loan.disbursed_at.date(), 1)


def ensure_schedule(db: Session, loan: Loan) -> list[LoanInstalment]:
    """The loan's instalments, created on first use; and its interest receivable."""
    if loan.interest_receivable_account_id is None:
        loan.interest_receivable_account_id = ledger.ensure_ledger_account(
            db,
            code=f"{INTEREST_RECEIVABLE_PREFIX}-{loan.loan_number}",
            name=f"Interest receivable {loan.loan_number}",
            account_type=LedgerAccountType.ASSET,
            currency=loan.currency,
        ).id
    instalments = instalments_of(db, loan.id)
    if instalments:
        return instalments
    for number, due, part, interest in build_schedule(
        loan.principal,
        loan.annual_rate_bps,
        loan.term_months,
        loan.monthly_payment,
        first_due_date(loan),
    ):
        db.add(
            LoanInstalment(
                loan_id=loan.id,
                number=number,
                due_date=due,
                principal=part,
                interest=interest,
                status=InstalmentStatus.SCHEDULED.value,
            )
        )
    db.flush()
    return instalments_of(db, loan.id)


def instalments_of(db: Session, loan_id: uuid.UUID) -> list[LoanInstalment]:
    return list(
        db.execute(
            select(LoanInstalment)
            .where(LoanInstalment.loan_id == loan_id)
            .order_by(LoanInstalment.number)
        ).scalars()
    )


# --- Business date, arrears and listeners --------------------------------------------------


@dataclass(frozen=True)
class Arrears:
    days_past_due: int
    amount: int  # minor units due and unpaid
    instalments: int
    bucket: str
    oldest_due: date | None

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["oldest_due"] = self.oldest_due.isoformat() if self.oldest_due else None
        return out


def bucket_for(days_past_due: int) -> str:
    return next((name for days, name in BUCKETS if days_past_due >= days), "current")


def business_date(db: Session) -> date | None:
    """The latest date the loan book was serviced to (None before the first run)."""
    return db.execute(select(func.max(LoanServicingRun.as_of))).scalar_one()


def current_date(db: Session) -> date:
    """The date repayments and payoffs are booked on: the business date, or today if the
    book has not been serviced past today."""
    serviced = business_date(db)
    today = datetime.now(UTC).date()
    return max(serviced, today) if serviced else today


def arrears(db: Session, loan: Loan, on: date) -> Arrears:
    due = [i for i in instalments_of(db, loan.id) if i.status == InstalmentStatus.DUE.value]
    if not due:
        return Arrears(0, 0, 0, "current", None)
    oldest = min(i.due_date for i in due)
    days = max(0, (on - oldest).days)
    return Arrears(days, sum(i.amount for i in due), len(due), bucket_for(days), oldest)


# (db, loan, arrears, business date, actor) -> None. The collections workflow listens.
ArrearsListener = Callable[[Session, Loan, Arrears, date, AuthenticatedUser], None]
_LISTENERS: list[ArrearsListener] = []


def on_arrears_change(listener: ArrearsListener) -> ArrearsListener:
    _LISTENERS.append(listener)
    return listener


def _notify(db: Session, loan: Loan, on: date, actor: AuthenticatedUser) -> None:
    state = arrears(db, loan, on)
    for listener in _LISTENERS:
        listener(db, loan, state, on, actor)


# --- Postings ------------------------------------------------------------------------------


def _ensure(db: Session, prefix: str, name: str, kind: LedgerAccountType, currency: str):
    return ledger.ensure_ledger_account(
        db,
        code=f"{prefix}-{currency}",
        name=f"{name} ({currency})",
        account_type=kind,
        currency=currency,
    )


def _post(
    db: Session,
    loan: Loan,
    *,
    key: str,
    description: str,
    source: str,
    lines: list[tuple[uuid.UUID, Direction, int]],
    actor_id: uuid.UUID | None,
    on: date,
):
    """Post a balanced entry, leaving out zero-amount lines (e.g. a 0 % loan's interest)."""
    specs = [
        ledger.LineSpec(account_id, direction, amount, f"{loan.loan_number}")
        for account_id, direction, amount in lines
        if amount > 0
    ]
    entry, _ = ledger.post_entry(
        db,
        idempotency_key=key,
        currency=loan.currency,
        description=description,
        source=source,
        lines=specs,
        actor_id=actor_id,
        effective_date=on,
    )
    return entry


def _lock_loan(db: Session, loan_id: uuid.UUID) -> Loan:
    db.flush()
    loan = db.execute(
        select(Loan)
        .where(Loan.id == loan_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if loan is None:
        raise NotFoundError("Loan not found.")
    return loan


def _lock_account(db: Session, account_id: uuid.UUID) -> Account:
    return (
        db.execute(
            select(Account)
            .where(Account.id == account_id)
            .with_for_update(of=Account)
            .execution_options(populate_existing=True)
        )
        .unique()
        .scalar_one()
    )


def _available(db: Session, account: Account) -> int:
    if account.status != AccountStatus.OPEN:
        return 0
    return ledger.balance(db, ledger.get_ledger_account(db, account.ledger_account_id))


def _accrue(db: Session, loan: Loan, instalment: LoanInstalment, actor_id) -> None:
    income = _ensure(
        db,
        INTEREST_INCOME_PREFIX,
        "Interest income on loans",
        LedgerAccountType.INCOME,
        loan.currency,
    )
    if instalment.interest > 0:
        entry = _post(
            db,
            loan,
            key=f"loan-accrual:{instalment.id}",
            description=f"Interest accrued, {loan.loan_number} instalment {instalment.number}",
            source="loan_interest_accrual",
            lines=[
                (loan.interest_receivable_account_id, Direction.DEBIT, instalment.interest),
                (income.id, Direction.CREDIT, instalment.interest),
            ],
            actor_id=actor_id,
            on=instalment.due_date,
        )
        instalment.accrual_entry_id = entry.id
    else:
        # Nothing to accrue on a 0 % loan; record the due date with the disbursement entry
        # so the status/posting invariant still holds.
        instalment.accrual_entry_id = loan.disbursement_entry_id
    instalment.status = InstalmentStatus.DUE.value


def _settle(
    db: Session,
    loan: Loan,
    account: Account,
    instalments: list[LoanInstalment],
    *,
    key: str,
    description: str,
    source: str,
    actor_id,
    on: date,
    status: InstalmentStatus = InstalmentStatus.PAID,
):
    """Collect `instalments` from the account in one entry. Accrued interest is settled
    from the interest receivable; principal from the loan receivable."""
    interest = sum(i.interest for i in instalments if i.status == InstalmentStatus.DUE.value)
    principal = sum(i.principal for i in instalments)
    entry = _post(
        db,
        loan,
        key=key,
        description=description,
        source=source,
        lines=[
            (account.ledger_account_id, Direction.DEBIT, interest + principal),
            (loan.interest_receivable_account_id, Direction.CREDIT, interest),
            (loan.ledger_account_id, Direction.CREDIT, principal),
        ],
        actor_id=actor_id,
        on=on,
    )
    for instalment in instalments:
        instalment.status = (
            InstalmentStatus.PAID.value
            if instalment.status == InstalmentStatus.DUE.value
            else status.value
        )
        instalment.payment_entry_id = entry.id
        instalment.paid_on = on
    return entry


def _close_if_repaid(loan: Loan, instalments: list[LoanInstalment], on: date) -> bool:
    open_ = {InstalmentStatus.SCHEDULED.value, InstalmentStatus.DUE.value}
    if any(i.status in open_ for i in instalments):
        return False
    loan.status = LoanStatus.REPAID.value
    loan.closed_on = on
    loan.closed_at = datetime.now(UTC)
    return True


# --- Servicing runs -------------------------------------------------------------------------


def service_loan(db: Session, loan: Loan, as_of: date, actor: AuthenticatedUser) -> dict[str, int]:
    """Accrue and collect everything due on `loan` up to `as_of`."""
    instalments = ensure_schedule(db, loan)
    stats = {"accrued": 0, "collected": 0, "missed": 0}
    newly_due: set[uuid.UUID] = set()
    for instalment in instalments:
        if instalment.status == InstalmentStatus.SCHEDULED.value and instalment.due_date <= as_of:
            _accrue(db, loan, instalment, actor.id)
            newly_due.add(instalment.id)
            stats["accrued"] += 1
    account = _lock_account(db, loan.disbursement_account_id)
    for instalment in instalments:
        if instalment.status != InstalmentStatus.DUE.value:
            continue
        if _available(db, account) < instalment.amount:
            break  # oldest first: nothing later is collected before this one
        on = instalment.due_date if instalment.id in newly_due else as_of
        _settle(
            db,
            loan,
            account,
            [instalment],
            key=f"loan-collection:{instalment.id}",
            description=f"Instalment {instalment.number} of {loan.loan_number} collected",
            source="loan_collection",
            actor_id=actor.id,
            on=on,
        )
        stats["collected"] += 1
    # Instalments that fell due in this run and could not be collected.
    stats["missed"] = sum(
        1 for i in instalments if i.id in newly_due and i.status == InstalmentStatus.DUE.value
    )
    stats["repaid"] = int(_close_if_repaid(loan, instalments, as_of))
    db.flush()
    return stats


def run(db: Session, as_of: date, actor: AuthenticatedUser) -> LoanServicingRun:
    """Service the whole active loan book up to `as_of`."""
    if not actor.can(Permission.LOANS_SERVICE):
        raise PermissionDeniedError("Servicing runs need loans:service.")
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SERVICING_LOCK})
    last = business_date(db)
    if last is not None and as_of < last:
        raise BusinessRuleViolation(
            f"The loan book is already serviced to {last.isoformat()}; business dates never "
            "go backwards.",
            {"business_date": last.isoformat()},
        )
    loan_ids = list(
        db.execute(
            select(Loan.id).where(Loan.status == LoanStatus.ACTIVE).order_by(Loan.loan_number)
        ).scalars()
    )
    summary: dict[str, Any] = {
        "loans": 0,
        "accrued": 0,
        "collected": 0,
        "missed": 0,
        "repaid": 0,
        "in_arrears": 0,
        "arrears_amount": {},
        "buckets": {},
    }
    for loan_id in loan_ids:
        loan = _lock_loan(db, loan_id)
        if loan.disbursed_at.date() > as_of:
            continue
        summary["loans"] += 1
        for key, value in service_loan(db, loan, as_of, actor).items():
            summary[key] += value
        state = arrears(db, loan, as_of)
        if state.days_past_due > 0 or state.instalments:
            summary["in_arrears"] += 1
            summary["arrears_amount"][loan.currency] = (
                summary["arrears_amount"].get(loan.currency, 0) + state.amount
            )
        summary["buckets"][state.bucket] = summary["buckets"].get(state.bucket, 0) + 1
        for listener in _LISTENERS:
            listener(db, loan, state, as_of, actor)
    record = LoanServicingRun(as_of=as_of, started_by=actor.id, summary=summary)
    db.add(record)
    db.flush()
    db.refresh(record)
    record_audit_event(
        db,
        actor_id=actor.id,
        action="loan.servicing_run",
        entity_type="loan_servicing_run",
        entity_id=record.id,
        metadata={"as_of": as_of.isoformat(), **summary},
    )
    return record


# --- Customer actions -----------------------------------------------------------------------


def repay_arrears(
    db: Session,
    loan_id: uuid.UUID,
    actor: AuthenticatedUser,
    *,
    key: str,
    instalments: int | None = None,
) -> Loan:
    """Settle the oldest `instalments` overdue instalments (all of them by default) from the
    borrower's account."""
    loan = _lock_loan(db, loan_id)
    if loan.status != LoanStatus.ACTIVE:
        raise ConflictError(f"The loan is {loan.status}.")
    schedule = ensure_schedule(db, loan)
    due = [i for i in schedule if i.status == InstalmentStatus.DUE.value]
    if not due:
        raise ConflictError("The loan has no overdue instalments.")
    count = len(due) if instalments is None else instalments
    if not 1 <= count <= len(due):
        raise BusinessRuleViolation(
            f"Choose between 1 and {len(due)} overdue instalments.", {"overdue": len(due)}
        )
    chosen = due[:count]
    on = current_date(db)
    account = _lock_account(db, loan.disbursement_account_id)
    amount = sum(i.amount for i in chosen)
    if _available(db, account) < amount:
        raise BusinessRuleViolation(
            "Insufficient funds for the repayment.",
            {"rule": "insufficient_funds", "requested": amount},
        )
    _settle(
        db,
        loan,
        account,
        chosen,
        key=f"loan-repayment:{loan.id}:{key}",
        description=f"Arrears repayment on {loan.loan_number}",
        source="loan_repayment",
        actor_id=actor.id,
        on=on,
    )
    _close_if_repaid(loan, schedule, on)
    db.flush()
    _audit(db, actor, "loan.repayment", loan, {"instalments": count, "amount": amount})
    _notify(db, loan, on, actor)
    return loan


def payoff_amount(db: Session, loan: Loan) -> dict[str, int]:
    open_ = [
        i
        for i in ensure_schedule(db, loan)
        if i.status in (InstalmentStatus.SCHEDULED.value, InstalmentStatus.DUE.value)
    ]
    interest = sum(i.interest for i in open_ if i.status == InstalmentStatus.DUE.value)
    principal = sum(i.principal for i in open_)
    return {"principal": principal, "accrued_interest": interest, "total": principal + interest}


def payoff(db: Session, loan_id: uuid.UUID, actor: AuthenticatedUser, *, key: str) -> Loan:
    """Settle the loan early: outstanding principal plus interest already accrued."""
    loan = _lock_loan(db, loan_id)
    if loan.status != LoanStatus.ACTIVE:
        raise ConflictError(f"The loan is {loan.status}.")
    schedule = ensure_schedule(db, loan)
    open_ = [
        i
        for i in schedule
        if i.status in (InstalmentStatus.SCHEDULED.value, InstalmentStatus.DUE.value)
    ]
    quote = payoff_amount(db, loan)
    outstanding = ledger.balance(db, ledger.get_ledger_account(db, loan.ledger_account_id))
    if outstanding != quote["principal"]:
        raise ConflictError(  # the schedule and the books must agree before money moves
            "The loan's schedule does not match its receivable balance.",
            {"schedule": quote["principal"], "receivable": outstanding},
        )
    on = current_date(db)
    account = _lock_account(db, loan.disbursement_account_id)
    if _available(db, account) < quote["total"]:
        raise BusinessRuleViolation(
            "Insufficient funds to pay off the loan.",
            {"rule": "insufficient_funds", "requested": quote["total"]},
        )
    _settle(
        db,
        loan,
        account,
        open_,
        key=f"loan-payoff:{loan.id}:{key}",
        description=f"Early payoff of {loan.loan_number}",
        source="loan_payoff",
        actor_id=actor.id,
        on=on,
        status=InstalmentStatus.PREPAID,
    )
    _close_if_repaid(loan, schedule, on)
    db.flush()
    _audit(db, actor, "loan.payoff", loan, quote)
    _notify(db, loan, on, actor)
    return loan


def write_off(db: Session, loan_id: uuid.UUID, approver: AuthenticatedUser, on: date) -> Loan:
    """Write off a loan at least 90 days past due: the remaining principal and the accrued
    interest become a loan loss. Needs loans:approve_large (credit committee)."""
    if not approver.can(Permission.LOANS_APPROVE_LARGE):
        raise PermissionDeniedError(
            "Write-offs need loans:approve_large.", {"rule": "write_off_authority"}
        )
    loan = _lock_loan(db, loan_id)
    if loan.status != LoanStatus.ACTIVE:
        raise ConflictError(f"The loan is {loan.status}.")
    state = arrears(db, loan, on)
    if state.days_past_due < WRITE_OFF_DAYS:
        raise BusinessRuleViolation(
            f"Only loans {WRITE_OFF_DAYS} or more days past due can be written off.",
            {"rule": "write_off_too_early", "days_past_due": state.days_past_due},
        )
    schedule = ensure_schedule(db, loan)
    open_ = [
        i
        for i in schedule
        if i.status in (InstalmentStatus.SCHEDULED.value, InstalmentStatus.DUE.value)
    ]
    interest = sum(i.interest for i in open_ if i.status == InstalmentStatus.DUE.value)
    principal = sum(i.principal for i in open_)
    losses = _ensure(db, LOAN_LOSS_PREFIX, "Loan losses", LedgerAccountType.EXPENSE, loan.currency)
    entry = _post(
        db,
        loan,
        key=f"loan-write-off:{loan.id}",
        description=f"Write-off of {loan.loan_number}",
        source="loan_write_off",
        lines=[
            (losses.id, Direction.DEBIT, principal + interest),
            (loan.interest_receivable_account_id, Direction.CREDIT, interest),
            (loan.ledger_account_id, Direction.CREDIT, principal),
        ],
        actor_id=approver.id,
        on=on,
    )
    for instalment in open_:
        instalment.status = InstalmentStatus.WRITTEN_OFF.value
    loan.status = LoanStatus.WRITTEN_OFF.value
    loan.written_off_by = approver.id
    loan.write_off_entry_id = entry.id
    loan.closed_on = on
    loan.closed_at = datetime.now(UTC)
    db.flush()
    _audit(
        db,
        approver,
        "loan.written_off",
        loan,
        {"principal": principal, "interest": interest, "days_past_due": state.days_past_due},
    )
    return loan


def _audit(db: Session, actor: AuthenticatedUser, action: str, loan: Loan, data: dict) -> None:
    record_audit_event(
        db,
        actor_id=actor.id,
        action=action,
        entity_type="loan",
        entity_id=loan.id,
        metadata={"loan_number": loan.loan_number, **data},
    )
