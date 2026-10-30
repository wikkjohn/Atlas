import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from app.core.dependencies import DbSession
from app.core.idempotency import IdempotencyKey, run_idempotent
from app.core.pagination import Page, PageParamsDep
from app.core.permissions import Permission
from app.modules.countries import service
from app.modules.countries.models import OperationalStatus, Region
from app.modules.countries.schemas import (
    BusinessDayOut,
    CalendarOut,
    CountryCreate,
    CountryOut,
    CountryUpdate,
    CurrencyOut,
    SampleOut,
    ValueCheckIn,
    ValueCheckOut,
)
from app.modules.identity.dependencies import Authorized

router = APIRouter(prefix="/countries", tags=["countries"])
currencies_router = APIRouter(prefix="/currencies", tags=["countries"])


@router.get("", response_model=Page[CountryOut], summary="List configured countries")
def list_countries(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.COUNTRIES_READ),
    region: Region | None = None,
    operational_status: OperationalStatus | None = None,
    q: Annotated[str | None, Query(max_length=100, description="Name or ISO code")] = None,
    currency: Annotated[str | None, Query(pattern=r"^[A-Za-z]{3}$")] = None,
) -> Page[CountryOut]:
    items, total = service.list_countries(
        db, page, region=region, status=operational_status, q=q, currency=currency
    )
    return Page(
        items=[CountryOut.model_validate(c) for c in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "", response_model=CountryOut, status_code=status.HTTP_201_CREATED, summary="Add a country"
)
def create_country(
    body: CountryCreate,
    request: Request,
    db: DbSession,
    actor: Authorized(Permission.COUNTRIES_MANAGE),
    idempotency_key: IdempotencyKey = None,
):
    return run_idempotent(
        db,
        key=idempotency_key,
        actor_id=actor.id,
        method="POST",
        path=request.url.path,
        payload=body,
        status_code=status.HTTP_201_CREATED,
        operation=lambda: CountryOut.model_validate(service.create_country(db, body, actor.id)),
    )


@router.get("/{country_id}", response_model=CountryOut, summary="Get a country")
def get_country(
    country_id: uuid.UUID, db: DbSession, _: Authorized(Permission.COUNTRIES_READ)
) -> CountryOut:
    return CountryOut.model_validate(service.get_country(db, country_id))


@router.patch("/{country_id}", response_model=CountryOut, summary="Update a country")
def update_country(
    country_id: uuid.UUID,
    body: CountryUpdate,
    db: DbSession,
    actor: Authorized(Permission.COUNTRIES_MANAGE),
) -> CountryOut:
    country = service.update_country(db, service.get_country(db, country_id), body, actor.id)
    return CountryOut.model_validate(country)


# --- Reference data (Phase 23) ---------------------------------------------------------------


@currencies_router.get("", response_model=list[CurrencyOut], summary="ISO 4217 currencies")
def list_currencies(db: DbSession, _: Authorized(Permission.COUNTRIES_READ)) -> list[CurrencyOut]:
    return [CurrencyOut.model_validate(c) for c in service.list_currencies(db)]


@router.get(
    "/{country_id}/calendar",
    response_model=CalendarOut,
    summary="A country's public holidays and business days in a year",
)
def country_calendar(
    country_id: uuid.UUID,
    db: DbSession,
    _: Authorized(Permission.COUNTRIES_READ),
    year: Annotated[int, Query(ge=1980, le=2099)],
) -> CalendarOut:
    return CalendarOut.model_validate(
        service.calendar_of(service.get_country(db, country_id), year)
    )


@router.get(
    "/{country_id}/business-day",
    response_model=BusinessDayOut,
    summary="Whether a date is a business day in a country, and the next one",
)
def country_business_day(
    country_id: uuid.UUID,
    db: DbSession,
    _: Authorized(Permission.COUNTRIES_READ),
    on: Annotated[date, Query(description="YYYY-MM-DD")],
) -> BusinessDayOut:
    return BusinessDayOut.model_validate(
        service.business_day(service.get_country(db, country_id), on)
    )


@router.post(
    "/{country_id}/check",
    response_model=ValueCheckOut,
    summary="Check a document number or postal code against the country's formats",
)
def check_country_value(
    country_id: uuid.UUID,
    body: ValueCheckIn,
    db: DbSession,
    _: Authorized(Permission.COUNTRIES_READ),
) -> ValueCheckOut:
    country = service.get_country(db, country_id)
    return ValueCheckOut.model_validate(service.check_value(country, body.kind, body.value))


@router.get(
    "/{country_id}/samples",
    response_model=list[SampleOut],
    summary="Synthetic document numbers, postal codes and addresses in the country's formats",
)
def country_samples(
    country_id: uuid.UUID,
    db: DbSession,
    _: Authorized(Permission.COUNTRIES_READ),
    count: Annotated[int, Query(ge=1, le=20)] = 3,
    seed: Annotated[int, Query(ge=0)] = 0,
) -> list[SampleOut]:
    country = service.get_country(db, country_id)
    return [SampleOut.model_validate(s) for s in service.samples(country, count, seed)]
