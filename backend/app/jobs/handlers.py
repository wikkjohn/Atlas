"""The job kinds the platform runs in the background.

Each handler opens its own sessions from `ctx.factory`, so a long job never holds the
claim transaction, and returns a small JSON result stored on the job.
"""

import uuid
from dataclasses import asdict
from datetime import UTC, date, datetime

from sqlalchemy import select

from app.core.permissions import Permission, permissions_for
from app.jobs.engine import JobContext, PermanentJobError, job_kind
from app.modules.identity.models import User
from app.modules.identity.service import AuthenticatedUser
from app.modules.ledger.models import ReconciliationMode

SCHEDULER_USERNAME = "atlas-scheduler"


def _principal(ctx: JobContext) -> AuthenticatedUser:
    """Who the job acts as: the person who queued it, else the scheduler service account."""
    with ctx.factory() as db:
        query = (
            select(User).where(User.id == ctx.created_by)
            if ctx.created_by
            else select(User).where(User.username == SCHEDULER_USERNAME)
        )
        user = db.execute(query).scalar_one_or_none()
        if user is None or not user.is_active:
            raise PermanentJobError("The job's principal does not exist or is inactive.")
        return AuthenticatedUser(
            id=user.id,
            username=user.username,
            role=user.role.code,
            permissions=permissions_for(user.role.code),
        )


@job_kind(
    "ledger.reconcile",
    description="Reconcile the ledger (payload: mode = full | incremental)",
    max_attempts=2,
    manual=True,
)
def reconcile(ctx: JobContext) -> dict:
    from app.modules.ledger import service as ledger

    try:
        mode = ReconciliationMode(ctx.payload.get("mode", "incremental"))
    except ValueError as exc:
        raise PermanentJobError(f"Unknown reconciliation mode: {exc}") from exc
    with ctx.factory() as db, db.begin():
        report = ledger.reconcile(db, ctx.created_by, mode)
        return {
            "ok": report.ok,
            "mode": mode.value,
            "run_number": report.run_number,
            "entries_checked": report.entries_checked,
            "failed_checks": [c.name for c in report.checks if not c.passed],
        }


@job_kind(
    "workflows.run_due",
    description="Resume due workflow steps and apply timeouts",
    max_attempts=3,
    backoff_seconds=10,
    manual=True,
)
def run_due_workflows(ctx: JobContext) -> dict:
    from app.modules.workflows import engine as workflows

    return asdict(workflows.run_due(ctx.factory))


@job_kind(
    "lending.service_loans",
    description="Service the loan book up to a date (payload: as_of, default today)",
    max_attempts=2,
    manual=True,
)
def service_loans(ctx: JobContext) -> dict:
    from app.modules.lending import servicing

    try:
        as_of = date.fromisoformat(ctx.payload["as_of"]) if ctx.payload.get("as_of") else None
    except ValueError as exc:
        raise PermanentJobError(f"Invalid as_of date: {exc}") from exc
    as_of = as_of or datetime.now(UTC).date()
    actor = _principal(ctx)
    with ctx.factory() as db, db.begin():
        serviced_to = servicing.business_date(db)
        if serviced_to is not None and serviced_to >= as_of:
            # Scheduled runs move with the calendar; a book already serviced past today
            # (e.g. a demo ran ahead) is left alone rather than refused every day.
            return {"skipped": True, "business_date": serviced_to.isoformat()}
        record = servicing.run(db, as_of, actor)
        return {"run_number": record.run_number, "as_of": as_of.isoformat(), **record.summary}


@job_kind(
    "simulation.execute",
    description="Execute queued simulation runs one after another",
    max_attempts=1,  # an interrupted run is reported as interrupted, not re-run
)
def execute_simulations(ctx: JobContext) -> dict:
    from app.config import get_settings
    from app.jobs import engine
    from app.simulation import runner

    run_ids = [uuid.UUID(r) for r in ctx.payload["run_ids"]]
    shard_jobs = runner.execute_batch(ctx.factory, run_ids)
    if shard_jobs and get_settings().jobs_execution == "inline":
        # No worker processes: this process runs the shards itself, one after another.
        for job_id in shard_jobs:
            engine.run_now(ctx.factory, job_id)
    return {"runs": len(run_ids), "shard_jobs": len(shard_jobs)}


@job_kind(
    "simulation.shard",
    description="Simulate one shard of a sharded simulation run (payload: run_id, shard)",
    max_attempts=1,  # a shard that stops fails its run, like an interrupted run
)
def execute_simulation_shard(ctx: JobContext) -> dict:
    from app.simulation import runner

    try:
        run_id, shard = uuid.UUID(ctx.payload["run_id"]), int(ctx.payload["shard"])
    except (KeyError, ValueError) as exc:
        raise PermanentJobError("The payload needs run_id and shard.") from exc
    status = runner.execute_shard(ctx.factory, run_id, shard, worker=ctx.worker)
    return {"shard": shard, "status": status}


