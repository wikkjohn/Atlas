"""Performance suite: the platform's key paths measured against recorded targets.

    python -m app.cli perf            # full profile (a few minutes)
    python -m app.cli perf --quick    # smaller sizes, looser targets (CI)

Each benchmark measures one number and compares it with its target. The targets are set
below what the development container measured (4 vCPUs, PostgreSQL on the same host; see
docs/performance.md), so a miss means a real regression rather than noise. The suite
writes synthetic data (ledger accounts and entries coded BENCH-…, jobs, simulation runs)
into the configured database: point it at a scratch database, never production.
"""

import json
import os
import platform
import statistics
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import __version__
from app.config import get_settings

Profile = Literal["quick", "full"]


@dataclass(frozen=True)
class Target:
    """At least `minimum` (throughput) or at most `maximum` (latency), per profile."""

    unit: str
    minimum: dict[str, float] = field(default_factory=dict)
    maximum: dict[str, float] = field(default_factory=dict)

    def met(self, profile: Profile, value: float) -> bool | None:
        if profile in self.minimum:
            return value >= self.minimum[profile]
        if profile in self.maximum:
            return value <= self.maximum[profile]
        return None  # recorded, not judged

    def describe(self, profile: Profile) -> str:
        if profile in self.minimum:
            return f">= {self.minimum[profile]:g} {self.unit}"
        if profile in self.maximum:
            return f"<= {self.maximum[profile]:g} {self.unit}"
        return "recorded"


@dataclass
class Result:
    name: str
    description: str
    value: float | None
    unit: str
    target: str
    ok: bool | None
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class Benchmark:
    name: str
    description: str
    target: Target
    run: Callable[["Context"], tuple[float, dict[str, Any]]]
    profiles: tuple[Profile, ...] = ("quick", "full")


@dataclass
class Context:
    factory: sessionmaker[Session]
    profile: Profile

    def size(self, quick: int, full: int) -> int:
        return quick if self.profile == "quick" else full


# --- Benchmarks -----------------------------------------------------------------------------


def _ledger(ctx: Context, bulk: bool) -> tuple[float, dict[str, Any]]:
    from app.modules.ledger import benchmark

    report = benchmark.run(
        ctx.factory,
        accounts=ctx.size(100, 500),
        entries=ctx.size(1_000, 5_000),
        hot_share=0.3,
        bulk=bulk,
    )
    return report["posting"]["entries_per_second"], {
        "balances_agree": report["balances_agree"],
        "hot_account_balance_ms": report["hot_account_balance"]["stored"]["median_ms"],
    }


def _admin_headers(db: Session) -> dict[str, str]:
    from datetime import timedelta

    from app.core.security import create_access_token
    from app.modules.identity.models import User

    admin = db.execute(select(User).where(User.username == "admin")).scalar_one_or_none()
    if admin is None:
        raise RuntimeError("No 'admin' user: run `python -m app.cli seed-demo` first.")
    secret = get_settings().jwt_secret.get_secret_value()
    token = create_access_token(admin.id, secret, timedelta(minutes=30)).token
    return {"Authorization": f"Bearer {token}"}


async def _asgi_get(app: Any, path: str, headers: dict[str, str]) -> int:
    """One GET straight into the ASGI application (no server, no test client): the time
    the platform itself takes, without network or HTTP parsing."""
    status = 0

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"perf")]
        + [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("127.0.0.1", 0),
        "server": ("perf", 80),
    }
    await app(scope, receive, send)
    return status


def _api(path: str) -> Callable[[Context], tuple[float, dict[str, Any]]]:
    def measure(ctx: Context) -> tuple[float, dict[str, Any]]:
        import asyncio

        from app.main import create_app

        with ctx.factory() as db:
            headers = _admin_headers(db)
        app = create_app()
        samples = []
        for i in range(ctx.size(20, 60) + 3):
            start = time.perf_counter()
            status = asyncio.run(_asgi_get(app, path, headers))
            elapsed = (time.perf_counter() - start) * 1000
            if status != 200:
                raise RuntimeError(f"GET {path} returned {status}")
            if i >= 3:  # the first requests warm caches and pools
                samples.append(elapsed)
        ordered = sorted(samples)
        p95 = ordered[max(0, round(0.95 * len(ordered)) - 1)]
        return round(p95, 1), {"median_ms": round(statistics.median(samples), 1)}

    return measure


def _jobs(ctx: Context) -> tuple[float, dict[str, Any]]:
    from app.jobs import engine, handlers  # noqa: F401  (registers system.ping)

    count = ctx.size(200, 1_000)
    with ctx.factory() as db, db.begin():
        for _ in range(count):
            engine.enqueue(db, "system.ping", {})
    start = time.perf_counter()
    stats = engine.run_worker(ctx.factory, schedules=False, idle_exit=True, poll_seconds=0.05)
    seconds = time.perf_counter() - start
    return round(stats.succeeded / seconds, 1), {
        "jobs": stats.succeeded,
        "seconds": round(seconds, 2),
    }


