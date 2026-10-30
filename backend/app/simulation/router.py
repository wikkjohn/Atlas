import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, RootModel
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import get_sessionmaker
from app.core.dependencies import DbSession
from app.core.idempotency import IdempotencyKey, run_idempotent
from app.core.pagination import Page, PageParamsDep
from app.core.permissions import Permission
from app.jobs import engine as jobs
from app.modules.identity.dependencies import Authorized
from app.simulation import history, service
from app.simulation.models import SimulationRun, SimulationStatus
from app.simulation.schemas import (
    CaseResultOut,
    HistoryOverview,
    ProfileOut,
    ScenarioOut,
    SimulationRunDetail,
    SimulationRunSummary,
    StartSimulation,
    StartSuite,
)

router = APIRouter(prefix="/simulations", tags=["simulations"])


def get_simulation_sessionmaker() -> sessionmaker[Session]:
    """Sessions for background runs (tests substitute their own connection)."""
    return get_sessionmaker()


SessionFactory = Annotated[sessionmaker[Session], Depends(get_simulation_sessionmaker)]


@router.get("/scenarios", response_model=list[ScenarioOut], summary="Registered scenarios")
def list_scenarios(_: Authorized(Permission.SIMULATIONS_READ)) -> list[ScenarioOut]:
    return service.scenarios()


@router.get("/profiles", response_model=list[ProfileOut], summary="Workload profiles")
def list_profiles(_: Authorized(Permission.SIMULATIONS_READ)) -> list[ProfileOut]:
    return service.profiles()


@router.get("", response_model=Page[SimulationRunSummary], summary="Simulation run registry")
def list_runs(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.SIMULATIONS_READ),
    status: SimulationStatus | None = None,
    batch_id: uuid.UUID | None = None,
    mode: Annotated[str | None, Query(max_length=20)] = None,
) -> Page[SimulationRunSummary]:
    service.reap_stale(db)
    items, total = service.list_runs(db, page, status=status, batch_id=batch_id, mode=mode)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/history",
    response_model=HistoryOverview,
    summary="Storage used by workflow history (live and simulated) and recent archives",
)
def history_overview(
    db: DbSession, _: Authorized(Permission.SIMULATIONS_MANAGE)
) -> HistoryOverview:
    return service.history_overview(db)


class SuiteRuns(RootModel[list[SimulationRunSummary]]):
    pass


def launch_idempotent(
    db: Session,
    request: Request,
    *,
    key: str | None,
    actor_id: uuid.UUID,
    payload: BaseModel,
    create,
    schedule,
) -> JSONResponse:
    """Create work and its background job, at most once per Idempotency-Key.

    `create` returns (response, job ids) after queueing the job in the same transaction,
    so the work, its job and the stored response commit together. `schedule` then runs the
    jobs in this process unless dedicated workers take them; a replay starts nothing.
    """
    started: list = []

    def operation() -> BaseModel:
        response, ids = create()
        started.extend(ids)
        return response

    response = run_idempotent(
        db,
        key=key,
        actor_id=actor_id,
        method="POST",
        path=request.url.path,
        payload=payload,
        status_code=status.HTTP_202_ACCEPTED,
        operation=operation,
    )
    # The background task reads the new rows in its own session: make them visible first.
    db.commit()
    if started:
        schedule(started)
    return response


def _launch(
    db: Session,
    request: Request,
    body: StartSimulation,
    actor_id: uuid.UUID,
    tasks: BackgroundTasks,
    factory,
    key: str | None,
) -> JSONResponse:
    def create():
        run = service.start_run(db, body, actor_id)
        job = jobs.enqueue(
            db, "simulation.execute", {"run_ids": [str(run.id)]}, created_by=actor_id
        )
        return service.detail(db, run), [job.id]

    return launch_idempotent(
        db,
        request,
        key=key,
        actor_id=actor_id,
        payload=body,
        create=create,
        schedule=lambda job_ids: jobs.dispatch(tasks, factory, job_ids),
    )


@router.post(
    "",
    response_model=SimulationRunDetail,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a simulation run (executes in the background)",
)
def start_run(
    body: StartSimulation,
    request: Request,
    db: DbSession,
    actor: Authorized(Permission.SIMULATIONS_RUN),
    tasks: BackgroundTasks,
    factory: SessionFactory,
    idempotency_key: IdempotencyKey = None,
):
    return _launch(db, request, body, actor.id, tasks, factory, idempotency_key)


