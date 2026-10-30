import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.audit import record_audit_event
from app.core.dependencies import DbSession
from app.core.errors import BusinessRuleViolation, NotFoundError
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
from app.jobs import engine
from app.jobs.models import Job, JobSchedule, JobStatus
from app.modules.countries.models import Country
from app.modules.identity.dependencies import Authorized
from app.modules.identity.models import User
from app.simulation.router import SessionFactory

jobs_router = APIRouter(prefix="/jobs", tags=["jobs"])
schedules_router = APIRouter(prefix="/job-schedules", tags=["jobs"])


class JobOut(BaseModel):
    id: uuid.UUID
    job_number: int
    kind: str
    payload: dict[str, Any]
    status: str
    attempts: int
    max_attempts: int
    run_at: datetime
    result: dict[str, Any] | None
    last_error: str | None
    locked_by: str | None
    schedule_name: str | None
    created_by_username: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobKindOut(BaseModel):
    kind: str
    description: str
    max_attempts: int
    manual: bool


class JobCreate(BaseModel):
    kind: str = Field(max_length=60)
    payload: dict[str, Any] = Field(default_factory=dict)


class ScheduleOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    kind: str
    payload: dict[str, Any]
    interval_seconds: int
    enabled: bool
    business_calendar: str | None = None
    next_run_at: datetime
    last_job: JobOut | None


class ScheduleUpdate(BaseModel):
    enabled: bool | None = None
    interval_seconds: int | None = Field(default=None, ge=60, le=7 * 24 * 3600)
    # A country code to run on its business days only; "" clears it (Phase 26).
    business_calendar: str | None = Field(default=None, pattern=r"^([A-Z]{2})?$")


def _usernames(db, ids) -> dict[uuid.UUID, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.username).where(User.id.in_(ids))).tuples().all())


def _job_out(job: Job, names: dict[uuid.UUID, str]) -> JobOut:
    return JobOut(
        id=job.id,
        job_number=job.job_number,
        kind=job.kind,
        payload=job.payload,
        status=job.status,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        run_at=job.run_at,
        result=job.result,
        last_error=job.last_error,
        locked_by=job.locked_by,
        schedule_name=job.schedule_name,
        created_by_username=names.get(job.created_by) if job.created_by else None,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@jobs_router.get("", response_model=Page[JobOut], summary="Background jobs, latest first")
def list_jobs(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.JOBS_READ),
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    kind: Annotated[str | None, Query(max_length=60)] = None,
) -> Page[JobOut]:
    query = select(Job).order_by(Job.job_number.desc())
    if status_filter:
        query = query.where(Job.status == status_filter)
    if kind:
        query = query.where(Job.kind == kind)
    items, total = paginate(db, query, page)
    names = _usernames(db, [j.created_by for j in items])
    return Page(
        items=[_job_out(j, names) for j in items], total=total, limit=page.limit, offset=page.offset
    )


@jobs_router.get("/kinds", response_model=list[JobKindOut], summary="Registered job kinds")
def list_kinds(_: Authorized(Permission.JOBS_READ)) -> list[JobKindOut]:
    return [
        JobKindOut(
            kind=k.name, description=k.description, max_attempts=k.max_attempts, manual=k.manual
        )
        for k in sorted(engine.REGISTRY.values(), key=lambda k: k.name)
    ]


@jobs_router.get("/{job_id}", response_model=JobOut, summary="One job")
def get_job(job_id: uuid.UUID, db: DbSession, _: Authorized(Permission.JOBS_READ)) -> JobOut:
    job = db.get(Job, job_id)
    if job is None:
        raise NotFoundError("Job not found.")
    return _job_out(job, _usernames(db, [job.created_by]))


@jobs_router.post(
    "",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a job by hand (kinds marked manual only); it runs as you",
)
def create_job(
    body: JobCreate,
    db: DbSession,
    actor: Authorized(Permission.JOBS_MANAGE),
    tasks: BackgroundTasks,
    factory: SessionFactory,
) -> JobOut:
    spec = engine.REGISTRY.get(body.kind)
    if spec is None or not spec.manual:
        raise BusinessRuleViolation(
            "This kind of job cannot be queued by hand.",
            {"manual_kinds": sorted(k.name for k in engine.REGISTRY.values() if k.manual)},
        )
    job = engine.enqueue(db, body.kind, body.payload, created_by=actor.id)
    record_audit_event(
        db,
        actor_id=actor.id,
        action="job.queued",
        entity_type="job",
        entity_id=job.id,
        metadata={"kind": job.kind, "payload": job.payload},
    )
    db.commit()
    engine.dispatch(tasks, factory, [job.id])
    return _job_out(job, {actor.id: actor.username})


