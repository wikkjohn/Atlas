"""Payment service: the only code that moves money between customer accounts.

`release` re-applies every control under row locks, whoever calls it — the payment
workflow, a test or a future API: both accounts open and in the payment's currency, enough
funds, and for a high-value payment an approval by someone else holding
`payments:approve`. Below the high-value limit a held payment may also be cleared by a
fraud reviewer (`payments:review`) or the policy engine (`payments:release_low_risk`).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased

from app.core.audit import record_audit_event
from app.core.errors import (
    BusinessRuleViolation,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.money import to_minor_units
from app.core.pagination import PageParams, paginate
from app.core.permissions import Permission
from app.modules.accounts.models import Account, AccountStatus
from app.modules.customers.models import Customer
from app.modules.identity.models import User
from app.modules.identity.service import AuthenticatedUser
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction
from app.modules.payments.models import PAYMENT_NUMBER_SEQUENCE, Payment, PaymentStatus
from app.modules.payments.schemas import PaymentOut

HIGH_VALUE_MAJOR = 10_000  # whole units of the payment's currency
MAX_PAYMENT_MAJOR = 1_000_000


def high_value_threshold(currency: str) -> int:
    return to_minor_units(HIGH_VALUE_MAJOR, currency)


def max_amount(currency: str) -> int:
    return to_minor_units(MAX_PAYMENT_MAJOR, currency)


def is_high_value(amount: int, currency: str) -> bool:
    return amount >= high_value_threshold(currency)


def create_payment(
    db: Session,
    *,
    debtor: Account,
    creditor: Account,
    amount: int,
    reference: str,
    initiated_by: uuid.UUID,
    workflow_execution_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> Payment:
    if debtor.id == creditor.id:
        raise BusinessRuleViolation("A payment needs two different accounts.")
    if amount <= 0 or amount > max_amount(debtor.currency):
        raise BusinessRuleViolation(
            "The amount is outside the payment limits.",
            {"amount": amount, "max": max_amount(debtor.currency)},
        )
    number = db.execute(PAYMENT_NUMBER_SEQUENCE.next_value()).scalar_one()
    payment = Payment(
        payment_number=f"PAY-{number:08d}",
        debtor_account_id=debtor.id,
        creditor_account_id=creditor.id,
        amount=amount,
        currency=debtor.currency,
        reference=reference,
        status=PaymentStatus.PENDING.value,
        initiated_by=initiated_by,
        workflow_execution_id=workflow_execution_id,
        created_at=now or datetime.now(UTC),  # simulated time in simulations
    )
    db.add(payment)
    db.flush()
    record_audit_event(
        db,
        actor_id=initiated_by,
        action="payment.created",
        entity_type="payment",
        entity_id=payment.id,
        metadata={"payment_number": payment.payment_number, "amount": amount},
    )
    return payment


def get_payment(db: Session, payment_id: uuid.UUID, *, for_update: bool = False) -> Payment:
    query = select(Payment).where(Payment.id == payment_id)
    if for_update:
        db.flush()
        query = query.with_for_update().execution_options(populate_existing=True)
    payment = db.execute(query).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("Payment not found.")
    return payment


def _lock_accounts(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, Account]:
    # Always in id order, so two payments between the same accounts cannot deadlock.
    db.flush()
    rows = (
        db.execute(
            select(Account)
            .where(Account.id.in_(ids))
            .order_by(Account.id)
            .with_for_update(of=Account)
            .execution_options(populate_existing=True)
        )
        .unique()
        .scalars()
    )
    return {a.id: a for a in rows}


def check_approver(payment: Payment, approver: AuthenticatedUser | None) -> None:
    """Raise unless `approver` may release this payment (None: straight-through)."""
    high_value = is_high_value(payment.amount, payment.currency)
    if approver is None:
        if high_value:
            raise PermissionDeniedError(
                "High-value payments need an approval by someone else.",
                {"rule": "high_value_requires_approval"},
            )
        return
    if approver.id == payment.initiated_by:
        raise PermissionDeniedError(
            "Four-eyes rule: the person who started the payment cannot approve it.",
            {"rule": "four_eyes"},
        )
    if approver.can(Permission.PAYMENTS_APPROVE):
        return
    limited = (Permission.PAYMENTS_REVIEW, Permission.PAYMENTS_RELEASE_LOW_RISK)
    if not high_value and any(approver.can(p) for p in limited):
        return
    raise PermissionDeniedError(
        "This principal may not approve this payment.",
        {"rule": "high_value_requires_approval" if high_value else "approver_without_authority"},
    )


def release(
    db: Session,
    payment_id: uuid.UUID,
    *,
    approver: AuthenticatedUser | None,
    now: datetime | None = None,
) -> Payment:
    """Post the payment to the ledger after re-checking every control."""
    now = now or datetime.now(UTC)
    payment = get_payment(db, payment_id, for_update=True)
    if payment.status != PaymentStatus.PENDING:
        raise ConflictError(f"The payment is {payment.status}.")
    check_approver(payment, approver)
    accounts = _lock_accounts(db, [payment.debtor_account_id, payment.creditor_account_id])
    debtor = accounts[payment.debtor_account_id]
    creditor = accounts[payment.creditor_account_id]
    for role, account in (("debtor", debtor), ("creditor", creditor)):
        if account.status != AccountStatus.OPEN:
            raise BusinessRuleViolation(
                f"The {role} account is {account.status}.", {"rule": f"{role}_not_open"}
            )
        if account.currency != payment.currency:
            raise BusinessRuleViolation(
                f"The {role} account is not in {payment.currency}.", {"rule": "currency"}
            )
    available = ledger.balance(db, ledger.get_ledger_account(db, debtor.ledger_account_id))
    if payment.amount > available:
        raise BusinessRuleViolation(
            "Insufficient funds.",
            {"rule": "insufficient_funds", "available": available, "requested": payment.amount},
        )
    memo = f"{payment.payment_number} {payment.reference}"[:200]
    entry, _ = ledger.post_entry(
        db,
        idempotency_key=f"payment:{payment.id}",
        currency=payment.currency,
        description=f"Payment {payment.payment_number} {debtor.account_number} to "
        f"{creditor.account_number}",
        source="payment",
        lines=[
            ledger.LineSpec(debtor.ledger_account_id, Direction.DEBIT, payment.amount, memo),
            ledger.LineSpec(creditor.ledger_account_id, Direction.CREDIT, payment.amount, memo),
        ],
        actor_id=approver.id if approver else None,
        effective_date=now.date(),
    )
    payment.status = PaymentStatus.RELEASED.value
    payment.journal_entry_id = entry.id
    payment.approved_by = approver.id if approver else None
    payment.decided_at = now
    db.flush()
    record_audit_event(
        db,
        actor_id=approver.id if approver else None,
        action="payment.released",
        entity_type="payment",
        entity_id=payment.id,
        metadata={"payment_number": payment.payment_number, "entry": entry.entry_number},
    )
    return payment


def reject(db: Session, payment_id: uuid.UUID, reason: str, now: datetime | None = None) -> Payment:
    payment = get_payment(db, payment_id, for_update=True)
    if payment.status != PaymentStatus.PENDING:
        raise ConflictError(f"The payment is {payment.status}.")
    payment.status = PaymentStatus.REJECTED.value
    payment.rejection_reason = reason[:500]
    payment.decided_at = now or datetime.now(UTC)
    db.flush()
    record_audit_event(
        db,
        actor_id=None,
        action="payment.rejected",
        entity_type="payment",
        entity_id=payment.id,
        metadata={"payment_number": payment.payment_number, "reason": reason[:500]},
    )
    return payment


def released_between(db: Session, debtor_id: uuid.UUID, creditor_id: uuid.UUID) -> int:
    """How many payments this debtor has already released to this creditor."""
    return db.execute(
        select(func.count()).where(
            Payment.debtor_account_id == debtor_id,
            Payment.creditor_account_id == creditor_id,
            Payment.status == PaymentStatus.RELEASED,
        )
    ).scalar_one()


def recent_count(db: Session, debtor_id: uuid.UUID, since: datetime, exclude: uuid.UUID) -> int:
    """Payments the debtor started since `since` (any outcome), excluding one."""
    return db.execute(
        select(func.count()).where(
            Payment.debtor_account_id == debtor_id,
            Payment.created_at >= since,
            Payment.id != exclude,
        )
    ).scalar_one()


def list_payments(
    db: Session,
    params: PageParams,
    *,
    status: str | None = None,
    account_id: uuid.UUID | None = None,
    q: str | None = None,
) -> tuple[list[Payment], int]:
    query = select(Payment).order_by(Payment.created_at.desc(), Payment.payment_number.desc())
    if status:
        query = query.where(Payment.status == status)
    if account_id:
        query = query.where(
            (Payment.debtor_account_id == account_id) | (Payment.creditor_account_id == account_id)
        )
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(
            Payment.payment_number.ilike(pattern) | Payment.reference.ilike(pattern)
        )
    return paginate(db, query, params)


def payments_out(db: Session, payments: list[Payment]) -> list[PaymentOut]:
    if not payments:
        return []
    account_ids = {p.debtor_account_id for p in payments} | {
        p.creditor_account_id for p in payments
    }
    holder = aliased(Customer)
    accounts = {
        account_id: (number, name)
        for account_id, number, name in db.execute(
            select(Account.id, Account.account_number, holder.name)
            .join(holder, and_(holder.id == Account.customer_id))
            .where(Account.id.in_(account_ids))
        ).all()
    }
    user_ids = {p.initiated_by for p in payments} | {
        p.approved_by for p in payments if p.approved_by
    }
    names = dict(db.execute(select(User.id, User.username).where(User.id.in_(user_ids))).all())
    return [
        PaymentOut(
            id=p.id,
            payment_number=p.payment_number,
            debtor_account_number=accounts[p.debtor_account_id][0],
            debtor_name=accounts[p.debtor_account_id][1],
            creditor_account_number=accounts[p.creditor_account_id][0],
            creditor_name=accounts[p.creditor_account_id][1],
            amount=p.amount,
            currency=p.currency,
            reference=p.reference,
            status=p.status,
            high_value=is_high_value(p.amount, p.currency),
            initiated_by_username=names.get(p.initiated_by),
            approved_by_username=names.get(p.approved_by) if p.approved_by else None,
            journal_entry_id=p.journal_entry_id,
            rejection_reason=p.rejection_reason,
            workflow_execution_id=p.workflow_execution_id,
            created_at=p.created_at,
            decided_at=p.decided_at,
        )
        for p in payments
    ]
