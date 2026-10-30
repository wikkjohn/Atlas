"""What the observability API reports: requests, the job queue, workers, slow queries."""

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Float, case, cast, func, select, text
from sqlalchemy.orm import Session

from app import __version__
from app.config import get_settings
from app.jobs.models import Job, JobStatus
from app.observability.metrics import REQUESTS, gauge
from app.observability.models import JobWorker, SlowQuery

# A worker that has not reported for this long is shown as lost (it reports every ~5 s).
WORKER_LOST_AFTER = timedelta(seconds=60)
THROUGHPUT_WINDOW = timedelta(hours=1)


def _now() -> datetime:
    return datetime.now(UTC)


def queue(db: Session) -> dict[str, Any]:
    now = func.clock_timestamp()
    row = db.execute(
        select(
            func.count().filter(Job.status == JobStatus.QUEUED, Job.run_at <= now).label("due"),
            func.count().filter(Job.status == JobStatus.QUEUED, Job.run_at > now).label("later"),
            func.count().filter(Job.status == JobStatus.RUNNING).label("running"),
            func.min(Job.run_at).filter(Job.status == JobStatus.QUEUED, Job.run_at <= now),
        ).where(Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
    ).one()
    oldest_due = row[3]
    return {
        "due": row.due,
        "scheduled_later": row.later,
        "running": row.running,
        # How long the oldest due job has been waiting: the queue's lag.
        "oldest_due_seconds": (
            round((_now() - oldest_due).total_seconds(), 1) if oldest_due else None
        ),
    }


def throughput(db: Session, window: timedelta = THROUGHPUT_WINDOW) -> list[dict[str, Any]]:
    """Per job kind over the window: finished jobs, failures and run time."""
    duration_ms = cast(Job.result["duration_ms"].astext, Float)
    rows = db.execute(
        select(
            Job.kind,
            func.count().label("finished"),
            func.count().filter(Job.status == JobStatus.SUCCEEDED).label("succeeded"),
            func.count().filter(Job.status == JobStatus.FAILED).label("failed"),
            func.avg(case((Job.status == JobStatus.SUCCEEDED, duration_ms))).label("avg_ms"),
            func.percentile_cont(0.95).within_group(duration_ms).label("p95_ms"),
            func.max(duration_ms).label("max_ms"),
        )
        .where(Job.finished_at >= _now() - window)
        .group_by(Job.kind)
        .order_by(func.count().desc())
    ).all()
    minutes = window.total_seconds() / 60
    return [
        {
            "kind": r.kind,
            "finished": r.finished,
            "succeeded": r.succeeded,
            "failed": r.failed,
            "per_minute": round(r.finished / minutes, 2),
            "avg_ms": round(r.avg_ms, 1) if r.avg_ms is not None else None,
            "p95_ms": round(r.p95_ms, 1) if r.p95_ms is not None else None,
            "max_ms": round(r.max_ms, 1) if r.max_ms is not None else None,
        }
        for r in rows
    ]


def workers(db: Session, limit: int = 20) -> list[dict[str, Any]]:
    """Workers seen recently, running ones first, with the job each one holds."""
    now = _now()
    found = db.execute(
        select(JobWorker)
        .where((JobWorker.stopped_at.is_(None)) | (JobWorker.stopped_at >= now - timedelta(days=1)))
        .order_by(JobWorker.stopped_at.is_not(None), JobWorker.last_seen_at.desc())
        .limit(limit)
    ).scalars()
    found = list(found)
    current = dict(
        db.execute(
            select(Job.locked_by, Job.kind).where(
                Job.status == JobStatus.RUNNING, Job.locked_by.in_([w.name for w in found])
            )
        ).all()
    )
    result = []
    for w in found:
        if w.stopped_at is not None:
            state = "stopped"
        elif now - w.last_seen_at > WORKER_LOST_AFTER:
            state = "lost"
        else:
            state = "running"
        result.append(
            {
                "name": w.name,
                "hostname": w.hostname,
                "pid": w.pid,
                "state": state,
                "started_at": w.started_at,
                "last_seen_at": w.last_seen_at,
                "stopped_at": w.stopped_at,
                "succeeded": w.succeeded,
                "failed": w.failed,
                "retried": w.retried,
                "current_job_kind": current.get(w.name),
            }
        )
    return result


def database(db: Session) -> dict[str, Any]:
    size, connections, hit = db.execute(
        text(
            "SELECT pg_database_size(current_database()), "
            "(SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()), "
            "(SELECT round(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 2) "
            " FROM pg_stat_database WHERE datname = current_database())"
        )
    ).one()
    return {
        "size_bytes": size,
        "connections": connections,
        "cache_hit_percent": float(hit) if hit is not None else None,
    }


def overview(db: Session) -> dict[str, Any]:
    settings = get_settings()
    return {
        "process": {
            "version": __version__,
            "pid": os.getpid(),
            "uptime_seconds": round(_now().timestamp() - REQUESTS.started),
            "jobs_execution": settings.jobs_execution,
            "slow_query_ms": settings.slow_query_ms,
        },
        "requests": REQUESTS.snapshot(),
        "queue": queue(db),
        "throughput": throughput(db),
        "workers": workers(db),
        "database": database(db),
    }


def slow_queries(db: Session, *, limit: int, grouped: bool) -> list[dict[str, Any]]:
    if not grouped:
        rows = db.execute(select(SlowQuery).order_by(SlowQuery.id.desc()).limit(limit)).scalars()
        return [
            {
                "occurred_at": r.occurred_at,
                "duration_ms": r.duration_ms,
                "statement": r.statement,
                "source": r.source,
                "context": r.context,
                "correlation_id": r.correlation_id,
            }
            for r in rows
        ]
    # The same statement (from the same route or job), however often it was slow.
    rows = db.execute(
        select(
            SlowQuery.statement,
            SlowQuery.context,
            func.count().label("count"),
            func.avg(SlowQuery.duration_ms).label("avg_ms"),
            func.max(SlowQuery.duration_ms).label("max_ms"),
            func.sum(SlowQuery.duration_ms).label("total_ms"),
            func.max(SlowQuery.occurred_at).label("last_seen"),
        )
        .group_by(SlowQuery.statement, SlowQuery.context)
        .order_by(func.sum(SlowQuery.duration_ms).desc())
        .limit(limit)
    ).all()
    return [
        {
            "statement": r.statement,
            "context": r.context,
            "count": r.count,
            "avg_ms": round(float(r.avg_ms), 1),
            "max_ms": r.max_ms,
            "total_ms": int(r.total_ms),
            "last_seen": r.last_seen,
        }
        for r in rows
    ]


def prometheus(db: Session) -> str:
    """Prometheus text format: this process's requests plus queue and worker gauges."""
    lines = REQUESTS.prometheus()
    q = queue(db)
    lines += gauge(
        "atlas_jobs",
        "Jobs waiting or running, by state.",
        [
            ({"state": "due"}, q["due"]),
            ({"state": "scheduled_later"}, q["scheduled_later"]),
            ({"state": "running"}, q["running"]),
        ],
    )
    lines += gauge(
        "atlas_jobs_oldest_due_seconds",
        "How long the oldest due job has waited (0 when none is due).",
        [({}, q["oldest_due_seconds"] or 0)],
    )
    rows = throughput(db)
    lines += gauge(
        "atlas_jobs_finished_last_hour",
        "Jobs finished in the last hour, by kind and outcome.",
        [({"kind": r["kind"], "outcome": "succeeded"}, r["succeeded"]) for r in rows]
        + [({"kind": r["kind"], "outcome": "failed"}, r["failed"]) for r in rows],
    )
    states: dict[str, int] = {"running": 0, "lost": 0}
    for w in workers(db, limit=1000):
        if w["state"] in states:
            states[w["state"]] += 1
    lines += gauge(
        "atlas_workers",
        "Worker processes by state.",
        [({"state": s}, n) for s, n in states.items()],
    )
    lines += gauge(
        "atlas_database_size_bytes", "Size of the database.", [({}, database(db)["size_bytes"])]
    )
    return "\n".join(lines) + "\n"
