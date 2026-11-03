"""Information Security's access grants (Phase 74)."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.dependencies import DbSession
from app.core.permissions import Permission
from app.modules.access import service
from app.modules.access.models import AccessGrant
from app.modules.employees.models import Employee
from app.modules.identity.dependencies import Authorized

router = APIRouter(prefix="/access", tags=["access"])


class GrantOut(BaseModel):
    id: uuid.UUID
    grant_number: str
    employee_id: uuid.UUID
    employee_number: str | None
    employee_name: str | None
    profile: str
    status: str
    requested_at: datetime
    granted_at: datetime | None
    revoked_at: datetime | None
    revoke_reason: str | None


def _out(db, grant: AccessGrant) -> GrantOut:
    employee = db.get(Employee, grant.employee_id)
    return GrantOut(
        id=grant.id,
        grant_number=grant.grant_number,
        employee_id=grant.employee_id,
        employee_number=employee.employee_number if employee else None,
        employee_name=f"{employee.first_name} {employee.last_name}" if employee else None,
        profile=grant.profile,
        status=grant.status,
        requested_at=grant.requested_at,
        granted_at=grant.granted_at,
        revoked_at=grant.revoked_at,
        revoke_reason=grant.revoke_reason,
    )


@router.get("/grants", response_model=list[GrantOut], summary="Access grants, newest first")
def list_grants(
    db: DbSession,
    _: Authorized(Permission.EMPLOYEES_READ),
    status: Annotated[str | None, Query(pattern="^(requested|granted|revoked)$")] = None,
) -> list[GrantOut]:
    return [_out(db, g) for g in service.list_grants(db, status)]


@router.get("/grants/summary", summary="Access grants by status")
def grants_summary(db: DbSession, _: Authorized(Permission.EMPLOYEES_READ)) -> dict[str, Any]:
    return service.counts(db)


@router.post(
    "/grants/{grant_id}/grant",
    response_model=GrantOut,
    summary="Grant requested access (publishes access.granted)",
)
def grant(
    grant_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.USERS_MANAGE)
) -> GrantOut:
    return _out(db, service.grant_access(db, service.get_grant(db, grant_id), actor.id))
