from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.dependencies import DbSession
from app.core.errors import BusinessRuleViolation
from app.core.pagination import Page, PageParamsDep
from app.core.permissions import Permission
from app.modules.fx import service
from app.modules.fx.schemas import (
    DealOut,
    PositionsOut,
    QuoteIn,
    QuoteOut,
    RateOut,
    RatePoint,
    RevaluationIn,
    RevaluationOut,
)
from app.modules.identity.dependencies import Authorized

router = APIRouter(prefix="/fx", tags=["fx"])


def _today() -> date:
    return datetime.now(UTC).date()


@router.get("/rates", response_model=list[RateOut], summary="A day's rates (units per US dollar)")
def list_rates(
    db: DbSession,
    _: Authorized(Permission.PAYMENTS_READ),
    on: Annotated[date | None, Query(description="Default today")] = None,
) -> list[RateOut]:
    day = on or _today()
    found = service.rates_on(db, day)
    return [RateOut(currency=c, rate_date=day, units_per_usd=r) for c, r in sorted(found.items())]


@router.get(
    "/rates/{currency}",
    response_model=list[RatePoint],
    summary="One currency's daily rates between two dates (at most a year)",
)
def rate_history(
    currency: str,
    db: DbSession,
    _: Authorized(Permission.PAYMENTS_READ),
    start: Annotated[date, Query(alias="from")],
    end: Annotated[date, Query(alias="to")],
) -> list[RatePoint]:
    if end < start:
        raise BusinessRuleViolation("'to' is before 'from'.")
    return [
        RatePoint(rate_date=d, units_per_usd=r)
        for d, r in service.history(db, currency.upper(), start, end)
    ]


@router.post("/quote", response_model=QuoteOut, summary="Quote a conversion (stores nothing)")
def quote(body: QuoteIn, db: DbSession, _: Authorized(Permission.PAYMENTS_READ)) -> QuoteOut:
    terms = service.quote(
        db, body.sell_currency, body.buy_currency, body.sell_amount, body.rate_date or _today()
    )
    return QuoteOut(**terms)


@router.get("/deals", response_model=Page[DealOut], summary="Conversions, newest first")
def list_deals(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.LEDGER_READ),
    currency: Annotated[str | None, Query(pattern=r"^[A-Z]{3}$")] = None,
) -> Page[DealOut]:
    items, total = service.list_deals(db, page, currency)
    return Page(
        items=[DealOut.model_validate(d) for d in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/positions",
    response_model=PositionsOut,
    summary="Open currency positions valued in US dollars, and the unbooked FX result",
)
def positions(
    db: DbSession,
    _: Authorized(Permission.LEDGER_READ),
    as_of: Annotated[date | None, Query()] = None,
) -> PositionsOut:
    return PositionsOut(**service.positions(db, as_of or _today()))


@router.post(
    "/revaluations",
    response_model=RevaluationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Revalue the open positions and book the result",
)
def revalue(
    body: RevaluationIn, db: DbSession, actor: Authorized(Permission.FX_MANAGE)
) -> RevaluationOut:
    return RevaluationOut.model_validate(service.revalue(db, body.as_of or _today(), actor.id))


@router.get("/revaluations", response_model=Page[RevaluationOut], summary="Revaluation runs")
def list_revaluations(
    db: DbSession, page: PageParamsDep, _: Authorized(Permission.LEDGER_READ)
) -> Page[RevaluationOut]:
    items, total = service.list_revaluations(db, page)
    return Page(
        items=[RevaluationOut.model_validate(r) for r in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
