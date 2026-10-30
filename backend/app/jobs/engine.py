"""Queue, claim and run background jobs; tick the schedules; recover lost workers.

Jobs are rows in `jobs`. `enqueue` adds one inside the caller's transaction. A worker
`claim`s the next due job in its own short transaction with `FOR UPDATE SKIP LOCKED`,
runs the handler outside it while a heartbeat thread keeps `heartbeat_at` fresh, and
records the outcome. A failure is retried with exponential backoff until the kind's
`max_attempts`; a job whose worker stopped heart-beating is requeued (or failed when out of
attempts) by `recover_stale`. `tick_schedules` queues each due schedule's job, at most one
active job per schedule.

Where no worker process runs (local development, tests, CI) the API runs the job it just
queued in the same process (`dispatch`), so behaviour matches the old background tasks
while the job is still recorded.
"""

import logging
import os
import socket
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.core.errors import BusinessRuleViolation
from app.jobs.models import ACTIVE_JOB_STATUSES, Job, JobSchedule, JobStatus
from app.observability.models import JobWorker
from app.observability.slow_queries import query_context

logger = logging.getLogger("atlas.jobs")

HEARTBEAT_SECONDS = 10


class PermanentJobError(Exception):
    """A failure that retrying cannot fix (bad payload, missing record)."""


@dataclass
class JobContext:
    factory: sessionmaker[Session]
    job_id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    attempt: int
    created_by: uuid.UUID | None
    worker: str = ""  # the process running it (for the job's own records)


Handler = Callable[[JobContext], dict[str, Any] | None]


@dataclass(frozen=True)
class JobKind:
    name: str
    handler: Handler
    description: str
    max_attempts: int = 3
    backoff_seconds: int = 30
    # Kinds people may queue by hand through the API (the rest are queued by services).
    manual: bool = False


REGISTRY: dict[str, JobKind] = {}


def job_kind(
    name: str,
    *,
    description: str,
    max_attempts: int = 3,
    backoff_seconds: int = 30,
    manual: bool = False,
) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        REGISTRY[name] = JobKind(name, handler, description, max_attempts, backoff_seconds, manual)
        return handler

    return register


def worker_name() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident() % 100000}"


def _now() -> datetime:
    return datetime.now(UTC)


# --- Queueing --------------------------------------------------------------------------------


def enqueue(
    db: Session,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    run_at: datetime | None = None,
    priority: int = 100,
    dedupe_key: str | None = None,
    created_by: uuid.UUID | None = None,
    schedule_name: str | None = None,
) -> Job:
    """Queue a job in the caller's transaction. With a `dedupe_key`, an active (queued or
    running) job with the same key is returned instead of a second one."""
    spec = REGISTRY.get(kind)
    if spec is None:
        raise BusinessRuleViolation(f"Unknown job kind '{kind}'.", {"kind": kind})
    if dedupe_key:
        existing = _active_with_key(db, dedupe_key)
        if existing is not None:
            return existing
    job = Job(
        kind=kind,
        payload=payload or {},
        status=JobStatus.QUEUED.value,
        priority=priority,
        run_at=run_at or _now(),
        attempts=0,
        max_attempts=spec.max_attempts,
        dedupe_key=dedupe_key,
        created_by=created_by,
        schedule_name=schedule_name,
    )
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError:
        # Another transaction queued the same key first.
        existing = _active_with_key(db, dedupe_key) if dedupe_key else None
        if existing is None:
            raise
        return existing
    return job


def _active_with_key(db: Session, key: str) -> Job | None:
    return db.execute(
        select(Job).where(Job.dedupe_key == key, Job.status.in_(ACTIVE_JOB_STATUSES))
    ).scalar_one_or_none()


def cancel(db: Session, job: Job) -> Job:
    if job.status != JobStatus.QUEUED:
        raise BusinessRuleViolation(f"Only queued jobs can be cancelled; this one is {job.status}.")
    job.status = JobStatus.CANCELLED.value
    job.finished_at = _now()
    db.flush()
    return job


# --- Claiming and running --------------------------------------------------------------------


def claim(
    factory: sessionmaker[Session], worker: str, *, job_id: uuid.UUID | None = None
) -> uuid.UUID | None:
    """Take the next due job (or `job_id`, if it is still queued) for `worker`."""
    with factory() as db, db.begin():
        query = (
            select(Job)
            .where(Job.status == JobStatus.QUEUED.value, Job.run_at <= func.clock_timestamp())
            .order_by(Job.priority, Job.run_at, Job.job_number)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job_id is not None:
            query = query.where(Job.id == job_id)
        job = db.execute(query).scalar_one_or_none()
        if job is None:
            return None
        now = _now()
        job.status = JobStatus.RUNNING.value
        job.locked_by = worker
        job.attempts += 1
        job.started_at = now
        job.heartbeat_at = now
        return job.id


def _heartbeat(factory: sessionmaker[Session], job_id: uuid.UUID, worker: str, stop) -> None:
    while not stop.wait(HEARTBEAT_SECONDS):
        try:
            with factory() as db, db.begin():
                db.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.locked_by == worker)
                    .values(heartbeat_at=_now())
                )
        except Exception:  # a missed beat is recovered by the next one
            logger.warning("job heartbeat failed", extra={"job_id": str(job_id)})


