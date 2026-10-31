"""Treasury API (Phase 39)."""

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.errors import BusinessRuleViolation
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
from app.modules.identity.dependencies import Authorized
from app.modules.treasury import service
from app.modules.treasury.models import (
    DealStatus,
    TreasuryCounterparty,
    TreasuryDeal,
    TreasuryFxTrade,
)

router = APIRouter(prefix="/treasury", tags=["treasury"])


def _today() -> date:
    return datetime.now(UTC).date()


class CounterpartyOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    country_code: str
    rating: str
    limit_usd: int
    exposure_usd: int
    investment_grade: bool


class DealOut(BaseModel):
    id: uuid.UUID
    deal_number: str
    kind: str
    counterparty_code: str
    counterparty_name: str
    currency: str
    principal: int
    rate_bps: int
    day_basis: int
    value_date: date
    maturity_date: date
    interest: int
    status: str
    created_at: datetime


class FxTradeOut(BaseModel):
    id: uuid.UUID
    trade_number: str
    counterparty_code: str
    sell_currency: str
    sell_amount: int
    buy_currency: str
    buy_amount: int
    mid_rate: str
    trade_date: date
    status: str
    created_at: datetime


def _counterparty_out(db, c: TreasuryCounterparty, day: date) -> CounterpartyOut:
    return CounterpartyOut(
        id=c.id, code=c.code, name=c.name, country_code=c.country_code, rating=c.rating,
        limit_usd=c.limit_usd, exposure_usd=service.exposure_usd(db, c, day),
        investment_grade=c.rating in service.INVESTMENT_GRADE,
    )  # fmt: skip


def _counterparties(db) -> dict[uuid.UUID, TreasuryCounterparty]:
    return {c.id: c for c in db.execute(select(TreasuryCounterparty)).scalars()}


def _deal_out(d: TreasuryDeal, parties: dict) -> DealOut:
    c = parties[d.counterparty_id]
    return DealOut(
        id=d.id, deal_number=d.deal_number, kind=d.kind, counterparty_code=c.code,
        counterparty_name=c.name, currency=d.currency, principal=d.principal,
        rate_bps=d.rate_bps, day_basis=d.day_basis, value_date=d.value_date,
        maturity_date=d.maturity_date, interest=d.interest, status=d.status,
        created_at=d.created_at,
    )  # fmt: skip


def _trade_out(t: TreasuryFxTrade, parties: dict) -> FxTradeOut:
    return FxTradeOut(
        id=t.id, trade_number=t.trade_number, counterparty_code=parties[t.counterparty_id].code,
        sell_currency=t.sell_currency, sell_amount=t.sell_amount, buy_currency=t.buy_currency,
        buy_amount=t.buy_amount, mid_rate=t.mid_rate, trade_date=t.trade_date, status=t.status,
        created_at=t.created_at,
    )  # fmt: skip


def _counterparty(db, code: str) -> TreasuryCounterparty:
    found = service.find_counterparty(db, code)
    if found is None:
        raise BusinessRuleViolation(f"No counterparty {code}.")
    return found


# --- Counterparties --------------------------------------------------------------------------


@router.get("/counterparties", response_model=list[CounterpartyOut], summary="Counterparties")
def counterparties(db: DbSession, _: Authorized(Permission.PAYMENTS_READ)):
    rows = db.execute(select(TreasuryCounterparty).order_by(TreasuryCounterparty.code)).scalars()
    return [_counterparty_out(db, c, _today()) for c in rows]


class LimitIn(BaseModel):
    limit_usd: int = Field(ge=0, le=1_000_000_000)


@router.put(
    "/counterparties/{code}/limit", response_model=CounterpartyOut,
    summary="Set a counterparty's placement limit (whole US dollars)",
)  # fmt: skip
def set_limit(code: str, body: LimitIn, db: DbSession,
              actor: Authorized(Permission.TREASURY_LIMITS)):  # fmt: skip
    counterparty = _counterparty(db, code)
    service.set_counterparty_limit(db, counterparty, body.limit_usd, actor.id)
    return _counterparty_out(db, counterparty, _today())


# --- Money-market deals ----------------------------------------------------------------------


class DealIn(BaseModel):
    kind: Literal["placement", "borrowing"]
    counterparty_code: str = Field(min_length=1, max_length=20)
    currency: str = Field(min_length=3, max_length=3)
    principal: int = Field(gt=0)
    rate_bps: int = Field(ge=0, le=5000)
    tenor_days: int = Field(ge=1, le=365)


@router.get("/deals", response_model=Page[DealOut], summary="Money-market deals")
def list_deals(
    db: DbSession, page: PageParamsDep, _: Authorized(Permission.PAYMENTS_READ),
    status_filter: Annotated[DealStatus | None, Query(alias="status")] = None,
) -> Page[DealOut]:  # fmt: skip
    query = select(TreasuryDeal).order_by(TreasuryDeal.created_at.desc(),
                                          TreasuryDeal.deal_number.desc())  # fmt: skip
    if status_filter is not None:
        query = query.where(TreasuryDeal.status == status_filter)
    items, total = paginate(db, query, page)
    parties = _counterparties(db)
    return Page(items=[_deal_out(d, parties) for d in items], total=total, limit=page.limit,
                offset=page.offset)  # fmt: skip


