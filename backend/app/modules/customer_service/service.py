"""Customer service (Phase 51): cases, complaints, SLA timers and redress."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.modules.accounts.models import Account, AccountStatus
from app.modules.customer_service.models import (
    CASE_SEQUENCE,
    CaseCategory,
    CaseEvent,
    CasePriority,
    CaseStatus,
    ComplaintOutcome,
    RedressStatus,
    ServiceCase,
)
from app.modules.customers.models import Customer
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, LedgerAccount, LedgerAccountType

CHANNELS = ("phone", "email", "chat", "branch", "letter")
TOPICS = ("account", "card", "payments", "lending", "fees", "digital", "other")
# Hours to the first response and to resolution, by priority.
SLA_HOURS = {
    CasePriority.URGENT: (1, 8),
    CasePriority.HIGH: (4, 24),
    CasePriority.NORMAL: (8, 72),
    CasePriority.LOW: (24, 120),
}
# Complaints: acknowledged within two days, a final response within eight weeks.
COMPLAINT_HOURS = (48, 56 * 24)
ESCALATE = {
    CasePriority.LOW: CasePriority.NORMAL,
    CasePriority.NORMAL: CasePriority.HIGH,
    CasePriority.HIGH: CasePriority.URGENT,
    CasePriority.URGENT: CasePriority.URGENT,
}


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _event(db: Session, case: ServiceCase, kind: str, actor_id: uuid.UUID | None,
           at: datetime, **detail) -> None:  # fmt: skip
    db.add(CaseEvent(case_id=case.id, kind=kind, actor_id=actor_id, at=at, detail=detail))


def _audit(db, actor_id, action: str, case: ServiceCase, **metadata) -> None:
    record_audit_event(db, actor_id=actor_id, action=action, entity_type="service_case",
                       entity_id=case.id,
                       metadata={"case_number": case.case_number, **metadata})  # fmt: skip


def sla_hours(category: str, priority: str) -> tuple[int, int]:
    if category == CaseCategory.COMPLAINT:
        return COMPLAINT_HOURS
    return SLA_HOURS[CasePriority(priority)]


def open_case(db: Session, customer: Customer, *, category: str, channel: str, topic: str,
              priority: str, subject: str, description: str, opened_by: uuid.UUID | None,
              account: Account | None = None,
              now: datetime | None = None) -> ServiceCase:  # fmt: skip
    """Open a case; its first response and resolution fall due by its priority (a complaint's
    by the complaint rules)."""
    now = _now(now)
    if category not in set(CaseCategory) or channel not in CHANNELS or topic not in TOPICS:
        raise BusinessRuleViolation("Unknown category, channel or topic.",
                                    {"rule": "case_invalid"})  # fmt: skip
    if priority not in set(CasePriority):
        raise BusinessRuleViolation(f"Unknown priority {priority}.", {"rule": "case_invalid"})
    if account is not None and account.customer_id != customer.id:
        raise BusinessRuleViolation("The account belongs to someone else.",
                                    {"rule": "account_owner"})  # fmt: skip
    respond_in, resolve_in = sla_hours(category, priority)
    number = f"SRV-{db.execute(CASE_SEQUENCE.next_value()).scalar_one():07d}"
    case = ServiceCase(
        case_number=number, customer_id=customer.id,
        account_id=account.id if account else None, category=category, channel=channel,
        topic=topic, priority=priority, subject=subject.strip()[:200] or "Customer contact",
        description=description.strip()[:2000] or "-", status=CaseStatus.OPEN.value,
        opened_by=opened_by, assigned_to=opened_by, opened_at=now,
        first_response_due=now + timedelta(hours=respond_in),
        resolve_due=now + timedelta(hours=resolve_in), paused_seconds=0,
        response_breached=False, resolution_breached=False, escalated=False,
    )  # fmt: skip
    db.add(case)
    db.flush()
    _event(db, case, "opened", opened_by, now, channel=channel, priority=priority)
    _audit(db, opened_by, "service.case_opened", case, category=category)
    return case


def get_case(db: Session, case_id: uuid.UUID, *, for_update: bool = False) -> ServiceCase:
    query = select(ServiceCase).where(ServiceCase.id == case_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    case = db.execute(query).scalar_one_or_none()
    if case is None:
        raise NotFoundError("Case not found.")
    return case


def find_case(db: Session, number: str) -> ServiceCase | None:
    return db.execute(
        select(ServiceCase).where(ServiceCase.case_number == number.strip().upper())
    ).scalar_one_or_none()


def _open(db: Session, case: ServiceCase) -> ServiceCase:
    case = get_case(db, case.id, for_update=True)
    if case.status == CaseStatus.RESOLVED:
        raise ConflictError(f"{case.case_number} is resolved.")
    return case


def respond(db: Session, case: ServiceCase, actor_id: uuid.UUID | None, message: str,
            now: datetime | None = None) -> ServiceCase:  # fmt: skip
    """Reply to the customer. The first reply meets the first-response SLA (for a complaint,
    the acknowledgement)."""
    now = _now(now)
    case = _open(db, case)
    first = case.first_responded_at is None
    if first:
        case.first_responded_at = now
    _event(db, case, "responded", actor_id, now, message=message.strip()[:500], first=first)
    db.flush()
    return case


def assign(db: Session, case: ServiceCase, user_id: uuid.UUID, actor_id: uuid.UUID | None,
           now: datetime | None = None) -> ServiceCase:  # fmt: skip
    now = _now(now)
    case = _open(db, case)
    case.assigned_to = user_id
    _event(db, case, "assigned", actor_id, now, assigned_to=str(user_id))
    db.flush()
    return case


def await_customer(db: Session, case: ServiceCase, actor_id: uuid.UUID | None,
                   now: datetime | None = None) -> ServiceCase:  # fmt: skip
    """Waiting on the customer pauses the SLA clock (not for a complaint's final response,
    which runs regardless)."""
    now = _now(now)
    case = _open(db, case)
    if case.status == CaseStatus.AWAITING_CUSTOMER:
        raise ConflictError(f"{case.case_number} is already awaiting the customer.")
    case.status, case.paused_at = CaseStatus.AWAITING_CUSTOMER.value, now
    _event(db, case, "awaiting_customer", actor_id, now)
    db.flush()
    return case


def resume(db: Session, case: ServiceCase, actor_id: uuid.UUID | None,
           now: datetime | None = None) -> ServiceCase:  # fmt: skip
    """The customer replied: the clock restarts and the due times move by the pause."""
    now = _now(now)
    case = _open(db, case)
    if case.status != CaseStatus.AWAITING_CUSTOMER or case.paused_at is None:
        raise ConflictError(f"{case.case_number} is not awaiting the customer.")
    paused = now - case.paused_at
    case.paused_seconds += int(paused.total_seconds())
    if case.first_responded_at is None:
        case.first_response_due += paused
    if case.category != CaseCategory.COMPLAINT:  # a complaint's final response runs regardless
        case.resolve_due += paused
    case.status, case.paused_at = CaseStatus.OPEN.value, None
    _event(db, case, "resumed", actor_id, now, paused_seconds=int(paused.total_seconds()))
    db.flush()
    return case


def sweep(db: Session, actor_id: uuid.UUID | None, now: datetime | None = None
          ) -> dict[str, int]:  # fmt: skip
    """Mark overdue cases breached. A missed first response escalates the case one priority;
    a missed resolution escalates it to the manager's queue (escalated). A case awaiting the
    customer is not overdue, except a complaint's final response."""
    now = _now(now)
    rows = db.execute(
        select(ServiceCase).where(ServiceCase.status != CaseStatus.RESOLVED)
        .where((ServiceCase.response_breached.is_(False) & ServiceCase.first_responded_at.is_(None)
                & (ServiceCase.first_response_due < now))
               | (ServiceCase.resolution_breached.is_(False) & (ServiceCase.resolve_due < now)))
        .order_by(ServiceCase.case_number).with_for_update(skip_locked=True)
    ).scalars().all()  # fmt: skip
    response = resolution = 0
    for case in rows:
        paused = case.status == CaseStatus.AWAITING_CUSTOMER
        if (not case.response_breached and case.first_responded_at is None
                and case.first_response_due < now and not paused):  # fmt: skip
            case.response_breached = True
            case.priority = ESCALATE[CasePriority(case.priority)].value
            _event(db, case, "response_breached", actor_id, now, priority=case.priority)
            response += 1
        if (not case.resolution_breached and case.resolve_due < now
                and (not paused or case.category == CaseCategory.COMPLAINT)):  # fmt: skip
            case.resolution_breached, case.escalated = True, True
            _event(db, case, "resolution_breached", actor_id, now)
            resolution += 1
    db.flush()
    return {"checked": len(rows), "response_breached": response,
            "resolution_breached": resolution, "swept_at": now.isoformat()}  # fmt: skip


