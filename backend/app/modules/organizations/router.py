import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from app.core.dependencies import DbSession
from app.core.idempotency import IdempotencyKey, run_idempotent
from app.core.pagination import Page, PageParamsDep
from app.core.permissions import Permission
from app.modules.identity.dependencies import Authorized
from app.modules.organizations import service
from app.modules.organizations.models import OrganizationStatus, OrganizationType
from app.modules.organizations.schemas import (
    OrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=Page[OrganizationOut], summary="List organizations")
def list_organizations(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.ORGANIZATIONS_READ),
    parent_id: Annotated[
        uuid.UUID | None, Query(description="Only direct children of this organization")
    ] = None,
    root_only: Annotated[bool, Query(description="Only the top of the hierarchy")] = False,
    organization_type: OrganizationType | None = None,
    country_id: uuid.UUID | None = None,
    status: OrganizationStatus | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[OrganizationOut]:
    items, total = service.list_organizations(
        db,
        page,
        parent_id=parent_id,
        root_only=root_only,
        organization_type=organization_type,
        country_id=country_id,
        status=status,
        q=q,
    )
    return Page(items=service.to_out(db, items), total=total, limit=page.limit, offset=page.offset)


@router.post(
    "",
    response_model=OrganizationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an organization",
)
def create_organization(
    body: OrganizationCreate,
    request: Request,
    db: DbSession,
    actor: Authorized(Permission.ORGANIZATIONS_MANAGE),
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
        operation=lambda: service.to_out(db, [service.create_organization(db, body, actor.id)])[0],
    )


@router.get("/{organization_id}", response_model=OrganizationOut, summary="Get an organization")
def get_organization(
    organization_id: uuid.UUID, db: DbSession, _: Authorized(Permission.ORGANIZATIONS_READ)
) -> OrganizationOut:
    return service.to_out(db, [service.get_organization(db, organization_id)])[0]


@router.get(
    "/{organization_id}/ancestors",
    response_model=list[OrganizationOut],
    summary="Path from the global bank to this organization",
)
def get_ancestors(
    organization_id: uuid.UUID, db: DbSession, _: Authorized(Permission.ORGANIZATIONS_READ)
) -> list[OrganizationOut]:
    return service.to_out(db, service.ancestors(db, service.get_organization(db, organization_id)))


@router.patch(
    "/{organization_id}", response_model=OrganizationOut, summary="Rename or (de)activate"
)
def update_organization(
    organization_id: uuid.UUID,
    body: OrganizationUpdate,
    db: DbSession,
    actor: Authorized(Permission.ORGANIZATIONS_MANAGE),
) -> OrganizationOut:
    organization = service.update_organization(
        db, service.get_organization(db, organization_id), body, actor.id
    )
    return service.to_out(db, [organization])[0]