@job_kind(
    "experiment.execute",
    description="Run an experiment's baseline and candidate, then evaluate",
    max_attempts=1,
)
def execute_experiment(ctx: JobContext) -> dict:
    from app.modules.experiments import service

    experiment_id = uuid.UUID(ctx.payload["experiment_id"])
    run_ids = [uuid.UUID(r) for r in ctx.payload["run_ids"]]
    service.execute(ctx.factory, experiment_id, run_ids)
    return {"experiment_id": str(experiment_id)}


@job_kind(
    "system.ping",
    description="Does nothing: shows that a worker is picking up jobs",
    max_attempts=1,
    manual=True,
)
def ping(ctx: JobContext) -> dict:
    return {"pong": True}


def _run_id(ctx: JobContext) -> uuid.UUID:
    try:
        return uuid.UUID(ctx.payload["run_id"])
    except (KeyError, ValueError) as exc:
        raise PermanentJobError("The payload needs a run_id.") from exc


@job_kind(
    "simulation.archive_history",
    description="Archive a simulation run's workflow history to files (payload: run_id)",
    max_attempts=1,
)
def archive_history(ctx: JobContext) -> dict:
    from app.core.errors import DomainError
    from app.simulation import history

    try:
        record = history.archive_run(ctx.factory, _run_id(ctx), ctx.created_by)
    except DomainError as exc:  # e.g. already archived: retrying would not help
        raise PermanentJobError(exc.message) from exc
    return {"run_number": record.manifest["run_number"], "rows": record.rows, "bytes": record.bytes}


@job_kind(
    "simulation.restore_history",
    description="Restore an archived simulation run's workflow history (payload: run_id)",
    max_attempts=1,
)
def restore_history(ctx: JobContext) -> dict:
    from app.core.errors import DomainError
    from app.simulation import history

    try:
        record = history.restore_run(ctx.factory, _run_id(ctx), ctx.created_by)
    except DomainError as exc:
        raise PermanentJobError(exc.message) from exc
    return {"run_number": record.manifest["run_number"], "rows": record.rows}


@job_kind(
    "simulation.archive_old",
    description="Archive the workflow history of finished simulation runs older than "
    "older_than_days (default 30)",
    max_attempts=2,
    manual=True,
)
def archive_old_history(ctx: JobContext) -> dict:
    from app.simulation import history

    days = ctx.payload.get("older_than_days", 30)
    if not isinstance(days, int) or days < 0:
        raise PermanentJobError("older_than_days must be a whole number of days, 0 or more.")
    actor = ctx.created_by or _principal(ctx).id
    archived = history.archive_older_than(ctx.factory, days, actor)
    return {"archived_runs": archived}


@job_kind(
    "fx.daily",
    description="Publish the day's exchange rates and revalue the open currency positions "
    "(payload: as_of, default today)",
    max_attempts=2,
    manual=True,
)
def fx_daily(ctx: JobContext) -> dict:
    from app.modules.fx import service as fx

    as_of = date.fromisoformat(ctx.payload["as_of"]) if ctx.payload.get("as_of") else None
    as_of = as_of or datetime.now(UTC).date()
    principal = _principal(ctx)
    if not principal.can(Permission.FX_MANAGE):
        raise PermanentJobError("The job's principal may not revalue currency positions.")
    with ctx.factory() as db, db.begin():
        published = fx.publish_rates(db, as_of)
        run = fx.revalue(db, as_of, principal.id)
        return {
            "as_of": as_of.isoformat(),
            "rates_published": published,
            "revaluation": run.run_number,
            "posted_usd_cents": run.posted,
        }


@job_kind(
    "organizations.generate",
    description="Launch countries and build their subsidiaries from the blueprint "
    "(payload: country_codes, staff)",
    max_attempts=1,
)
def generate_subsidiaries(ctx: JobContext) -> dict:
    from app.core.errors import DomainError
    from app.modules.countries.models import Country
    from app.modules.organizations import blueprint

    principal = _principal(ctx)
    if not principal.can(Permission.ORGANIZATIONS_MANAGE):
        raise PermanentJobError("The job's principal may not create organizations.")
    codes = ctx.payload.get("country_codes")
    if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
        raise PermanentJobError("country_codes must be a list of country codes.")
    staff = bool(ctx.payload.get("staff", True))
    totals = {"organizations_created": 0, "employees_hired": 0}
    launched, failed = [], {}
    # One transaction per country: a failure leaves the countries before it in place.
    for code in codes:
        try:
            with ctx.factory() as db, db.begin():
                country = db.execute(
                    select(Country).where(Country.iso_country_code == code)
                ).scalar_one()
                result = blueprint.launch_country(db, country, principal.id, staff=staff)
        except DomainError as exc:
            failed[code] = exc.message
            continue
        launched.append(code)
        totals["organizations_created"] += result.organizations_created
        totals["employees_hired"] += result.employees_hired
    return {"countries": len(codes), "launched": launched, "failed": failed, **totals}
