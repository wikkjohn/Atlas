"""IT operations API (Phase 59): applications, incidents and change requests."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
from app.modules.identity.dependencies import Authorized
from app.modules.itops import service
from app.modules.itops.models import Application, ChangeRequest, Incident
from app.modules.organizations.models import Organization

router = APIRouter(prefix="/itops", tags=["itops"])
READ, MANAGE = Permission.ITOPS_READ, Permission.ITOPS_MANAGE
APPROVE, MAJOR = Permission.ITOPS_APPROVE, Permission.ITOPS_APPROVE_MAJOR


class ApplicationIn(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    description: str = Field(default="", max_length=300)
    department_id: uuid.UUID
    tier: int = Field(ge=1, le=3)


class ApplicationOut(BaseModel):
    id: uuid.UUID
    application_number: str
    name: str
    description: str
    department: str
    tier: int
    status: str
    open_incidents: int


class IncidentIn(BaseModel):
    application_number: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=5, max_length=200)
    impact: str = Field(pattern=r"^(high|medium|low)$")
    urgency: str = Field(pattern=r"^(high|medium|low)$")


class ResolveIn(BaseModel):
    resolution: str = Field(min_length=10, max_length=2000)
    change_number: str | None = Field(default=None, max_length=20)


class CloseIn(BaseModel):
    review: str | None = Field(default=None, max_length=4000)


class IncidentOut(BaseModel):
    id: uuid.UUID
    incident_number: str
    application_number: str
    application: str
    tier: int
    title: str
    impact: str
    urgency: str
    priority: int
    status: str
    respond_by: datetime
    resolve_by: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    response_breached: bool
    resolution_breached: bool
    resolution: str | None
    review: str | None
    change_number: str | None
    created_at: datetime


class ChangeIn(BaseModel):
    application_number: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=5, max_length=200)
    kind: str = Field(pattern=r"^(standard|normal|emergency)$")
    backout_plan: str = Field(default="", max_length=2000)
    planned_start: datetime
    planned_end: datetime
    incident_number: str | None = Field(default=None, max_length=20)


class ImplementIn(BaseModel):
    success: bool


class ChangeOut(BaseModel):
    id: uuid.UUID
    change_number: str
    application_number: str
    application: str
    tier: int
    title: str
    kind: str
    risk: str
    needs_cab: bool
    planned_start: datetime
    planned_end: datetime
    incident_number: str | None
    status: str
    created_at: datetime


def _app_out(db, a: Application) -> ApplicationOut:
    from sqlalchemy import func

    from app.modules.itops.models import IncidentStatus

    open_count = db.execute(
        select(func.count()).select_from(Incident).where(
            Incident.application_id == a.id,
            Incident.status.in_([IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED]))
    ).scalar_one()  # fmt: skip
    return ApplicationOut(
        id=a.id, application_number=a.application_number, name=a.name,
        description=a.description, department=db.get(Organization, a.department_id).name,
        tier=a.tier, status=a.status, open_incidents=open_count,
    )  # fmt: skip


def _incident_out(db, i: Incident) -> IncidentOut:
    app = db.get(Application, i.application_id)
    change = db.get(ChangeRequest, i.change_id) if i.change_id else None
    return IncidentOut(
        id=i.id, incident_number=i.incident_number, application_number=app.application_number,
        application=app.name, tier=app.tier, title=i.title, impact=i.impact,
        urgency=i.urgency, priority=i.priority, status=i.status, respond_by=i.respond_by,
        resolve_by=i.resolve_by, acknowledged_at=i.acknowledged_at, resolved_at=i.resolved_at,
        response_breached=i.response_breached, resolution_breached=i.resolution_breached,
        resolution=i.resolution, review=i.review,
        change_number=change.change_number if change else None, created_at=i.created_at,
    )  # fmt: skip


def _change_out(db, c: ChangeRequest) -> ChangeOut:
    app = db.get(Application, c.application_id)
    incident = db.get(Incident, c.incident_id) if c.incident_id else None
    return ChangeOut(
        id=c.id, change_number=c.change_number, application_number=app.application_number,
        application=app.name, tier=app.tier, title=c.title, kind=c.kind, risk=c.risk,
        needs_cab=service.needs_cab(db, c), planned_start=c.planned_start,
        planned_end=c.planned_end,
        incident_number=incident.incident_number if incident else None, status=c.status,
        created_at=c.created_at,
    )  # fmt: skip


def _page(db, query, page, out):
    items, total = paginate(db, query, page)
    return Page(items=[out(db, r) for r in items], total=total, limit=page.limit,
                offset=page.offset)  # fmt: skip


# --- Applications ------------------------------------------------------------------------------


@router.get("/applications", response_model=list[ApplicationOut],
            summary="The application catalogue, most critical first")  # fmt: skip
def list_applications(db: DbSession, _: Authorized(READ)):
    rows = db.execute(
        select(Application).order_by(Application.tier, Application.name)
    ).scalars()  # fmt: skip
    return [_app_out(db, a) for a in rows]


@router.post("/applications", response_model=ApplicationOut,
             status_code=status.HTTP_201_CREATED)  # fmt: skip
def register_application(body: ApplicationIn, db: DbSession, user: Authorized(MAJOR)):
    app = service.register_application(db, name=body.name, description=body.description,
                                       department_id=body.department_id, tier=body.tier,
                                       actor_id=user.id)  # fmt: skip
    return _app_out(db, app)


# --- Incidents ---------------------------------------------------------------------------------


@router.get("/incidents", response_model=Page[IncidentOut], summary="Incidents, newest first")
def list_incidents(db: DbSession, page: PageParamsDep, _: Authorized(READ),
                   status_: str | None = Query(default=None, alias="status")):  # fmt: skip
    query = select(Incident).order_by(Incident.created_at.desc(),
                                      Incident.incident_number.desc())  # fmt: skip
    if status_:
        query = query.where(Incident.status == status_)
    return _page(db, query, page, _incident_out)


@router.post("/incidents", response_model=IncidentOut, status_code=status.HTTP_201_CREATED,
             summary="Report an incident (prioritised from impact and urgency)")  # fmt: skip
def open_incident(body: IncidentIn, db: DbSession, user: Authorized(MANAGE)):
    app = service.find_application(db, body.application_number)
    return _incident_out(db, service.open_incident(db, app, body.title, body.impact,
                                                   body.urgency, user.id))  # fmt: skip


@router.post("/incidents/{incident_id}/acknowledge", response_model=IncidentOut)
def acknowledge(incident_id: uuid.UUID, db: DbSession, user: Authorized(MANAGE)):
    incident = service.get_incident(db, incident_id)
    return _incident_out(db, service.acknowledge(db, incident, user.id))


@router.post("/incidents/{incident_id}/resolve", response_model=IncidentOut)
def resolve(incident_id: uuid.UUID, body: ResolveIn, db: DbSession, user: Authorized(MANAGE)):
    incident = service.get_incident(db, incident_id)
    change = service.find_change(db, body.change_number) if body.change_number else None
    return _incident_out(db, service.resolve(db, incident, body.resolution, user.id,
                                             change=change))  # fmt: skip


@router.post("/incidents/{incident_id}/close", response_model=IncidentOut,
             summary="Close a resolved incident (a P1 with a post-incident review)")  # fmt: skip
def close(incident_id: uuid.UUID, body: CloseIn, db: DbSession, user: Authorized(APPROVE)):
    incident = service.get_incident(db, incident_id)
    return _incident_out(db, service.close(db, incident, user.id, body.review))


@router.post("/incidents/sweep", summary="Mark incidents past their targets")
def sweep(db: DbSession, _: Authorized(MANAGE)) -> dict:
    return service.sla_sweep(db)


# --- Changes -----------------------------------------------------------------------------------


@router.get("/changes", response_model=Page[ChangeOut], summary="Changes, newest first")
def list_changes(db: DbSession, page: PageParamsDep, _: Authorized(READ),
                 status_: str | None = Query(default=None, alias="status")):  # fmt: skip
    query = select(ChangeRequest).order_by(ChangeRequest.created_at.desc(),
                                           ChangeRequest.change_number.desc())  # fmt: skip
    if status_:
        query = query.where(ChangeRequest.status == status_)
    return _page(db, query, page, _change_out)


@router.post("/changes", response_model=ChangeOut, status_code=status.HTTP_201_CREATED,
             summary="Raise a change (risk-rated; standard changes are pre-approved)")  # fmt: skip
def raise_change(body: ChangeIn, db: DbSession, user: Authorized(MANAGE)):
    app = service.find_application(db, body.application_number)
    incident = service.find_incident(db, body.incident_number) if body.incident_number else None
    change = service.raise_change(
        db, app, title=body.title, kind=body.kind, backout_plan=body.backout_plan,
        planned_start=body.planned_start, planned_end=body.planned_end,
        requested_by=user.id, incident=incident,
    )  # fmt: skip
    return _change_out(db, change)


@router.post("/changes/{change_id}/approve", response_model=ChangeOut)
def approve_change(change_id: uuid.UUID, db: DbSession, user: Authorized(APPROVE)):
    change = service.get_change(db, change_id)
    return _change_out(db, service.decide_change(db, change, user.id, True, user.can(MAJOR)))


@router.post("/changes/{change_id}/reject", response_model=ChangeOut)
def reject_change(change_id: uuid.UUID, db: DbSession, user: Authorized(APPROVE)):
    change = service.get_change(db, change_id)
    return _change_out(db, service.decide_change(db, change, user.id, False))


@router.post("/changes/{change_id}/implement", response_model=ChangeOut,
             summary="Record the change as implemented or failed (a failure opens an "
                     "incident)")  # fmt: skip
def implement(change_id: uuid.UUID, body: ImplementIn, db: DbSession, user: Authorized(MANAGE)):
    change, _ = service.implement(db, service.get_change(db, change_id), user.id, body.success)
    return _change_out(db, change)


@router.get("/departments", summary="Active departments an application can belong to")
def departments(db: DbSession, _: Authorized(READ)) -> list[dict]:
    from app.modules.hr import service as hr

    return hr.departments(db)


@router.get("/summary/counts", summary="Counts for the IT operations page")
def summary(db: DbSession, _: Authorized(READ)) -> dict:
    return service.summary(db)
