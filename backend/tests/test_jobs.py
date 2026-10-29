"""Phase 14: the durable job queue, its workers, schedules and API."""

import threading
import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, delete, select, update
from sqlalchemy.orm import Session

from app.core.database import get_sessionmaker
from app.core.permissions import RoleCode
from app.jobs import engine
from app.jobs.engine import JobContext, PermanentJobError, job_kind
from app.jobs.models import Job, JobSchedule
from app.modules.ledger.models import LedgerReconciliation
from app.modules.lending.models import LoanServicingRun
from app.simulation.router import get_simulation_sessionmaker
from tests.factories import auth, make_loan, make_staff, make_user

CALLS: Counter[str] = Counter()
FAIL_FIRST: set[str] = set()
CALLS_LOCK = threading.Lock()


@job_kind("test.record", description="Record that it ran", max_attempts=3, backoff_seconds=60)
def _record(ctx: JobContext) -> dict:
    tag = ctx.payload["tag"]
    with CALLS_LOCK:
        CALLS[tag] += 1
        first = CALLS[tag] == 1
    if tag in FAIL_FIRST and first:
        raise RuntimeError("transient failure")
    if ctx.payload.get("permanent"):
        raise PermanentJobError("bad payload")
    return {"tag": tag}


@pytest.fixture
def factory(db_connection: Connection):
    def make() -> Session:
        return Session(
            bind=db_connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
            expire_on_commit=False,
        )

    return make


@pytest.fixture(autouse=True)
def quiet_schedules(db: Session) -> None:
    """The migration's default schedules would otherwise queue real jobs mid-test."""
    db.execute(update(JobSchedule).values(next_run_at=datetime.now(UTC) + timedelta(days=1)))
    db.flush()


def _queue(db: Session, tag: str, **payload) -> Job:
    job = engine.enqueue(db, "test.record", {"tag": tag, **payload})
    db.commit()
    return job


def test_jobs_run_once_and_record_their_result(db: Session, factory) -> None:
    tag = uuid.uuid4().hex
    job = _queue(db, tag)

    assert engine.run_next(factory) == "succeeded"
    assert engine.run_next(factory) is None  # nothing else is due

    db.refresh(job)
    assert (job.status, job.attempts, job.locked_by) == ("succeeded", 1, None)
    assert job.result["tag"] == tag and job.result["duration_ms"] >= 0
    assert CALLS[tag] == 1


def test_a_dedupe_key_allows_one_active_job(db: Session, factory) -> None:
    first = engine.enqueue(db, "test.record", {"tag": "d"}, dedupe_key="only-one")
    again = engine.enqueue(db, "test.record", {"tag": "d"}, dedupe_key="only-one")
    assert again.id == first.id
    db.commit()
    engine.run_next(factory)
    later = engine.enqueue(db, "test.record", {"tag": "d"}, dedupe_key="only-one")
    assert later.id != first.id  # the first one finished


def test_failures_retry_with_backoff_then_fail(db: Session, factory) -> None:
    tag = uuid.uuid4().hex
    FAIL_FIRST.add(tag)
    job = _queue(db, tag)

    assert engine.run_next(factory) == "queued"  # retried later
    db.refresh(job)
    assert job.attempts == 1 and "transient failure" in job.last_error
    assert job.run_at > datetime.now(UTC) + timedelta(seconds=50)  # 60 s backoff
    assert engine.run_next(factory) is None  # not due yet

    db.execute(update(Job).where(Job.id == job.id).values(run_at=datetime.now(UTC)))
    db.commit()
    assert engine.run_next(factory) == "succeeded"
    db.refresh(job)
    assert job.attempts == 2

    permanent = _queue(db, uuid.uuid4().hex, permanent=True)
    assert engine.run_next(factory) == "failed"  # never retried
    db.refresh(permanent)
    assert permanent.attempts == 1 and "bad payload" in permanent.last_error


def test_jobs_of_a_lost_worker_are_recovered(db: Session, factory) -> None:
    job = _queue(db, uuid.uuid4().hex)
    assert engine.claim(factory, "worker-that-dies") == job.id
    db.execute(
        update(Job)
        .where(Job.id == job.id)
        .values(heartbeat_at=datetime.now(UTC) - timedelta(minutes=10))
    )
    db.commit()

    assert engine.recover_stale(factory, stale_after=timedelta(minutes=5)) == 1

    db.refresh(job)
    assert (job.status, job.locked_by) == ("queued", None)
    assert "stopped responding" in job.last_error
    # Another worker runs it; then the "dead" worker finishes late. Its report must not
    # overwrite the newer result: completion only applies while the job is still its own.
    assert engine.run_next(factory, "worker-2") == "succeeded"
    db.refresh(job)
    finished = job.finished_at
    engine.run_claimed(factory, job.id, "worker-that-dies")
    db.refresh(job)
    assert (job.status, job.attempts, job.locked_by) == ("succeeded", 2, None)
    assert job.finished_at == finished


