"""Collections and recoveries (Phase 53): payment plans and recoveries on written-off loans."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.modules.collections.models import (
    PLAN_SEQUENCE,
    RECOVERY_SEQUENCE,
    LoanRecovery,
    PaymentPlan,
    PlanStatus,
    RecoveryKind,
    RecoveryStatus,
)
from app.modules.identity.service import AuthenticatedUser
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, JournalLine, LedgerAccount, LedgerAccountType
from app.modules.lending import servicing
from app.modules.lending.models import Loan, LoanStatus

MISSED_TO_BREAK = 2  # missed payments that break a plan


def _audit(db, actor_id, action: str, entity_type: str, entity_id, **metadata) -> None:
    record_audit_event(db, actor_id=actor_id, action=action, entity_type=entity_type,
                       entity_id=entity_id, metadata=metadata)  # fmt: skip


def find_loan(db: Session, number: str) -> Loan:
    loan = db.execute(
        select(Loan).where(Loan.loan_number == number.strip().upper())
    ).scalar_one_or_none()  # fmt: skip
    if loan is None:
        raise NotFoundError(f"No loan {number}.")
    return loan


def open_plan(db: Session, loan_id: uuid.UUID) -> PaymentPlan | None:
    return db.execute(
        select(PaymentPlan).where(PaymentPlan.loan_id == loan_id,
                                  PaymentPlan.status.in_([PlanStatus.PROPOSED,
                                                          PlanStatus.ACTIVE]))
    ).scalar_one_or_none()  # fmt: skip


def active_plan(db: Session, loan_id: uuid.UUID) -> PaymentPlan | None:
    plan = open_plan(db, loan_id)
    return plan if plan is not None and plan.status == PlanStatus.ACTIVE else None


# --- Payment plans ----------------------------------------------------------------------------


def propose_plan(db: Session, loan: Loan, interval_days: int, proposed_by: uuid.UUID,
                 today: date | None = None) -> PaymentPlan:  # fmt: skip
    """Spread the loan's arrears into catch-up payments, one per overdue instalment, every
    `interval_days`, the first one interval from today. A second person approves it."""
    today = today or servicing.current_date(db)
    if loan.status != LoanStatus.ACTIVE:
        raise ConflictError(f"{loan.loan_number} is {loan.status}.")
    if not 7 <= interval_days <= 31:
        raise BusinessRuleViolation("Plan payments fall 7 to 31 days apart.",
                                    {"rule": "interval_range"})  # fmt: skip
    state = servicing.arrears(db, loan, today)
    if state.instalments == 0:
        raise BusinessRuleViolation(f"{loan.loan_number} is not in arrears.",
                                    {"rule": "not_in_arrears"})  # fmt: skip
    if open_plan(db, loan.id) is not None:
        raise ConflictError(f"{loan.loan_number} already has a plan.")
    due = [i for i in servicing.instalments_of(db, loan.id) if i.status == "due"]
    schedule = [{"n": n + 1, "due": (today + timedelta(days=interval_days * (n + 1))).isoformat(),
                 "amount": instalment.amount, "status": "due", "on": None}
                for n, instalment in enumerate(sorted(due, key=lambda i: i.due_date))]  # fmt: skip
    number = f"PLN-{db.execute(PLAN_SEQUENCE.next_value()).scalar_one():07d}"
    plan = PaymentPlan(
        plan_number=number, loan_id=loan.id, status=PlanStatus.PROPOSED.value,
        arrears_amount=state.amount, days_past_due=state.days_past_due,
        payments=len(schedule), interval_days=interval_days, schedule=schedule, missed=0,
        proposed_by=proposed_by, start_date=today,
    )  # fmt: skip
    db.add(plan)
    db.flush()
    _audit(db, proposed_by, "collections.plan_proposed", "payment_plan", plan.id,
           plan_number=number, loan_number=loan.loan_number)  # fmt: skip
    return plan


def get_plan(db: Session, plan_id: uuid.UUID, *, for_update: bool = False) -> PaymentPlan:
    query = select(PaymentPlan).where(PaymentPlan.id == plan_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    plan = db.execute(query).scalar_one_or_none()
    if plan is None:
        raise NotFoundError("Plan not found.")
    return plan


def find_plan(db: Session, number: str) -> PaymentPlan | None:
    return db.execute(
        select(PaymentPlan).where(PaymentPlan.plan_number == number.strip().upper())
    ).scalar_one_or_none()


def _decide(row, actor_id: uuid.UUID, by: uuid.UUID, pending: str, who: str) -> None:
    if row.status != pending:
        raise ConflictError(f"It is {row.status}.")
    if actor_id == by:
        raise BusinessRuleViolation(f"Four-eyes rule: the person who {who} it cannot decide it.",
                                    {"rule": "four_eyes"})  # fmt: skip


def decide_plan(db: Session, plan: PaymentPlan, actor_id: uuid.UUID, approve: bool,
                note: str = "") -> PaymentPlan:  # fmt: skip
    plan = get_plan(db, plan.id, for_update=True)
    _decide(plan, actor_id, plan.proposed_by, PlanStatus.PROPOSED, "proposed")
    plan.status = (PlanStatus.ACTIVE if approve else PlanStatus.REJECTED).value
    plan.approved_by, plan.decided_at = actor_id, datetime.now(UTC)
    plan.note = note.strip() or None
    db.flush()
    _audit(db, actor_id, "collections.plan_decided", "payment_plan", plan.id,
           plan_number=plan.plan_number, status=plan.status)  # fmt: skip
    return plan


def collect_plan(db: Session, plan: PaymentPlan, as_of: date, actor: AuthenticatedUser
                 ) -> dict[str, int]:  # fmt: skip
    """Take one active plan's payments due by `as_of`: each settles the loan's oldest overdue
    instalment from the borrower's account. A payment the account cannot cover is missed;
    two missed, or a schedule run out with one missed, break the plan. One the borrower
    already settled counts as settled; a plan paid or settled throughout completes."""
    paid = missed = 0
    schedule = [dict(p) for p in plan.schedule]
    for payment in schedule:
        if payment["status"] != "due" or date.fromisoformat(payment["due"]) > as_of:
            continue
        try:
            key = f"plan:{plan.plan_number}:{payment['n']}"
            with db.begin_nested():
                servicing.repay_arrears(db, plan.loan_id, actor, instalments=1, key=key)
            payment["status"], payment["on"] = "paid", as_of.isoformat()
            paid += 1
        except BusinessRuleViolation:
            payment["status"], payment["on"] = "missed", as_of.isoformat()
            plan.missed += 1
            missed += 1
        except ConflictError:  # nothing overdue any more: the borrower caught up
            payment["status"], payment["on"] = "settled", as_of.isoformat()
    plan.schedule = schedule
    finished = all(p["status"] != "due" for p in schedule)
    completed = broken = 0
    if plan.missed >= MISSED_TO_BREAK or (finished and plan.missed):
        plan.status, broken = PlanStatus.BROKEN.value, 1
    elif all(p["status"] in ("paid", "settled") for p in schedule):
        plan.status, completed = PlanStatus.COMPLETED.value, 1
    db.flush()
    return {"paid": paid, "missed": missed, "completed": completed, "broken": broken}


def collect(db: Session, as_of: date, actor: AuthenticatedUser) -> dict[str, int]:
    """Take every active plan's payments due by `as_of` (see `collect_plan`)."""
    plans = db.execute(
        select(PaymentPlan).where(PaymentPlan.status == PlanStatus.ACTIVE)
        .order_by(PaymentPlan.plan_number).with_for_update(skip_locked=True)
    ).scalars().all()  # fmt: skip
    totals = {"plans": len(plans), "paid": 0, "missed": 0, "completed": 0, "broken": 0}
    for plan in plans:
        for key, value in collect_plan(db, plan, as_of, actor).items():
            totals[key] += value
    return totals