def run_claimed(factory: sessionmaker[Session], job_id: uuid.UUID, worker: str) -> str:
    """Run a job this worker claimed and record the outcome. Returns the final status."""
    with factory() as db:
        job = db.get(Job, job_id)
        assert job is not None
        context = JobContext(
            factory=factory,
            job_id=job.id,
            kind=job.kind,
            payload=dict(job.payload),
            attempt=job.attempts,
            created_by=job.created_by,
            worker=worker,
        )
        attempts, max_attempts = job.attempts, job.max_attempts
    spec = REGISTRY.get(context.kind)
    stop = threading.Event()
    beat = threading.Thread(target=_heartbeat, args=(factory, job_id, worker, stop), daemon=True)
    beat.start()
    started = time.perf_counter()
    context_token = query_context.set(f"job {context.kind}")
    try:
        if spec is None:
            raise PermanentJobError(f"No handler is registered for '{context.kind}'.")
        result = spec.handler(context) or {}
        outcome: dict[str, Any] = {
            "status": JobStatus.SUCCEEDED.value,
            "result": {
                **result,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "worker": worker,  # which process ran it (inline:… when the API did)
            },
            "last_error": None,
            "finished_at": _now(),
        }
    except Exception as exc:  # recorded on the job; the worker carries on
        logger.exception("job failed", extra={"job_id": str(job_id), "kind": context.kind})
        retry = not isinstance(exc, PermanentJobError) and attempts < max_attempts
        error = f"{type(exc).__name__}: {exc}"[:2000]
        if retry:
            backoff = (spec.backoff_seconds if spec else 30) * 2 ** (attempts - 1)
            outcome = {
                "status": JobStatus.QUEUED.value,
                "run_at": _now() + timedelta(seconds=backoff),
                "last_error": error,
            }
        else:
            outcome = {"status": JobStatus.FAILED.value, "last_error": error, "finished_at": _now()}
    finally:
        query_context.reset(context_token)
        stop.set()
        beat.join()
    with factory() as db, db.begin():
        # Only if the job is still ours: recover_stale may have taken it back meanwhile.
        db.execute(
            update(Job)
            .where(Job.id == job_id, Job.locked_by == worker, Job.status == JobStatus.RUNNING)
            .values(locked_by=None, heartbeat_at=None, **outcome)
        )
    return outcome["status"]


def run_next(factory: sessionmaker[Session], worker: str | None = None) -> str | None:
    """Claim and run the next due job. Returns its final status, or None if none was due."""
    worker = worker or worker_name()
    job_id = claim(factory, worker)
    return run_claimed(factory, job_id, worker) if job_id else None


def run_now(factory: sessionmaker[Session], job_id: uuid.UUID) -> str | None:
    """Run one specific queued job in this process (inline execution)."""
    worker = f"inline:{worker_name()}"
    claimed = claim(factory, worker, job_id=job_id)
    return run_claimed(factory, claimed, worker) if claimed else None


def dispatch(background_tasks, factory: sessionmaker[Session], job_ids: list[uuid.UUID]) -> None:
    """After the transaction that queued `job_ids` committed: run them in this process
    unless dedicated workers are configured to pick them up."""
    if get_settings().jobs_execution != "inline":
        return
    for job_id in job_ids:
        background_tasks.add_task(run_now, factory, job_id)


# --- Recovery and schedules -----------------------------------------------------------------


def recover_stale(factory: sessionmaker[Session], *, stale_after: timedelta | None = None) -> int:
    """Running jobs whose worker stopped heart-beating: retry them, or fail them when they
    are out of attempts. Returns how many were recovered."""
    stale_after = stale_after or timedelta(seconds=get_settings().jobs_stale_after_seconds)
    with factory() as db, db.begin():
        stale = list(
            db.execute(
                select(Job)
                .where(
                    Job.status == JobStatus.RUNNING.value,
                    Job.heartbeat_at < func.clock_timestamp() - stale_after,
                )
                .with_for_update(skip_locked=True)
            ).scalars()
        )
        for job in stale:
            note = f"Worker {job.locked_by} stopped responding."
            job.locked_by = None
            job.heartbeat_at = None
            job.last_error = note
            if job.attempts < job.max_attempts:
                job.status = JobStatus.QUEUED.value
                job.run_at = _now()
            else:
                job.status = JobStatus.FAILED.value
                job.finished_at = _now()
        return len(stale)