def _simulation(shards: int) -> Callable[[Context], tuple[float, dict[str, Any]]]:
    def measure(ctx: Context) -> tuple[float, dict[str, Any]]:
        from app.modules.identity.models import User
        from app.simulation import runner, service
        from app.simulation.models import SimulationRun, SimulationStatus
        from app.simulation.schemas import StartSimulation

        applications = ctx.size(60, 400) * shards
        with ctx.factory() as db, db.begin():
            admin = db.execute(select(User).where(User.username == "admin")).scalar_one()
            body = StartSimulation(
                profile="custom",
                applications=applications,
                employees=max(12, applications // 20),
                seed=2026,
                shards=shards,
            )
            run_id = service.start_run(db, body, admin.id).id
        jobs = runner.execute_run(ctx.factory, run_id)
        if jobs:
            from app.cli import _run_workers

            _run_workers(shards)
        with ctx.factory() as db:
            run = db.get(SimulationRun, run_id)
            assert run is not None
            if run.status != SimulationStatus.COMPLETED:
                raise RuntimeError(f"Run {run.run_number} {run.status}: {run.failure_reason}")
            seconds = (run.wall_ms or 1) / 1000
            return round(applications / seconds, 2), {
                "run": run.run_number,
                "cases": applications,
                "seconds": round(seconds, 1),
            }

    return measure


BENCHMARKS: tuple[Benchmark, ...] = (
    Benchmark(
        "ledger.posting",
        "Single-entry postings through post_entry (30 % on one hot account)",
        Target("entries/s", minimum={"quick": 60, "full": 120}),
        lambda ctx: _ledger(ctx, bulk=False),
    ),
    Benchmark(
        "ledger.bulk_posting",
        "Bulk postings through post_entries (COPY)",
        Target("entries/s", minimum={"quick": 500, "full": 1_500}),
        lambda ctx: _ledger(ctx, bulk=True),
    ),
    Benchmark(
        "api.customers",
        "GET /api/v1/customers (first page), p95",
        Target("ms", maximum={"quick": 400, "full": 150}),
        _api("/api/v1/customers"),
    ),
    Benchmark(
        "api.task_inbox",
        "GET /api/v1/workflow-tasks, p95",
        Target("ms", maximum={"quick": 400, "full": 150}),
        _api("/api/v1/workflow-tasks"),
    ),
    Benchmark(
        "api.dashboard",
        "GET /api/v1/analytics/overview, p95",
        Target("ms", maximum={"quick": 1_500, "full": 600}),
        _api("/api/v1/analytics/overview"),
    ),
    Benchmark(
        "jobs.throughput",
        "Job queue: system.ping jobs drained by one worker",
        Target("jobs/s", minimum={"quick": 30, "full": 60}),
        _jobs,
    ),
    Benchmark(
        "simulation.single",
        "Retail onboarding simulation in one process",
        Target("cases/s", minimum={"quick": 1.5, "full": 3}),
        _simulation(1),
    ),
    Benchmark(
        "simulation.sharded",
        "Retail onboarding simulation in 4 shards and 4 worker processes",
        Target("cases/s", minimum={"full": 7}),
        _simulation(4),
        profiles=("full",),
    ),
)


def run(
    factory: sessionmaker[Session], profile: Profile, only: list[str] | None = None
) -> dict[str, Any]:
    if get_settings().environment == "production":
        raise RuntimeError("The performance suite writes synthetic data; not in production.")
    ctx = Context(factory=factory, profile=profile)
    results = []
    for bench in BENCHMARKS:
        if profile not in bench.profiles or (only and bench.name not in only):
            continue
        start = time.perf_counter()
        try:
            value, detail = bench.run(ctx)
            ok = bench.target.met(profile, value)
            results.append(
                Result(
                    bench.name,
                    bench.description,
                    value,
                    bench.target.unit,
                    bench.target.describe(profile),
                    ok,
                    detail,
                )
            )
        except Exception as exc:  # recorded; the suite carries on
            results.append(
                Result(
                    bench.name,
                    bench.description,
                    None,
                    bench.target.unit,
                    bench.target.describe(profile),
                    False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
        results[-1].detail["seconds"] = round(time.perf_counter() - start, 1)
    return {
        "suite": "atlas-performance",
        "profile": profile,
        "version": __version__,
        "run_id": str(uuid.uuid4()),
        "started_at": datetime.now(UTC).isoformat(),
        "machine": {"cpus": os.cpu_count(), "python": platform.python_version()},
        "passed": all(r.ok is not False for r in results),
        "results": [asdict(r) for r in results],
    }


def render(report: dict[str, Any]) -> str:
    lines = [f"Performance suite ({report['profile']}), ATLAS {report['version']}", ""]
    for r in report["results"]:
        mark = {True: "ok  ", False: "MISS", None: "    "}[r["ok"]]
        value = f"{r['value']:g} {r['unit']}" if r["value"] is not None else "error"
        lines.append(f"  {mark}  {r['name']:<22} {value:>16}   target {r['target']}")
        if r["error"]:
            lines.append(f"        {r['error']}")
    lines += ["", "PASSED" if report["passed"] else "FAILED: a target was missed"]
    return "\n".join(lines)


def save(report: dict[str, Any], path: str) -> None:
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
