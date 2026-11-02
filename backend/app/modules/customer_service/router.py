"""Customer service API (Phase 51)."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.errors import BusinessRuleViolation
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
from app.modules.accounts.models import Account
from app.modules.customer_service import service
from app.modules.customer_service.models import ServiceCase
from app.modules.customers.models import Customer
from app.modules.identity.dependencies import Authorized

router = APIRouter(prefix="/customer-service", tags=["customer-service"])
READ, HANDLE = Permission.SERVICE_READ, Permission.SERVICE_HANDLE


class CaseOut(BaseModel):
    id: uuid.UUID
    case_number: str
    customer_number: str
    customer_name: str
    account_number: str | None
    category: str
    channel: str
    topic: str
    priority: str
    subject: str
    description: str
    status: str
    opened_at: datetime
    first_response_due: datetime
    resolve_due: datetime
    first_responded_at: datetime | None
    response_breached: bool
    resolution_breached: bool
    escalated: bool
    resolved_at: datetime | None
    resolution: str | None
    outcome: str | None
    redress_amount: int | None
    redress_status: str | None
    redress_entry: str | None
    currency: str | None


def _out(db, case: ServiceCase) -> CaseOut:
    customer = db.get(Customer, case.customer_id)
    account = db.get(Account, case.account_id) if case.account_id else None
    return CaseOut(
        id=case.id, case_number=case.case_number, customer_number=customer.customer_number,
        customer_name=customer.name, account_number=account.account_number if account else None,
        category=case.category, channel=case.channel, topic=case.topic,
        priority=case.priority, subject=case.subject, description=case.description,
        status=case.status, opened_at=case.opened_at,
        first_response_due=case.first_response_due, resolve_due=case.resolve_due,
        first_responded_at=case.first_responded_at, response_breached=case.response_breached,
        resolution_breached=case.resolution_breached, escalated=case.escalated,
        resolved_at=case.resolved_at, resolution=case.resolution, outcome=case.outcome,
        redress_amount=case.redress_amount, redress_status=case.redress_status,
        redress_entry=case.redress_entry, currency=account.currency if account else None,
    )  # fmt: skip


def _customer(db, number: str) -> Customer:
    customer = db.execute(
        select(Customer).where(Customer.customer_number == number.strip().upper())
    ).scalar_one_or_none()  # fmt: skip
    if customer is None:
        raise BusinessRuleViolation(f"No customer {number}.")
    return customer


def _account(db, number: str | None) -> Account | None:
    if not number:
        return None
    account = db.execute(
        select(Account).where(Account.account_number == number.strip().upper())
    ).scalar_one_or_none()  # fmt: skip
    if account is None:
        raise BusinessRuleViolation(f"No account {number}.")
    return account


class OpenIn(BaseModel):
    customer_number: str = Field(min_length=1, max_length=20)
    account_number: str | None = Field(default=None, max_length=34)
    category: str = Field(pattern="^(enquiry|request|complaint)$")
    channel: str = Field(pattern="^(phone|email|chat|branch|letter)$")
    topic: str = Field(pattern="^(account|card|payments|lending|fees|digital|other)$")
    priority: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")
    subject: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)


class ResolveIn(BaseModel):
    resolution: str = Field(min_length=1, max_length=1000)
    outcome: str | None = Field(default=None, pattern="^(upheld|partly_upheld|not_upheld)$")


class RedressIn(BaseModel):
    amount: int = Field(gt=0, le=100_000_000_00)
    account_number: str = Field(min_length=1, max_length=34)


@router.get("/cases", response_model=Page[CaseOut], summary="Cases, most urgent first")
def list_cases(db: DbSession, page: PageParamsDep, _: Authorized(READ),
               status_filter: Annotated[str | None, Query(alias="status")] = None,
               category: str | None = None,
               customer_number: str | None = None):  # fmt: skip
    query = select(ServiceCase)
    if status_filter == "unresolved":
        query = query.where(ServiceCase.status != "resolved")
    elif status_filter:
        query = query.where(ServiceCase.status == status_filter)
    if category:
        query = query.where(ServiceCase.category == category)
    if customer_number:
        query = query.where(ServiceCase.customer_id == _customer(db, customer_number).id)
    query = query.order_by((ServiceCase.status == "resolved"), ServiceCase.resolve_due,
                           ServiceCase.case_number)  # fmt: skip
    items, total = paginate(db, query, page)
    return Page(items=[_out(db, c) for c in items], total=total, limit=page.limit,
                offset=page.offset)  # fmt: skip


@router.post("/cases", response_model=CaseOut, status_code=status.HTTP_201_CREATED,
             summary="Open a case")  # fmt: skip
def open_case(body: OpenIn, db: DbSession, actor: Authorized(HANDLE)):
    case = service.open_case(
        db, _customer(db, body.customer_number), category=body.category, channel=body.channel,
        topic=body.topic, priority=body.priority, subject=body.subject,
        description=body.description, opened_by=actor.id,
        account=_account(db, body.account_number),
    )  # fmt: skip
    return _out(db, case)


@router.get("/cases/{case_id}/events", summary="The case's timeline")
def case_events(case_id: uuid.UUID, db: DbSession, _: Authorized(READ)) -> list[dict]:
    return [{"kind": e.kind, "at": e.at.isoformat(), "detail": e.detail}
            for e in service.events(db, service.get_case(db, case_id))]  # fmt: skip


@router.post("/cases/{case_id}/respond", response_model=CaseOut, summary="Reply to the customer")
def respond(case_id: uuid.UUID, body: MessageIn, db: DbSession, actor: Authorized(HANDLE)):
    return _out(db, service.respond(db, service.get_case(db, case_id), actor.id, body.message))


@router.post("/cases/{case_id}/await-customer", response_model=CaseOut,
             summary="Wait on the customer (pauses the SLA clock)")  # fmt: skip
def await_customer(case_id: uuid.UUID, db: DbSession, actor: Authorized(HANDLE)):
    return _out(db, service.await_customer(db, service.get_case(db, case_id), actor.id))


@router.post("/cases/{case_id}/resume", response_model=CaseOut, summary="The customer replied")
def resume(case_id: uuid.UUID, db: DbSession, actor: Authorized(HANDLE)):
    return _out(db, service.resume(db, service.get_case(db, case_id), actor.id))


@router.post("/cases/{case_id}/redress", response_model=CaseOut,
             summary="Propose complaint redress")  # fmt: skip
def propose_redress(case_id: uuid.UUID, body: RedressIn, db: DbSession,
                    actor: Authorized(HANDLE)):  # fmt: skip
    case = service.propose_redress(db, service.get_case(db, case_id), body.amount,
                                   _account(db, body.account_number), actor.id)  # fmt: skip
    return _out(db, case)


@router.post("/cases/{case_id}/redress/pay", response_model=CaseOut,
             summary="Pay the redress; not by whoever proposed it")  # fmt: skip
def pay_redress(case_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.SERVICE_APPROVE)):
    return _out(db, service.pay_redress(db, service.get_case(db, case_id), actor.id))


@router.post("/cases/{case_id}/redress/withdraw", response_model=CaseOut,
             summary="Withdraw the proposed redress")  # fmt: skip
def withdraw_redress(case_id: uuid.UUID, db: DbSession, actor: Authorized(HANDLE)):
    return _out(db, service.withdraw_redress(db, service.get_case(db, case_id), actor.id))


@router.post("/cases/{case_id}/resolve", response_model=CaseOut, summary="Resolve the case")
def resolve(case_id: uuid.UUID, body: ResolveIn, db: DbSession, actor: Authorized(HANDLE)):
    return _out(db, service.resolve(db, service.get_case(db, case_id), actor.id,
                                    body.resolution, body.outcome))  # fmt: skip


@router.post("/sweep", summary="Mark overdue cases breached and escalate them")
def sweep(db: DbSession, actor: Authorized(HANDLE)) -> dict:
    return service.sweep(db, actor.id)


@router.get("/summary/counts", summary="Counts for the customer service page")
def summary(db: DbSession, _: Authorized(READ)) -> dict:
    return service.summary(db)
