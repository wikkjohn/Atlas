import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import object_session

from app.core.dependencies import DbSession
from app.core.errors import NotFoundError
from app.core.idempotency import IdempotencyKey, run_idempotent
from app.core.pagination import Page, PageParamsDep
from app.core.permissions import Permission
from app.modules.employees import service
from app.modules.employees.models import EmploymentStatus
from app.modules.employees.schemas import EmployeeCreate, EmployeeOut, EmployeeUpdate
from app.modules.identity import scopes
from app.modules.identity.dependencies import Authorized
from app.modules.identity.service import AuthenticatedUser

router = APIRouter(prefix="/employees", tags=["employees"])


def _out(user: AuthenticatedUser):
    can_see_pay = user.can(Permission.EMPLOYEES_READ_COMPENSATION)
    return lambda employee: service.to_out(employee, include_compensation=can_see_pay)


def _scoped(db, user: AuthenticatedUser, employee_id: uuid.UUID):
    """The employee, if within the caller's countries and departments (Phase 84); else 404."""
    employee = service.get_employee(db, employee_id)
    if not service.in_scope(user.scope, employee):
        raise NotFoundError("Employee not found.")
    return employee


def _hired_in_scope(actor: AuthenticatedUser, employee):
    db = object_session(employee)
    db.flush()
    db.refresh(employee)
    scopes.require_in_scope(actor.scope, country=employee.country.iso_country_code,
                            department=employee.department.name)  # fmt: skip
    return employee


@router.get("", response_model=Page[EmployeeOut], summary="List employees")
def list_employees(
    db: DbSession,
    page: PageParamsDep,
    user: Authorized(Permission.EMPLOYEES_READ),
    q: Annotated[
        str | None, Query(max_length=100, description="Name, email, number or job title")
    ] = None,
    organization_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    country_id: uuid.UUID | None = None,
    manager_id: uuid.UUID | None = None,
    employment_status: EmploymentStatus | None = None,
) -> Page[EmployeeOut]:
    items, total = service.list_employees(
        db,
        page,
        q=q,
        organization_id=organization_id,
        department_id=department_id,
        country_id=country_id,
        manager_id=manager_id,
        employment_status=employment_status,
        scope=user.scope,
    )
    out = _out(user)
    return Page(items=[out(e) for e in items], total=total, limit=page.limit, offset=page.offset)


@router.post("", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED, summary="Hire")
def create_employee(
    body: EmployeeCreate,
    request: Request,
    db: DbSession,
    actor: Authorized(Permission.EMPLOYEES_MANAGE),
    idempotency_key: IdempotencyKey = None,
):
    out = _out(actor)
    return run_idempotent(
        db,
        key=idempotency_key,
        actor_id=actor.id,
        method="POST",
        path=request.url.path,
        payload=body,
        status_code=status.HTTP_201_CREATED,
        operation=lambda: out(_hired_in_scope(actor, service.create_employee(db, body, actor.id))),
    )


class WorkforceIn(BaseModel):
    count: int = Field(default=150_000, ge=1, le=250_000)
    seed: int = Field(default=2030, ge=0)


@router.post("/workforce/generate", summary="Generate the bank's workforce (seeded, idempotent)")
def generate_workforce(body: WorkforceIn, db: DbSession,
                       actor: Authorized(Permission.EMPLOYEES_MANAGE)) -> dict:  # fmt: skip
    from app.modules.employees import workforce

    return workforce.generate_workforce(db, body.count, body.seed, actor.id)


@router.get("/workforce/summary", summary="The workforce by country, department, grade, role")
def workforce_summary(db: DbSession, _: Authorized(Permission.EMPLOYEES_READ)) -> dict:
    from app.modules.employees import workforce

    return workforce.summary(db)


@router.get("/{employee_id}", response_model=EmployeeOut, summary="Get an employee")
def get_employee(
    employee_id: uuid.UUID, db: DbSession, user: Authorized(Permission.EMPLOYEES_READ)
) -> EmployeeOut:
    return _out(user)(_scoped(db, user, employee_id))


@router.get(
    "/{employee_id}/direct-reports",
    response_model=list[EmployeeOut],
    summary="Employees managed directly by this employee",
)
def get_direct_reports(
    employee_id: uuid.UUID, db: DbSession, user: Authorized(Permission.EMPLOYEES_READ)
) -> list[EmployeeOut]:
    out = _out(user)
    reports = service.direct_reports(db, _scoped(db, user, employee_id))
    return [out(e) for e in reports if service.in_scope(user.scope, e)]


@router.get(
    "/{employee_id}/reporting-chain",
    response_model=list[EmployeeOut],
    summary="Managers from the direct manager upwards",
)
def get_reporting_chain(
    employee_id: uuid.UUID, db: DbSession, user: Authorized(Permission.EMPLOYEES_READ)
) -> list[EmployeeOut]:
    out = _out(user)
    chain = service.reporting_chain(db, _scoped(db, user, employee_id))
    return [out(e) for e in chain if service.in_scope(user.scope, e)]


@router.patch("/{employee_id}", response_model=EmployeeOut, summary="Update an employee")
def update_employee(
    employee_id: uuid.UUID,
    body: EmployeeUpdate,
    db: DbSession,
    actor: Authorized(Permission.EMPLOYEES_MANAGE),
) -> EmployeeOut:
    employee = service.update_employee(db, _scoped(db, actor, employee_id), body, actor.id)
    return _out(actor)(_hired_in_scope(actor, employee))  # a move out of scope is refused