def test_schedules_queue_at_most_one_job_each(db: Session, factory) -> None:
    schedule = JobSchedule(
        name=f"test-{uuid.uuid4().hex[:8]}",
        description="test",
        kind="test.record",
        payload={"tag": "scheduled"},
        interval_seconds=3600,
        enabled=True,
        next_run_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    db.add(schedule)
    db.commit()

    first = engine.tick_schedules(factory)
    assert len(first) == 1
    assert engine.tick_schedules(factory) == []  # next run is an hour away
    # Due again while its job is still queued: no second job.
    db.execute(
        update(JobSchedule)
        .where(JobSchedule.id == schedule.id)
        .values(next_run_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db.commit()
    assert engine.tick_schedules(factory) == []
    jobs = db.execute(select(Job).where(Job.schedule_name == schedule.name)).scalars().all()
    assert len(jobs) == 1 and jobs[0].dedupe_key == f"schedule:{schedule.name}"


def test_parallel_workers_share_the_queue_without_running_a_job_twice() -> None:
    """Real commits from four worker threads with their own connections."""
    factory = get_sessionmaker()
    tag = f"parallel-{uuid.uuid4().hex}"
    with factory() as db, db.begin():
        ids = [engine.enqueue(db, "test.record", {"tag": f"{tag}-{i}"}).id for i in range(120)]
    try:
        stats: list[engine.WorkerStats] = []
        threads = [
            threading.Thread(
                target=lambda: stats.append(
                    engine.run_worker(factory, schedules=False, idle_exit=True, poll_seconds=0.05)
                )
            )
            for _ in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert all(CALLS[f"{tag}-{i}"] == 1 for i in range(120))
        assert sum(s.succeeded for s in stats) == 120
        assert sum(1 for s in stats if s.succeeded) > 1  # the work was actually shared
    finally:
        with factory() as db, db.begin():
            db.execute(delete(Job).where(Job.id.in_(ids)))


# --- Handlers ------------------------------------------------------------------------------------


def test_reconciliation_and_servicing_jobs(db: Session, factory) -> None:
    staff = make_staff(db)
    make_loan(db, staff, disbursed=date(2040, 1, 10))
    reconcile = engine.enqueue(db, "ledger.reconcile", {"mode": "incremental"})
    servicing = engine.enqueue(db, "lending.service_loans", {"as_of": "2040-03-01"})
    again = engine.enqueue(db, "lending.service_loans", {"as_of": "2040-02-01"})
    db.commit()

    for _ in range(3):
        engine.run_next(factory)

    for job in (reconcile, servicing, again):
        db.refresh(job)
    assert reconcile.status == "succeeded" and reconcile.result["ok"] is True
    assert db.execute(
        select(LedgerReconciliation).where(
            LedgerReconciliation.run_number == reconcile.result["run_number"]
        )
    ).scalar_one()
    # Scheduled servicing runs as the scheduler's service account.
    assert servicing.status == "succeeded", servicing.last_error
    run = db.execute(
        select(LoanServicingRun).where(
            LoanServicingRun.run_number == servicing.result["run_number"]
        )
    ).scalar_one()
    assert run.as_of == date(2040, 3, 1)
    # A book already serviced past the date is left alone.
    assert again.result["skipped"] is True and again.result["business_date"] == "2040-03-01"


# --- API ------------------------------------------------------------------------------------------


@pytest.fixture
def api(app: FastAPI, factory) -> TestClient:
    app.dependency_overrides[get_simulation_sessionmaker] = lambda: factory
    with TestClient(app) as client:
        yield client


def test_jobs_api_permissions_schedules_and_manual_runs(api: TestClient, db: Session) -> None:
    admin = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))
    auditor = auth(make_user(db, RoleCode.AUDITOR))
    teller = auth(make_user(db, RoleCode.BANKING_EMPLOYEE))

    schedules = api.get("/api/v1/job-schedules", headers=auditor).json()
    names = {s["name"]: s for s in schedules}
    assert names["ledger-incremental-reconciliation"]["enabled"] is True
    assert names["loan-servicing"]["enabled"] is False
    assert api.get("/api/v1/job-schedules", headers=teller).status_code == 403
    assert (
        api.patch(
            "/api/v1/job-schedules/loan-servicing", json={"enabled": True}, headers=auditor
        ).status_code
        == 403
    )

    changed = api.patch(
        "/api/v1/job-schedules/loan-servicing",
        json={"enabled": True, "interval_seconds": 7200},
        headers=admin,
    )
    assert changed.status_code == 200
    assert (changed.json()["enabled"], changed.json()["interval_seconds"]) == (True, 7200)

    queued = api.post("/api/v1/job-schedules/ledger-incremental-reconciliation/run", headers=admin)
    assert queued.status_code == 202
    # No worker process in tests: the API ran the job itself after responding.
    job = api.get(f"/api/v1/jobs/{queued.json()['id']}", headers=auditor).json()
    assert job["status"] == "succeeded" and job["result"]["mode"] == "incremental"
    assert job["created_by_username"] is not None

    manual = api.post(
        "/api/v1/jobs",
        json={"kind": "ledger.reconcile", "payload": {"mode": "full"}},
        headers=admin,
    )
    assert manual.status_code == 202
    refused = api.post("/api/v1/jobs", json={"kind": "simulation.execute"}, headers=admin)
    assert refused.status_code == 422 and "ledger.reconcile" in refused.text
    kinds = {k["kind"]: k for k in api.get("/api/v1/jobs/kinds", headers=auditor).json()}
    assert kinds["ledger.reconcile"]["manual"] and not kinds["simulation.execute"]["manual"]
    listing = api.get("/api/v1/jobs?kind=ledger.reconcile", headers=auditor).json()
    assert listing["total"] >= 2


def test_queued_jobs_can_be_cancelled(api: TestClient, db: Session) -> None:
    admin = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))
    job = engine.enqueue(
        db, "test.record", {"tag": "cancel"}, run_at=datetime.now(UTC) + timedelta(hours=1)
    )
    db.commit()

    cancelled = api.post(f"/api/v1/jobs/{job.id}/cancel", headers=admin)

    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert api.post(f"/api/v1/jobs/{job.id}/cancel", headers=admin).status_code == 422