@jobs_router.post("/{job_id}/cancel", response_model=JobOut, summary="Cancel a queued job")
def cancel_job(job_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.JOBS_MANAGE)):
    job = db.execute(select(Job).where(Job.id == job_id).with_for_update()).scalar_one_or_none()
    if job is None:
        raise NotFoundError("Job not found.")
    engine.cancel(db, job)
    record_audit_event(
        db, actor_id=actor.id, action="job.cancelled", entity_type="job", entity_id=job.id
    )
    return _job_out(job, _usernames(db, [job.created_by]))


# --- Schedules ---------------------------------------------------------------------------------


def _schedule_out(db, schedule: JobSchedule) -> ScheduleOut:
    last = db.get(Job, schedule.last_job_id) if schedule.last_job_id else None
    return ScheduleOut(
        id=schedule.id,
        name=schedule.name,
        description=schedule.description,
        kind=schedule.kind,
        payload=schedule.payload,
        interval_seconds=schedule.interval_seconds,
        enabled=schedule.enabled,
        business_calendar=schedule.business_calendar,
        next_run_at=schedule.next_run_at,
        last_job=_job_out(last, _usernames(db, [last.created_by])) if last else None,
    )


def _schedule(db, name: str) -> JobSchedule:
    schedule = db.execute(
        select(JobSchedule).where(JobSchedule.name == name).with_for_update()
    ).scalar_one_or_none()
    if schedule is None:
        raise NotFoundError("Schedule not found.")
    return schedule


@schedules_router.get("", response_model=list[ScheduleOut], summary="Recurring jobs")
def list_schedules(db: DbSession, _: Authorized(Permission.JOBS_READ)) -> list[ScheduleOut]:
    schedules = db.execute(select(JobSchedule).order_by(JobSchedule.name)).scalars()
    return [_schedule_out(db, s) for s in schedules]


@schedules_router.patch(
    "/{name}", response_model=ScheduleOut, summary="Switch a schedule on or off, or change it"
)
def update_schedule(
    name: str, body: ScheduleUpdate, db: DbSession, actor: Authorized(Permission.JOBS_MANAGE)
) -> ScheduleOut:
    schedule = _schedule(db, name)
    changes: dict[str, Any] = {}
    if body.enabled is not None and body.enabled != schedule.enabled:
        changes["enabled"] = [schedule.enabled, body.enabled]
        schedule.enabled = body.enabled
    if body.interval_seconds is not None and body.interval_seconds != schedule.interval_seconds:
        changes["interval_seconds"] = [schedule.interval_seconds, body.interval_seconds]
        schedule.interval_seconds = body.interval_seconds
    if body.business_calendar is not None:
        calendar = body.business_calendar or None
        if (
            calendar is not None
            and not db.execute(
                select(Country.id).where(Country.iso_country_code == calendar)
            ).first()
        ):
            raise BusinessRuleViolation(f"No country {calendar}.", {"business_calendar": calendar})
        if calendar != schedule.business_calendar:
            changes["business_calendar"] = [schedule.business_calendar, calendar]
            schedule.business_calendar = calendar
    if changes:
        record_audit_event(
            db,
            actor_id=actor.id,
            action="job_schedule.updated",
            entity_type="job_schedule",
            entity_id=schedule.id,
            metadata={"name": name, "changes": changes},
        )
    db.flush()
    return _schedule_out(db, schedule)


@schedules_router.post(
    "/{name}/run",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue the schedule's job now (at most one active job per schedule)",
)
def run_schedule(
    name: str,
    db: DbSession,
    actor: Authorized(Permission.JOBS_MANAGE),
    tasks: BackgroundTasks,
    factory: SessionFactory,
) -> JobOut:
    schedule = _schedule(db, name)
    job = engine.enqueue(
        db,
        schedule.kind,
        schedule.payload,
        dedupe_key=f"schedule:{schedule.name}",
        schedule_name=schedule.name,
        created_by=actor.id,
    )
    schedule.last_job_id = job.id
    record_audit_event(
        db,
        actor_id=actor.id,
        action="job.queued",
        entity_type="job",
        entity_id=job.id,
        metadata={"kind": job.kind, "schedule": name},
    )
    db.commit()
    engine.dispatch(tasks, factory, [job.id])
    return _job_out(job, _usernames(db, [job.created_by]))
