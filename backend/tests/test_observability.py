"""Phase 15: request metrics, the slow-query log, worker registry and observability API."""

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Connection, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.database import get_engine
from app.core.permissions import RoleCode
from app.jobs import engine
from app.jobs.engine import JobContext, job_kind
from app.observability.metrics import REQUESTS
from app.observability.models import JobWorker
from app.observability.slow_queries import SlowQueryLog, query_context
from tests.factories import auth, make_user


@job_kind("test.observed", description="A job for the observability tests", max_attempts=1)
def _observed(ctx: JobContext) -> dict:
    return {"ok": True}


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


def test_requests_are_counted_by_route_template(client: TestClient, db: Session) -> None:
    REQUESTS.reset()
    headers = auth(make_user(db, RoleCode.AUDITOR))
    for _ in range(3):
        client.get(f"/api/v1/customers/{uuid.uuid4()}", headers=headers)  # 404s
    client.get("/api/v1/customers", headers=headers)
    client.get("/api/v1/customers")  # 401
    client.get("/api/v1/no-such-endpoint")

    rows = {(r["method"], r["route"]): r for r in REQUESTS.snapshot()}
    one = rows[("GET", "/api/v1/customers/{customer_id}")]
    assert one["count"] == 3 and one["by_status"] == {"4xx": 3}
    listing = rows[("GET", "/api/v1/customers")]
    assert listing["by_status"] == {"2xx": 1, "4xx": 1}
    assert listing["p95_ms"] >= listing["p50_ms"] > 0
    # Unknown paths share one series instead of creating one per path.
    assert rows[("GET", "unmatched")]["count"] == 1
    assert not any(str(r[1]).count("-") > 3 for r in rows)  # no raw ids in route names


def test_slow_statements_are_logged_without_their_parameters(db: Session) -> None:
    log = SlowQueryLog()
    log.install(get_engine(), source="test", threshold_ms=15, writer=False)
    token = query_context.set("job test.slow")
    try:
        db.execute(text("SELECT pg_sleep(:seconds)"), {"seconds": 0.03})
        db.execute(text("SELECT 1"))
    finally:
        query_context.reset(token)
        log.uninstall(get_engine())

    entries = log.drain()
    assert len(entries) == 1
    slow = entries[0]
    assert slow["statement"] == "SELECT pg_sleep(%(seconds)s)"  # the value is not stored
    assert slow["duration_ms"] >= 25
    assert (slow["source"], slow["context"]) == ("test", "job test.slow")


def test_observability_api(client: TestClient, db: Session, factory) -> None:
    auditor = auth(make_user(db, RoleCode.AUDITOR))
    teller = auth(make_user(db, RoleCode.BANKING_EMPLOYEE))
    assert client.get("/api/v1/observability/overview", headers=teller).status_code == 403

    # Two jobs finish through a registered worker; one more waits.
    for _ in range(2):
        engine.enqueue(db, "test.observed", {})
    db.commit()
    stats = engine.run_worker(factory, schedules=False, idle_exit=True, poll_seconds=0.01)
    engine.enqueue(db, "test.observed", {})
    db.commit()
    # Slow queries written by the log's writer.
    log = SlowQueryLog()
    for duration in (300, 500):
        log.pending.append(
            {
                "occurred_at": None,
                "duration_ms": duration,
                "statement": "SELECT count(*) FROM workflow_events_simulation",
                "source": "worker:1",
                "context": "job simulation.archive_history",
                "correlation_id": None,
            }
        )
    entries = [{k: v for k, v in e.items() if v is not None} for e in log.drain()]
    log.write(db.connection(), entries)

    body = client.get("/api/v1/observability/overview", headers=auditor).json()
    assert body["queue"]["due"] >= 1 and body["queue"]["oldest_due_seconds"] >= 0
    kinds = {k["kind"]: k for k in body["throughput"]}
    assert kinds["test.observed"]["succeeded"] >= 2
    worker = next(w for w in body["workers"] if w["name"] == stats.worker)
    assert worker["state"] == "stopped" and worker["succeeded"] == 2
    assert body["database"]["size_bytes"] > 0
    assert body["process"]["jobs_execution"] == "inline"

    latest = client.get("/api/v1/observability/slow-queries", headers=auditor).json()
    assert latest[0]["context"] == "job simulation.archive_history"
    grouped = client.get("/api/v1/observability/slow-queries?grouped=true", headers=auditor).json()
    group = next(g for g in grouped if g["statement"].endswith("workflow_events_simulation"))
    assert (group["count"], group["max_ms"], group["total_ms"]) == (2, 500, 800)


def test_worker_registry_marks_running_and_stopped_workers(db: Session, factory) -> None:
    stats = engine.run_worker(factory, schedules=False, idle_exit=True, poll_seconds=0.01)
    worker = db.execute(select(JobWorker).where(JobWorker.name == stats.worker)).scalar_one()
    assert worker.stopped_at is not None and worker.last_seen_at >= worker.started_at


def test_prometheus_endpoint_needs_its_token(client: TestClient, db: Session, monkeypatch) -> None:
    assert client.get("/api/metrics").status_code == 404  # no token configured: no endpoint
    monkeypatch.setattr(get_settings(), "metrics_token", SecretStr("scrape-me"))
    assert client.get("/api/metrics", headers={"Authorization": "Bearer nope"}).status_code == 404
    odd = {"Authorization": "Bearer café".encode()}  # non-ASCII bytes: still a plain 404
    assert client.get("/api/metrics", headers=odd).status_code == 404

    client.get("/api/health")
    response = client.get("/api/metrics", headers={"Authorization": "Bearer scrape-me"})

    assert response.status_code == 200
    body = response.text
    assert 'atlas_http_requests_total{method="GET",route="/api/health",status="2xx"}' in body
    assert (
        'atlas_http_request_duration_seconds_bucket{method="GET",route="/api/health",le="+Inf"}'
        in body
    )
    assert 'atlas_jobs{state="due"}' in body and "atlas_workers" in body