def plan_profile(db: Session, plan: PaymentPlan) -> dict[str, Any]:
    """What an approver weighs before activating a payment plan (Phase 54), as of the day it
    was proposed: the arrears and how late they are; what the borrower would pay a month
    while the plan runs (the regular instalment plus the catch-up payments) against the money
    paid into their account in the 90 days before, and how long since the last of it; the
    loan's age; and the borrower's earlier payment plans and how many they broke."""
    from app.modules.accounts.models import Account
    from app.modules.ledger.models import JournalEntry
    from app.modules.risk import service as risk

    loan = db.get(Loan, plan.loan_id)
    today = plan.start_date
    account = db.get(Account, loan.disbursement_account_id)
    credits = db.execute(
        select(JournalLine.amount, JournalEntry.effective_date)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(JournalLine.ledger_account_id == account.ledger_account_id,
               JournalLine.direction == Direction.CREDIT,
               JournalEntry.source != "loan_disbursement",
               JournalEntry.effective_date > today - timedelta(days=90),
               JournalEntry.effective_date <= today)
    ).all()  # fmt: skip
    inflow = sum(int(amount) for amount, _ in credits)
    monthly_inflow = inflow // 3
    catch_up = plan.arrears_amount // plan.payments
    commitment = loan.monthly_payment + catch_up * 30 // plan.interval_days
    earlier = db.execute(
        select(PaymentPlan.status).join(Loan, Loan.id == PaymentPlan.loan_id)
        .where(Loan.customer_id == loan.customer_id, PaymentPlan.id != plan.id)
    ).scalars().all()  # fmt: skip
    return {
        "currency": loan.currency, "arrears_amount": plan.arrears_amount,
        "arrears_usd": risk._usd(db, plan.arrears_amount, loan.currency, today),
        "days_past_due": plan.days_past_due, "overdue_instalments": plan.payments,
        "interval_days": plan.interval_days, "monthly_payment": loan.monthly_payment,
        "monthly_commitment": commitment, "inflow_90d": inflow, "credits_90d": len(credits),
        "commitment_to_income_pct": commitment * 100 // monthly_inflow if monthly_inflow
        else 999,
        "days_since_last_credit": (today - max(d for _, d in credits)).days if credits
        else 999,
        "loan_age_days": (today - loan.disbursed_at.date()).days,
        "prior_plans": len(earlier),
        "prior_plans_broken": sum(1 for status in earlier if status == PlanStatus.BROKEN),
    }  # fmt: skip