def redress_account(db: Session, currency: str) -> LedgerAccount:
    return ledger.ensure_ledger_account(
        db, code=f"CS-REDRESS-{currency}", name=f"Complaint redress ({currency})",
        account_type=LedgerAccountType.EXPENSE, currency=currency,
    )  # fmt: skip


def propose_redress(db: Session, case: ServiceCase, amount: int, account: Account,
                    actor_id: uuid.UUID | None, now: datetime | None = None
                    ) -> ServiceCase:  # fmt: skip
    """Propose redress for a complaint, to be paid into one of the customer's accounts once
    someone else approves it."""
    now = _now(now)
    case = _open(db, case)
    if case.category != CaseCategory.COMPLAINT:
        raise BusinessRuleViolation("Only complaints carry redress.", {"rule": "not_complaint"})
    if case.redress_status in (RedressStatus.PROPOSED, RedressStatus.PAID):
        raise ConflictError(f"{case.case_number}'s redress is already {case.redress_status}.")
    if amount <= 0:
        raise BusinessRuleViolation("Redress is a positive amount.", {"rule": "amount"})
    if account.customer_id != case.customer_id or account.status != AccountStatus.OPEN:
        raise BusinessRuleViolation("Redress goes to one of the customer's open accounts.",
                                    {"rule": "account_owner"})  # fmt: skip
    case.redress_amount, case.redress_status = amount, RedressStatus.PROPOSED.value
    case.redress_proposed_by, case.redress_approved_by, case.account_id = actor_id, None, account.id
    _event(db, case, "redress_proposed", actor_id, now, amount=amount, currency=account.currency)
    db.flush()
    _audit(db, actor_id, "service.redress_proposed", case, amount=amount)
    return case


