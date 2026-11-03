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
    owner: str | None
    technology: str
    hosting: str
    vendor: str | None
    generated_from: str | None


class ProfileIn(BaseModel):
    owner_username: str | None = Field(default=None, max_length=100)
    technology: str = Field(min_length=2, max_length=40)
    hosting: str = Field(pattern=r"^(on_premise|private_cloud|public_cloud|saas)$")
    vendor: str | None = Field(default=None, max_length=100)


class DependencyIn(BaseModel):
    depends_on: str = Field(min_length=1, max_length=20, description="Application number")
    kind: str = Field(pattern=r"^(data|api|batch|auth)$")


class EstateIn(BaseModel):
    count: int = Field(ge=1, le=10_000)
    seed: int = Field(ge=0, le=2**31 - 1)


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


def _open_incidents(db, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    from sqlalchemy import func

    from app.modules.itops.models import IncidentStatus

    if not ids:
        return {}
    rows = db.execute(
        select(Incident.application_id, func.count()).where(
            Incident.application_id.in_(ids),
            Incident.status.in_([IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED]))
        .group_by(Incident.application_id)).all()  # fmt: skip
    return {app_id: count for app_id, count in rows}


def _app_out(db, a: Application, open_count: int | None = None) -> ApplicationOut:
    from app.modules.identity.models import User

    if open_count is None:
        open_count = _open_incidents(db, [a.id]).get(a.id, 0)
    owner = db.get(User, a.owner_id) if a.owner_id else None
    return ApplicationOut(
        id=a.id, application_number=a.application_number, name=a.name,
        description=a.description, department=db.get(Organization, a.department_id).name,
        tier=a.tier, status=a.status, open_incidents=open_count,
        owner=owner.username if owner else None, technology=a.technology, hosting=a.hosting,
        vendor=a.vendor, generated_from=a.generated_from,
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


@router.get("/applications", response_model=Page[ApplicationOut],
            summary="The application registry, most critical first")  # fmt: skip
def list_applications(db: DbSession, page: PageParamsDep, _: Authorized(READ),
                      q: str | None = Query(default=None, max_length=100),
                      tier: int | None = Query(default=None, ge=1, le=3),
                      technology: str | None = Query(default=None, max_length=40),
                      generated: bool | None = None):  # fmt: skip
    query = select(Application).order_by(Application.tier, Application.name)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(Application.name.ilike(like)
                            | Application.application_number.ilike(like))  # fmt: skip
    if tier:
        query = query.where(Application.tier == tier)
    if technology:
        query = query.where(Application.technology == technology)
    if generated is not None:
        query = query.where(Application.generated_from.is_not(None) if generated
                            else Application.generated_from.is_(None))  # fmt: skip
    items, total = paginate(db, query, page)
    counts = _open_incidents(db, [a.id for a in items])
    return Page(items=[_app_out(db, a, counts.get(a.id, 0)) for a in items], total=total,
                limit=page.limit, offset=page.offset)  # fmt: skip


@router.get("/applications/{application_id}", summary="An application with what it relies on, "
            "what relies on it, and what stops if it stops")  # fmt: skip
def application_detail(application_id: uuid.UUID, db: DbSession, _: Authorized(READ)) -> dict:
    from app.modules.itops import estate

    app = service.get_application(db, application_id)

    def edge(dependency, other) -> dict:
        return {"id": str(dependency.id), "kind": dependency.kind,
                "application_number": other.application_number, "name": other.name,
                "tier": other.tier, "application_id": str(other.id)}  # fmt: skip

    return {
        "application": _app_out(db, app).model_dump(mode="json"),
        "dependencies": [edge(d, o) for d, o in estate.dependencies(db, app)],
        "dependents": [edge(d, o) for d, o in estate.dependents(db, app)],
        "impact": estate.impact(db, app),
    }


@router.put("/applications/{application_id}/profile", response_model=ApplicationOut,
            summary="Record the owner, technology, hosting and vendor")  # fmt: skip
def set_profile(application_id: uuid.UUID, body: ProfileIn, db: DbSession,
                user: Authorized(MAJOR)):  # fmt: skip
    from app.modules.itops import estate

    app = estate.set_profile(db, service.get_application(db, application_id),
                             owner_username=body.owner_username, technology=body.technology,
                             hosting=body.hosting, vendor=body.vendor,
                             actor_id=user.id)  # fmt: skip
    return _app_out(db, app)


@router.post("/applications/{application_id}/dependencies", status_code=status.HTTP_201_CREATED,
             summary="Record that the application relies on another (never a cycle)")  # fmt: skip
def add_dependency(application_id: uuid.UUID, body: DependencyIn, db: DbSession,
                   user: Authorized(MAJOR)) -> dict:  # fmt: skip
    from app.modules.itops import estate

    app = service.get_application(db, application_id)
    dependency = estate.add_dependency(db, app, service.find_application(db, body.depends_on),
                                       body.kind, user.id)  # fmt: skip
    return {"id": str(dependency.id), "kind": dependency.kind}


@router.delete("/applications/{application_id}/dependencies/{dependency_id}",
               status_code=status.HTTP_204_NO_CONTENT)  # fmt: skip
def remove_dependency(application_id: uuid.UUID, dependency_id: uuid.UUID, db: DbSession,
                      user: Authorized(MAJOR)) -> None:  # fmt: skip
    from app.modules.itops import estate

    estate.remove_dependency(db, dependency_id, user.id)


@router.post("/estate/generate", summary="Generate the simulated application estate (seeded)")
def generate_estate(body: EstateIn, db: DbSession, user: Authorized(MAJOR)) -> dict:
    from app.modules.itops import estate

    return estate.generate_estate(db, body.count, body.seed, user.id)


@router.get("/estate/summary", summary="The estate by tier, technology and hosting")
def estate_summary(db: DbSession, _: Authorized(READ)) -> dict:
    from app.modules.itops import estate

    return estate.summary(db)


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


# --- Simulated applications and outages (Phase 64) ---------------------------------------


class CallsIn(BaseModel):
    operation: str = Field(default="read", max_length=10)
    count: int = Field(default=100, ge=1, le=10_000)
    seed: int = Field(default=2030, ge=0)


class OutageIn(BaseModel):
    application_number: str = Field(min_length=1, max_length=20)
    kind: str = Field(default="down", max_length=10)
    reason: str = Field(max_length=300)
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class OutageOut(BaseModel):
    id: uuid.UUID
    outage_number: str
    application_number: str
    application: str
    tier: int
    kind: str
    reason: str
    starts_at: datetime
    ends_at: datetime | None
    status: str  # scheduled, in_force or ended
    incident_number: str | None
    failing: int  # applications whose calls fail while it is down


def _outage_out(db, o, now: datetime | None = None) -> OutageOut:
    from app.modules.itops import simulated

    now = now or simulated._now()
    app = db.get(Application, o.application_id)
    incident = db.get(Incident, o.incident_id) if o.incident_id else None
    ended = o.ends_at is not None and o.ends_at <= now
    state = "scheduled" if o.starts_at > now else "ended" if ended else "in_force"
    return OutageOut(
        id=o.id, outage_number=o.outage_number, application_number=app.application_number,
        application=app.name, tier=app.tier, kind=o.kind, reason=o.reason,
        starts_at=o.starts_at, ends_at=o.ends_at, status=state,
        incident_number=incident.incident_number if incident else None,
        failing=simulated.blast_radius(db, app)["failing"] if o.kind == "down" else 0,
    )  # fmt: skip


@router.get("/applications/{application_id}/contract",
            summary="How the application answers: latency, failures, its state")  # fmt: skip
def application_contract(application_id: uuid.UUID, db: DbSession, _: Authorized(READ)) -> dict:
    from dataclasses import asdict

    from app.modules.itops import simulated

    app = service.get_application(db, application_id)
    view = simulated.Estate(db)
    state = view.state(app)
    return {**asdict(view.contract(app)),
            "state": {"status": state.status, "cause": state.cause, "path": list(state.path)},
            "blast_radius": simulated.blast_radius(db, app)["failing"]}  # fmt: skip


@router.post("/applications/{application_id}/calls",
             summary="Make simulated calls and summarise them (nothing is stored)")  # fmt: skip
def sample_calls(application_id: uuid.UUID, body: CallsIn, db: DbSession,
                 _: Authorized(MANAGE)) -> dict:  # fmt: skip
    from app.modules.itops import simulated

    app = service.get_application(db, application_id)
    return simulated.sample(db, app, body.operation, body.count, body.seed)


@router.get("/outages", response_model=Page[OutageOut])
def list_outages(db: DbSession, page: PageParamsDep, _: Authorized(READ),
                 active: bool = False):  # fmt: skip
    from sqlalchemy import or_

    from app.modules.itops import simulated
    from app.modules.itops.models import ApplicationOutage

    query = select(ApplicationOutage).order_by(ApplicationOutage.starts_at.desc(),
                                               ApplicationOutage.outage_number.desc())  # fmt: skip
    if active:
        now = simulated._now()
        query = query.where(ApplicationOutage.starts_at <= now, or_(
            ApplicationOutage.ends_at.is_(None), ApplicationOutage.ends_at > now))  # fmt: skip
    return _page(db, query, page, _outage_out)


@router.post("/outages", response_model=OutageOut, status_code=status.HTTP_201_CREATED,
             summary="Take an application down or degrade it")  # fmt: skip
def declare_outage(body: OutageIn, db: DbSession, user: Authorized(MANAGE)):
    from app.modules.itops import simulated

    app = service.find_application(db, body.application_number)
    outage = simulated.declare_outage(db, app, body.kind, body.reason, user.id,
                                      starts_at=body.starts_at, ends_at=body.ends_at)  # fmt: skip
    return _outage_out(db, outage)


@router.post("/outages/{outage_id}/end", response_model=OutageOut,
             summary="Restore service now")  # fmt: skip
def end_outage(outage_id: uuid.UUID, db: DbSession, user: Authorized(MANAGE)):
    from app.modules.itops import simulated

    outage = simulated.end_outage(db, simulated.get_outage(db, outage_id), user.id)
    return _outage_out(db, outage)


# --- Applications and workflows (Phase 65) -----------------------------------------------


@router.get("/applications/{application_id}/workflows",
            summary="The workflows that call it, and what its outage stops")  # fmt: skip
def application_workflows(application_id: uuid.UUID, db: DbSession,
                          _: Authorized(READ)) -> dict:  # fmt: skip
    from app.modules.itops import links

    return links.application_workflows(db, service.get_application(db, application_id))


@router.get("/workflows/{workflow_id}/applications",
            summary="The applications a workflow's steps call")  # fmt: skip
def workflow_applications(workflow_id: str, db: DbSession, _: Authorized(READ)) -> dict:
    from app.core.errors import NotFoundError
    from app.modules.itops import links

    result = links.workflow_applications(db, workflow_id)
    if result["name"] is None:
        raise NotFoundError(f"No active workflow {workflow_id} calls an application.")
    return result


@router.get("/estate/wiring", summary="How much of the estate the workflows depend on")
def estate_wiring(db: DbSession, _: Authorized(READ)) -> dict:
    from app.modules.itops import links

    return links.summary(db)