# --- Recoveries -------------------------------------------------------------------------------


def recoveries_account(db: Session, currency: str) -> LedgerAccount:
    return ledger.ensure_ledger_account(
        db, code=f"LOAN-RECOVERIES-{currency}", name=f"Loan loss recoveries ({currency})",
        account_type=LedgerAccountType.INCOME, currency=currency,
    )  # fmt: skip


def written_off_amount(db: Session, loan: Loan) -> int:
    """The loss booked when the loan was written off."""
    if loan.write_off_entry_id is None:
        return 0
    return int(db.execute(
        select(func.coalesce(func.sum(JournalLine.amount), 0))
        .where(JournalLine.journal_entry_id == loan.write_off_entry_id,
               JournalLine.direction == Direction.DEBIT)
    ).scalar_one())  # fmt: skip


def recovered(db: Session, loan: Loan) -> int:
    """Recovered so far, counting a debt sale awaiting approval."""
    return int(db.execute(
        select(func.coalesce(func.sum(LoanRecovery.amount), 0))
        .where(LoanRecovery.loan_id == loan.id,
               LoanRecovery.status.in_([RecoveryStatus.POSTED, RecoveryStatus.RECORDED]))
    ).scalar_one())  # fmt: skip


def _post_recovery(db: Session, recovery: LoanRecovery, loan: Loan, actor_id: uuid.UUID) -> None:
    memo = f"{recovery.recovery_number} {recovery.kind.replace('_', ' ')} on {loan.loan_number}"
    entry, _ = ledger.post_entry(
        db, idempotency_key=f"loan-recovery:{recovery.recovery_number}",
        currency=recovery.currency, description=memo, source="loan_recovery",
        lines=[ledger.LineSpec(ledger.cash_account(db, recovery.currency).id, Direction.DEBIT,
                               recovery.amount, memo),
               ledger.LineSpec(recoveries_account(db, recovery.currency).id, Direction.CREDIT,
                               recovery.amount, memo)],
        actor_id=actor_id,
    )  # fmt: skip
    recovery.status, recovery.entry_number = RecoveryStatus.POSTED.value, entry.entry_number


def record_recovery(db: Session, loan: Loan, kind: str, amount: int, recorded_by: uuid.UUID,
                    note: str = "") -> LoanRecovery:  # fmt: skip
    """Record money recovered on a written-off loan; never more than was written off. A
    payment or an agency's remittance is posted at once; a debt sale waits for the credit
    committee."""
    if loan.status != LoanStatus.WRITTEN_OFF:
        raise BusinessRuleViolation(f"{loan.loan_number} is not written off.",
                                    {"rule": "not_written_off"})  # fmt: skip
    if kind not in set(RecoveryKind) or amount <= 0:
        raise BusinessRuleViolation(
            "A recovery is a payment, agency remittance or debt sale of a positive amount.",
            {"rule": "recovery_invalid"},
        )
    db.execute(select(Loan.id).where(Loan.id == loan.id).with_for_update())
    remaining = written_off_amount(db, loan) - recovered(db, loan)
    if amount > remaining:
        raise BusinessRuleViolation(
            f"Only {remaining} minor units of {loan.loan_number} remain to recover.",
            {"rule": "exceeds_written_off", "remaining": remaining},
        )
    number = f"REC-{db.execute(RECOVERY_SEQUENCE.next_value()).scalar_one():07d}"
    recovery = LoanRecovery(recovery_number=number, loan_id=loan.id, kind=kind, amount=amount,
                            currency=loan.currency, status=RecoveryStatus.RECORDED.value,
                            recorded_by=recorded_by, note=note.strip() or None)  # fmt: skip
    db.add(recovery)
    db.flush()
    if kind != RecoveryKind.DEBT_SALE:
        _post_recovery(db, recovery, loan, recorded_by)
        db.flush()
    _audit(db, recorded_by, "collections.recovery_recorded", "loan_recovery", recovery.id,
           recovery_number=number, kind=kind, amount=amount)  # fmt: skip
    return recovery