def _business_run(db: Session, schedule: JobSchedule, at: datetime) -> datetime:
    """`at`, moved forward by whole days until it falls on a business day of the schedule's
    calendar country (in that country's local time); unchanged without a calendar."""
    if not schedule.business_calendar:
        return at
    from zoneinfo import ZoneInfo

    from app.modules.countries.models import Country
    from app.modules.reference import calendar

    country = db.execute(
        select(Country).where(Country.iso_country_code == schedule.business_calendar)
    ).scalar_one_or_none()
    if country is None:
        return at
    profile = country.calendar_profile()
    zone = ZoneInfo(country.default_timezone)
    for _ in range(31):
        if calendar.is_business_day(profile, at.astimezone(zone).date()):
            return at
        at += timedelta(days=1)
    return at


def tick_schedules(factory: sessionmaker[Session]) -> list[uuid.UUID]:
    """Queue the job of every due, enabled schedule. Returns the ids of new jobs. A schedule
    with a business calendar that falls due on a weekend or holiday is moved to the next
    business day instead (Phase 26)."""
    queued: list[uuid.UUID] = []
    with factory() as db, db.begin():
        due = list(
            db.execute(
                select(JobSchedule)
                .where(
                    JobSchedule.enabled.is_(True), JobSchedule.next_run_at <= func.clock_timestamp()
                )
                .with_for_update(skip_locked=True)
            ).scalars()
        )
        for schedule in due:
            business = _business_run(db, schedule, schedule.next_run_at)
            if business != schedule.next_run_at:
                schedule.next_run_at = business
                continue
            job = enqueue(
                db,
                schedule.kind,
                schedule.payload,
                dedupe_key=f"schedule:{schedule.name}",
                schedule_name=schedule.name,
            )
            if job.id != schedule.last_job_id:
                queued.append(job.id)
            schedule.last_job_id = job.id
            schedule.next_run_at = _business_run(
                db, schedule, _now() + timedelta(seconds=schedule.interval_seconds)
            )
    return queued


# --- The worker loop ------------------------------------------------------------------------


@dataclass
class WorkerStats:
    worker: str
    succeeded: int = 0
    failed: int = 0
    retried: int = 0
    recovered: int = 0
    scheduled: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)


def run_worker(
    factory: sessionmaker[Session],
    *,
    stop: threading.Event | None = None,
    poll_seconds: float = 1.0,
    schedules: bool = True,
    max_jobs: int | None = None,
    idle_exit: bool = False,
) -> WorkerStats:
    """Process jobs until `stop` is set (or `max_jobs` ran, or the queue is empty when
    `idle_exit`). Each worker also ticks the schedules and recovers lost jobs; the
    database locks make that safe with any number of workers."""
    stop = stop or threading.Event()
    stats = WorkerStats(worker=worker_name())
    _register(factory, stats)
    try:
        _work(factory, stats, stop, poll_seconds, schedules, max_jobs, idle_exit)
    finally:
        _report(factory, stats, stopped=True)
    return stats


def _work(
    factory: sessionmaker[Session],
    stats: WorkerStats,
    stop: threading.Event,
    poll_seconds: float,
    schedules: bool,
    max_jobs: int | None,
    idle_exit: bool,
) -> None:
    last_upkeep = 0.0
    while not stop.is_set():
        if time.monotonic() - last_upkeep > 5:
            last_upkeep = time.monotonic()
            _report(factory, stats)
            stats.recovered += recover_stale(factory)
            if schedules:
                stats.scheduled += len(tick_schedules(factory))
        job_id = claim(factory, stats.worker)
        if job_id is None:
            if idle_exit:
                break
            stop.wait(poll_seconds)
            continue
        with factory() as db:
            kind = db.execute(select(Job.kind).where(Job.id == job_id)).scalar_one()
        outcome = run_claimed(factory, job_id, stats.worker)
        stats.by_kind[kind] = stats.by_kind.get(kind, 0) + 1
        if outcome == JobStatus.SUCCEEDED:
            stats.succeeded += 1
        elif outcome == JobStatus.QUEUED:
            stats.retried += 1
        else:
            stats.failed += 1
        if max_jobs is not None and stats.succeeded + stats.failed >= max_jobs:
            break


# --- Worker registry (observability) ----------------------------------------------------------


def _register(factory: sessionmaker[Session], stats: WorkerStats) -> None:
    now = _now()
    with factory() as db, db.begin():
        db.add(
            JobWorker(
                name=stats.worker,
                hostname=socket.gethostname()[:255],
                pid=os.getpid(),
                started_at=now,
                last_seen_at=now,
                succeeded=0,
                failed=0,
                retried=0,
            )
        )


def _report(factory: sessionmaker[Session], stats: WorkerStats, *, stopped: bool = False) -> None:
    """Record that the worker is alive (and its counts); a stopped worker says so."""
    values: dict[str, Any] = {
        "last_seen_at": _now(),
        "succeeded": stats.succeeded,
        "failed": stats.failed,
        "retried": stats.retried,
    }
    if stopped:
        values["stopped_at"] = values["last_seen_at"]
    try:
        with factory() as db, db.begin():
            db.execute(update(JobWorker).where(JobWorker.name == stats.worker).values(**values))
    except Exception:  # bookkeeping only: never stop the worker over it
        logger.exception("could not update the worker registry")
