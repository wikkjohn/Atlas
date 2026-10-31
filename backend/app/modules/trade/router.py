"""Trade finance API (Phase 37)."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.errors import BusinessRuleViolation
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
from app.modules.accounts import service as accounts
from app.modules.customers.models import Customer
from app.modules.identity.dependencies import Authorized
from app.modules.trade import service
from app.modules.trade.models import (
    DISCREPANCIES,
    InstrumentStatus,
    TradeDemand,
    TradeInstrument,
)

router = APIRouter(prefix="/trade", tags=["trade finance"])
Discrepancy = Literal[tuple(sorted(DISCREPANCIES))]  # type: ignore[valid-type]


class InstrumentOut(BaseModel):
    id: uuid.UUID
    instrument_number: str
    kind: str
    customer_number: str
    customer_name: str
    beneficiary_name: str
    beneficiary_country: str
    purpose: str
    amount: int
    currency: str
    margin_bps: int
    margin: int
    drawn: int
    expires_on: date
    status: str
    needs_committee: bool
    approved: bool
    committee_approved: bool
    screening_list: str | None
    created_at: datetime


class InstrumentRequest(BaseModel):
    kind: Literal["letter_of_credit", "guarantee"]
    customer_number: str = Field(min_length=4, max_length=20)
    account_number: str = Field(min_length=6, max_length=34)
    beneficiary_name: str = Field(min_length=2, max_length=140)
    beneficiary_country: str = Field(pattern=r"^[A-Z]{2}$")
    amount: int = Field(gt=0, description="Minor units of the account's currency")
    expires_on: date
    purpose: str = Field(default="Trade", max_length=140)


class DemandIn(BaseModel):
    amount: int = Field(gt=0)
    presented_on: date
    discrepancies: list[Discrepancy] = Field(default_factory=list, max_length=5)


class DemandOut(BaseModel):
    id: uuid.UUID
    demand_number: str
    instrument_id: uuid.UUID
    amount: int
    presented_on: date
    discrepancies: list[str]
    status: str
    decision_note: str | None
    decided_at: datetime | None


class Rejection(BaseModel):
    note: str = Field(min_length=3, max_length=200)


def _out(db, instruments: list[TradeInstrument]) -> list[InstrumentOut]:
    ids = {i.customer_id for i in instruments}
    customers = {
        c.id: c for c in db.execute(select(Customer).where(Customer.id.in_(ids))).scalars()
    } if ids else {}  # fmt: skip
    return [
        InstrumentOut(
            id=i.id,
            instrument_number=i.instrument_number,
            kind=i.kind,
            customer_number=customers[i.customer_id].customer_number,
            customer_name=customers[i.customer_id].name,
            beneficiary_name=i.beneficiary_name,
            beneficiary_country=i.beneficiary_country,
            purpose=i.purpose,
            amount=i.amount,
            currency=i.currency,
            margin_bps=i.margin_bps,
            margin=i.margin,
            drawn=i.drawn,
            expires_on=i.expires_on,
            status=i.status,
            needs_committee=service.needs_committee(i),
            approved=i.approved_by is not None,
            committee_approved=i.committee_approved_by is not None,
            screening_list=i.screening.get("list"),
            created_at=i.created_at,
        )  # fmt: skip
        for i in instruments
    ]


def _one(db, instrument: TradeInstrument) -> InstrumentOut:
    return _out(db, [instrument])[0]


@router.get("/instruments", response_model=Page[InstrumentOut], summary="Instruments")
def list_instruments(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.LOANS_READ),
    status_filter: Annotated[InstrumentStatus | None, Query(alias="status")] = None,
) -> Page[InstrumentOut]:
    query = select(TradeInstrument).order_by(
        TradeInstrument.created_at.desc(), TradeInstrument.instrument_number.desc()
    )
    if status_filter is not None:
        query = query.where(TradeInstrument.status == status_filter)
    items, total = paginate(db, query, page)
    return Page(items=_out(db, items), total=total, limit=page.limit, offset=page.offset)


@router.post(
    "/instruments", response_model=InstrumentOut, status_code=status.HTTP_201_CREATED,
    summary="Request a letter of credit or a guarantee (beneficiary screened)",
)  # fmt: skip
def request_instrument(
    body: InstrumentRequest, db: DbSession, actor: Authorized(Permission.ACCOUNTS_TRANSACT)
):
    customer = service.find_customer(db, body.customer_number)
    if customer is None:
        raise BusinessRuleViolation(f"No customer {body.customer_number}.")
    account = accounts.find_account(db, body.account_number)
    if account is None:
        raise BusinessRuleViolation(f"No account {body.account_number}.")
    instrument = service.request_instrument(
        db, customer=customer, account=account, kind=body.kind,
        beneficiary_name=body.beneficiary_name, beneficiary_country=body.beneficiary_country,
        amount=body.amount, expires_on=body.expires_on, purpose=body.purpose,
        requested_by=actor.id,
    )  # fmt: skip
    return _one(db, instrument)


@router.post(
    "/instruments/{instrument_id}/approve", response_model=InstrumentOut,
    summary="Credit approval; issued (margin taken) unless above US$1m",
)  # fmt: skip
def approve(instrument_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.LOANS_APPROVE)):
    instrument = service.get_instrument(db, instrument_id, for_update=True)
    return _one(db, service.approve_instrument(db, instrument, actor.id))


@router.post(
    "/instruments/{instrument_id}/committee", response_model=InstrumentOut,
    summary="Credit committee approval above US$1m; a third person",
)  # fmt: skip
def committee(
    instrument_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.LOANS_APPROVE_LARGE)
):
    instrument = service.get_instrument(db, instrument_id, for_update=True)
    return _one(db, service.committee_approve(db, instrument, actor.id))


@router.post(
    "/instruments/{instrument_id}/decline", response_model=InstrumentOut, summary="Decline"
)
def decline(instrument_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.LOANS_APPROVE)):
    instrument = service.get_instrument(db, instrument_id, for_update=True)
    return _one(db, service.decline_instrument(db, instrument, actor.id))


@router.post(
    "/instruments/{instrument_id}/expire", response_model=InstrumentOut,
    summary="Close after expiry and release the margin",
)  # fmt: skip
def expire(instrument_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.TRADE_MANAGE)):
    instrument = service.get_instrument(db, instrument_id)
    return _one(db, service.expire_instrument(db, instrument, actor.id))


@router.get(
    "/instruments/{instrument_id}/demands", response_model=list[DemandOut], summary="Demands"
)
def list_demands(instrument_id: uuid.UUID, db: DbSession, _: Authorized(Permission.LOANS_READ)):
    return db.execute(
        select(TradeDemand).where(TradeDemand.instrument_id == instrument_id)
        .order_by(TradeDemand.created_at.desc())
    ).scalars().all()  # fmt: skip


@router.post(
    "/instruments/{instrument_id}/demands", response_model=DemandOut,
    status_code=status.HTTP_201_CREATED,
    summary="Documents presented (letter of credit) or a claim (guarantee)",
)  # fmt: skip
def receive_demand(
    instrument_id: uuid.UUID, body: DemandIn, db: DbSession,
    actor: Authorized(Permission.ACCOUNTS_TRANSACT),
):  # fmt: skip
    instrument = service.get_instrument(db, instrument_id, for_update=True)
    return service.receive_demand(
        db, instrument, amount=body.amount, presented_on=body.presented_on,
        discrepancies=list(body.discrepancies), received_by=actor.id,
    )  # fmt: skip


@router.post(
    "/demands/{demand_id}/pay", response_model=DemandOut,
    summary="Pay the beneficiary (discrepancies waived by the applicant); not by the receiver",
)  # fmt: skip
def pay(demand_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.TRADE_MANAGE)):
    return service.pay_demand(db, service.get_demand(db, demand_id), actor.id)


@router.post("/demands/{demand_id}/reject", response_model=DemandOut, summary="Reject")
def reject(
    demand_id: uuid.UUID, body: Rejection, db: DbSession,
    actor: Authorized(Permission.TRADE_MANAGE),
):  # fmt: skip
    return service.reject_demand(db, service.get_demand(db, demand_id), actor.id, body.note)


@router.get("/summary/counts", summary="Counts for the trade finance page")
def summary(db: DbSession, _: Authorized(Permission.LOANS_READ)) -> dict:
    return service.summary(db)