def pay_redress(db: Session, case: ServiceCase, actor_id: uuid.UUID,
                now: datetime | None = None) -> ServiceCase:  # fmt: skip
    """Pay the proposed redress into the customer's account: not by whoever proposed it."""
    now = _now(now)
    case = _open(db, case)
    if case.redress_status != RedressStatus.PROPOSED:
        raise ConflictError(f"{case.case_number} has no redress awaiting approval.")
    if actor_id == case.redress_proposed_by:
        raise BusinessRuleViolation("Four-eyes rule: the person who proposed the redress "
                                    "cannot pay it.", {"rule": "four_eyes"})  # fmt: skip
    account = db.get(Account, case.account_id)
    if account is None or account.status != AccountStatus.OPEN:
        raise BusinessRuleViolation("The customer's account is not open.",
                                    {"rule": "account_not_open"})  # fmt: skip
    memo = f"{case.case_number} complaint redress"
    entry, _ = ledger.post_entry(
        db, idempotency_key=f"service-redress:{case.case_number}", currency=account.currency,
        description=memo, source="complaint_redress",
        lines=[ledger.LineSpec(redress_account(db, account.currency).id, Direction.DEBIT,
                               case.redress_amount, memo),
               ledger.LineSpec(account.ledger_account_id, Direction.CREDIT,
                               case.redress_amount, memo)],
        actor_id=actor_id,
    )  # fmt: skip
    case.redress_status, case.redress_approved_by = RedressStatus.PAID.value, actor_id
    case.redress_entry = entry.entry_number
    _event(db, case, "redress_paid", actor_id, now, entry_number=entry.entry_number)
    db.flush()
    _audit(db, actor_id, "service.redress_paid", case, entry_number=entry.entry_number)
    return case


