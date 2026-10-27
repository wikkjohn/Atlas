import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from app.core.dependencies import DbSession
from app.core.idempotency import IdempotencyKey, run_idempotent
from app.core.pagination import Page, PageParamsDep
from app.core.permissions import Permission
from app.modules.countries import service
from app.modules.countries.models import OperationalStatus, Region
from app.modules.countries.schemas import CountryCreate, CountryOut, CountryUpdate
from app.modules.identity.dependencies import Authorized

router = APIRouter(prefix="/countries", tags=["countries"])


@router.get("", response_model=Page[CountryOut], summary="List configured countries")
def list_countries(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.COUNTRIES_READ),
    region: Region | None = None,
    operational_status: OperationalStatus | None = None,
    q: Annotated[str | None, Query(max_length=100, description="Name or ISO code")] = None,
) -> Page[CountryOut]:
    items, total = service.list_countries(db, page, region=region, status=operational_status, q=q)
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
