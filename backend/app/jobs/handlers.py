"""The job kinds the platform runs in the background.

Each handler opens its own sessions from `ctx.factory`, so a long job never holds the
claim transaction, and returns a small JSON result stored on the job.
"""

import uuid
from dataclasses import asdict
from datetime import UTC, date, datetime

from sqlalchemy import select

from app.core.permissions import permissions_for
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
    from app.simulation import runner

    run_ids = [uuid.UUID(r) for r in ctx.payload["run_ids"]]
    runner.execute_batch(ctx.factory, run_ids)
    return {"runs": len(run_ids)}


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