def withdraw_redress(db: Session, case: ServiceCase, actor_id: uuid.UUID | None,
                     now: datetime | None = None) -> ServiceCase:  # fmt: skip
    now = _now(now)
    case = _open(db, case)
    if case.redress_status != RedressStatus.PROPOSED:
        raise ConflictError(f"{case.case_number} has no redress awaiting approval.")
    case.redress_status = RedressStatus.WITHDRAWN.value
    _event(db, case, "redress_withdrawn", actor_id, now)
    db.flush()
    return case


def resolve(db: Session, case: ServiceCase, actor_id: uuid.UUID | None, resolution: str,
            outcome: str | None = None, now: datetime | None = None) -> ServiceCase:  # fmt: skip
    """Resolve the case. A complaint needs a final response with an outcome; redress awaiting
    approval must be paid or withdrawn first, and an upheld complaint's redress paid."""
    now = _now(now)
    case = _open(db, case)
    if case.category == CaseCategory.COMPLAINT:
        if outcome not in set(ComplaintOutcome):
            raise BusinessRuleViolation("A complaint's final response needs an outcome.",
                                        {"rule": "outcome_required"})  # fmt: skip
        if case.redress_status == RedressStatus.PROPOSED:
            raise BusinessRuleViolation("Pay or withdraw the proposed redress first.",
                                        {"rule": "redress_pending"})  # fmt: skip
    elif outcome is not None:
        raise BusinessRuleViolation("Only complaints have an outcome.", {"rule": "not_complaint"})
    if case.first_responded_at is None:
        case.first_responded_at = now  # the resolution is the response
    case.status, case.paused_at = CaseStatus.RESOLVED.value, None
    case.resolved_at, case.resolved_by = now, actor_id
    case.resolution, case.outcome = resolution.strip()[:1000] or "Resolved", outcome
    _event(db, case, "resolved", actor_id, now, outcome=outcome)
    db.flush()
    _audit(db, actor_id, "service.case_resolved", case, outcome=outcome)
    return case


def events(db: Session, case: ServiceCase) -> list[CaseEvent]:
    return list(db.execute(
        select(CaseEvent).where(CaseEvent.case_id == case.id)
        .order_by(CaseEvent.at, CaseEvent.id)
    ).scalars())  # fmt: skip


def summary(db: Session, now: datetime | None = None) -> dict[str, Any]:
    now = _now(now)

    def count(*where) -> int:
        return db.execute(select(func.count()).select_from(ServiceCase).where(*where)).scalar_one()

    unresolved = ServiceCase.status != CaseStatus.RESOLVED
    responded = db.execute(
        select(func.avg(func.extract("epoch", ServiceCase.first_responded_at
                                     - ServiceCase.opened_at)))
        .where(ServiceCase.first_responded_at.is_not(None))
    ).scalar_one()  # fmt: skip
    return {
        "open": count(unresolved),
        "awaiting_customer": count(ServiceCase.status == CaseStatus.AWAITING_CUSTOMER),
        "complaints_open": count(unresolved, ServiceCase.category == CaseCategory.COMPLAINT),
        "breached": count(unresolved, ServiceCase.response_breached
                          | ServiceCase.resolution_breached),
        "due_today": count(unresolved, ServiceCase.resolve_due < now + timedelta(days=1)),
        "redress_to_approve": count(ServiceCase.redress_status == RedressStatus.PROPOSED),
        "avg_first_response_minutes": round(float(responded) / 60, 1) if responded else None,
    }  # fmt: skip