def get_recovery(db: Session, recovery_id: uuid.UUID, *, for_update: bool = False
                 ) -> LoanRecovery:  # fmt: skip
    query = select(LoanRecovery).where(LoanRecovery.id == recovery_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    recovery = db.execute(query).scalar_one_or_none()
    if recovery is None:
        raise NotFoundError("Recovery not found.")
    return recovery


def decide_recovery(db: Session, recovery: LoanRecovery, actor_id: uuid.UUID, approve: bool,
                    note: str = "") -> LoanRecovery:  # fmt: skip
    """Approve (post) or reject a debt sale: not by whoever recorded it."""
    recovery = get_recovery(db, recovery.id, for_update=True)
    _decide(recovery, actor_id, recovery.recorded_by, RecoveryStatus.RECORDED, "recorded")
    if approve:
        _post_recovery(db, recovery, db.get(Loan, recovery.loan_id), actor_id)
    else:
        recovery.status = RecoveryStatus.REJECTED.value
    recovery.approved_by, recovery.decided_at = actor_id, datetime.now(UTC)
    if note.strip():
        recovery.note = note.strip()
    db.flush()
    _audit(db, actor_id, "collections.recovery_decided", "loan_recovery", recovery.id,
           recovery_number=recovery.recovery_number, status=recovery.status)  # fmt: skip
    return recovery


def arrears_book(db: Session, on: date | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """Active loans in arrears, most days past due first, with any open plan."""
    from app.modules.customers.models import Customer

    on = on or servicing.current_date(db)
    out = []
    for loan in db.execute(
        select(Loan).where(Loan.status == LoanStatus.ACTIVE).order_by(Loan.loan_number)
    ).scalars():  # fmt: skip
        state = servicing.arrears(db, loan, on)
        if state.instalments == 0:
            continue
        plan = open_plan(db, loan.id)
        customer = db.get(Customer, loan.customer_id)
        out.append({"loan_number": loan.loan_number, "customer_number": customer.customer_number,
                    "customer_name": customer.name, "currency": loan.currency,
                    **state.as_dict(), "plan_number": plan.plan_number if plan else None,
                    "plan_status": plan.status if plan else None})  # fmt: skip
    out.sort(key=lambda r: (-r["days_past_due"], r["loan_number"]))
    return out[:limit]


def written_off_book(db: Session, limit: int = 200) -> list[dict[str, Any]]:
    from app.modules.customers.models import Customer

    out = []
    for loan in db.execute(
        select(Loan).where(Loan.status == LoanStatus.WRITTEN_OFF)
        .order_by(Loan.closed_on.desc(), Loan.loan_number).limit(limit)
    ).scalars():  # fmt: skip
        customer = db.get(Customer, loan.customer_id)
        written, back = written_off_amount(db, loan), recovered(db, loan)
        out.append({"loan_number": loan.loan_number, "customer_number": customer.customer_number,
                    "customer_name": customer.name, "currency": loan.currency,
                    "written_off_on": loan.closed_on.isoformat() if loan.closed_on else None,
                    "written_off": written, "recovered": back,
                    "remaining": written - back})  # fmt: skip
    return out


def summary(db: Session) -> dict[str, Any]:
    def count(model, *where) -> int:
        return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()

    return {
        "plans_proposed": count(PaymentPlan, PaymentPlan.status == PlanStatus.PROPOSED),
        "plans_active": count(PaymentPlan, PaymentPlan.status == PlanStatus.ACTIVE),
        "plans_broken": count(PaymentPlan, PaymentPlan.status == PlanStatus.BROKEN),
        "plans_completed": count(PaymentPlan, PaymentPlan.status == PlanStatus.COMPLETED),
        "debt_sales_to_approve": count(LoanRecovery,
                                       LoanRecovery.status == RecoveryStatus.RECORDED),
        "loans_written_off": count(Loan, Loan.status == LoanStatus.WRITTEN_OFF),
    }  # fmt: skip