@router.post(
    "/suites",
    response_model=list[SimulationRunSummary],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run several experiment modes on the same seed and workload, one after another",
)
def start_suite(
    body: StartSuite,
    request: Request,
    db: DbSession,
    actor: Authorized(Permission.SIMULATIONS_RUN),
    tasks: BackgroundTasks,
    factory: SessionFactory,
    idempotency_key: IdempotencyKey = None,
):
    def create():
        runs = service.start_suite(db, body, actor.id)
        names = {actor.id: actor.username}
        job = jobs.enqueue(
            db, "simulation.execute", {"run_ids": [str(r.id) for r in runs]}, created_by=actor.id
        )
        return SuiteRuns([service.summary(r, names) for r in runs]), [job.id]

    return launch_idempotent(
        db,
        request,
        key=idempotency_key,
        actor_id=actor.id,
        payload=body,
        create=create,
        schedule=lambda job_ids: jobs.dispatch(tasks, factory, job_ids),
    )


@router.get("/{run_id}", response_model=SimulationRunDetail, summary="A run with its results")
def get_run(
    run_id: uuid.UUID, db: DbSession, _: Authorized(Permission.SIMULATIONS_READ)
) -> SimulationRunDetail:
    service.reap_stale(db)
    return service.detail(db, service.get_run(db, run_id))


@router.post(
    "/{run_id}/rerun",
    response_model=SimulationRunDetail,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run again with the same scenario, profile and seed (reproducibility check)",
)
def rerun(
    run_id: uuid.UUID,
    request: Request,
    db: DbSession,
    actor: Authorized(Permission.SIMULATIONS_RUN),
    tasks: BackgroundTasks,
    factory: SessionFactory,
    idempotency_key: IdempotencyKey = None,
):
    body = service.rerun_body(service.get_run(db, run_id))
    return _launch(db, request, body, actor.id, tasks, factory, idempotency_key)


@router.get(
    "/{run_id}/cases",
    response_model=Page[CaseResultOut],
    summary="Per-case results next to their ground truth",
)
def list_cases(
    run_id: uuid.UUID,
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.SIMULATIONS_READ),
    kind: Annotated[str | None, Query(max_length=40)] = None,
    mismatched: Annotated[
        bool, Query(description="Only cases whose outcome differs from the ground truth")
    ] = False,
) -> Page[CaseResultOut]:
    service.get_run(db, run_id)
    items, total = service.list_cases(db, run_id, page, kind=kind, mismatched=mismatched)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


class QueuedJob(BaseModel):
    job_id: uuid.UUID
    job_number: int
    kind: str
    status: str


def _queue_history_job(
    db: Session, kind: str, run: SimulationRun, actor_id: uuid.UUID, tasks, factory
) -> QueuedJob:
    # One archive or restore per run at a time.
    job = jobs.enqueue(
        db,
        kind,
        {"run_id": str(run.id)},
        created_by=actor_id,
        dedupe_key=f"simulation-history:{run.id}",
    )
    db.commit()
    jobs.dispatch(tasks, factory, [job.id])
    return QueuedJob(job_id=job.id, job_number=job.job_number, kind=job.kind, status=job.status)


@router.post(
    "/{run_id}/archive",
    response_model=QueuedJob,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Archive the run's workflow history to files (a background job); results stay",
)
def archive_history(
    run_id: uuid.UUID,
    db: DbSession,
    actor: Authorized(Permission.SIMULATIONS_MANAGE),
    tasks: BackgroundTasks,
    factory: SessionFactory,
) -> QueuedJob:
    run = service.get_run(db, run_id)
    history.check_archivable(db, run)  # refuse now rather than in a failed job
    return _queue_history_job(db, "simulation.archive_history", run, actor.id, tasks, factory)


@router.post(
    "/{run_id}/restore",
    response_model=QueuedJob,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Restore the run's archived workflow history (a background job)",
)
def restore_history(
    run_id: uuid.UUID,
    db: DbSession,
    actor: Authorized(Permission.SIMULATIONS_MANAGE),
    tasks: BackgroundTasks,
    factory: SessionFactory,
) -> QueuedJob:
    run = service.get_run(db, run_id)
    history.check_restorable(run)
    return _queue_history_job(db, "simulation.restore_history", run, actor.id, tasks, factory)