@router.post("/deals", response_model=DealOut, status_code=status.HTTP_201_CREATED,
             summary="Book a placement or a borrowing, value today")  # fmt: skip
def book_deal(body: DealIn, db: DbSession, actor: Authorized(Permission.TREASURY_DEAL)):
    deal = service.book_deal(
        db, counterparty=_counterparty(db, body.counterparty_code), kind=body.kind,
        currency=body.currency, principal=body.principal, rate_bps=body.rate_bps,
        tenor_days=body.tenor_days, booked_by=actor.id,
    )  # fmt: skip
    return _deal_out(deal, _counterparties(db))


@router.post("/deals/{deal_id}/confirm", response_model=DealOut,
             summary="Back office confirms and settles; not the dealer")  # fmt: skip
def confirm_deal(deal_id: uuid.UUID, db: DbSession,
                 actor: Authorized(Permission.TREASURY_CONFIRM)):  # fmt: skip
    deal = service.confirm_deal(db, service.get_deal(db, deal_id), actor.id)
    return _deal_out(deal, _counterparties(db))


@router.post("/deals/{deal_id}/cancel", response_model=DealOut, summary="Cancel a booked deal")
def cancel_deal(deal_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.TREASURY_DEAL)):
    deal = service.cancel_deal(db, service.get_deal(db, deal_id), actor.id)
    return _deal_out(deal, _counterparties(db))


@router.post("/deals/{deal_id}/mature", response_model=DealOut,
             summary="Settle principal and interest at maturity; not the dealer")  # fmt: skip
def mature_deal(deal_id: uuid.UUID, db: DbSession,
                actor: Authorized(Permission.TREASURY_CONFIRM)):  # fmt: skip
    deal = service.mature_deal(db, service.get_deal(db, deal_id), actor.id)
    return _deal_out(deal, _counterparties(db))


# --- Liquidity and the FX desk ---------------------------------------------------------------


@router.get("/liquidity", summary="30-day liquidity coverage by currency")
def liquidity(db: DbSession, _: Authorized(Permission.PAYMENTS_READ)) -> dict:
    return service.liquidity(db, _today())


@router.get("/fx-desk", summary="Open currency positions against their limits")
def fx_desk(db: DbSession, _: Authorized(Permission.PAYMENTS_READ)) -> dict:
    return service.fx_desk(db, _today())


@router.put("/fx-limits/{currency}", summary="Set a currency's net open position limit")
def set_fx_limit(currency: str, body: LimitIn, db: DbSession,
                 actor: Authorized(Permission.TREASURY_LIMITS)) -> dict:  # fmt: skip
    row = service.set_fx_limit(db, currency, body.limit_usd, actor.id)
    return {"currency": row.currency, "limit_usd": row.limit_usd}


class FxTradeIn(BaseModel):
    counterparty_code: str = Field(min_length=1, max_length=20)
    sell_currency: str = Field(min_length=3, max_length=3)
    buy_currency: str = Field(min_length=3, max_length=3)
    sell_amount: int = Field(gt=0)


@router.get("/fx-trades", response_model=Page[FxTradeOut], summary="FX desk trades")
def list_fx_trades(db: DbSession, page: PageParamsDep, _: Authorized(Permission.PAYMENTS_READ)):
    query = select(TreasuryFxTrade).order_by(TreasuryFxTrade.created_at.desc(),
                                             TreasuryFxTrade.trade_number.desc())  # fmt: skip
    items, total = paginate(db, query, page)
    parties = _counterparties(db)
    return Page(items=[_trade_out(t, parties) for t in items], total=total, limit=page.limit,
                offset=page.offset)  # fmt: skip


@router.post("/fx-trades", response_model=FxTradeOut, status_code=status.HTTP_201_CREATED,
             summary="Book a spot trade that reduces a long position, at the mid rate")  # fmt: skip
def book_fx_trade(body: FxTradeIn, db: DbSession, actor: Authorized(Permission.TREASURY_DEAL)):
    trade = service.book_fx_trade(
        db, counterparty=_counterparty(db, body.counterparty_code),
        sell_currency=body.sell_currency, buy_currency=body.buy_currency,
        sell_amount=body.sell_amount, booked_by=actor.id,
    )  # fmt: skip
    return _trade_out(trade, _counterparties(db))


@router.post("/fx-trades/{trade_id}/confirm", response_model=FxTradeOut,
             summary="Back office confirms and settles both legs; not the dealer")  # fmt: skip
def confirm_fx_trade(trade_id: uuid.UUID, db: DbSession,
                     actor: Authorized(Permission.TREASURY_CONFIRM)):  # fmt: skip
    trade = service.confirm_fx_trade(db, service.get_fx_trade(db, trade_id), actor.id)
    return _trade_out(trade, _counterparties(db))


@router.post("/fx-trades/{trade_id}/cancel", response_model=FxTradeOut, summary="Cancel")
def cancel_fx_trade(trade_id: uuid.UUID, db: DbSession,
                    actor: Authorized(Permission.TREASURY_DEAL)):  # fmt: skip
    trade = service.cancel_fx_trade(db, service.get_fx_trade(db, trade_id), actor.id)
    return _trade_out(trade, _counterparties(db))


@router.get("/summary/counts", summary="Counts for the treasury page")
def summary(db: DbSession, _: Authorized(Permission.PAYMENTS_READ)) -> dict:
    return service.summary(db)
