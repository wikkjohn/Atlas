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
    CalibrationCreate,
    CalibrationSummary,
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


# --- Reviewer calibration (Phase 82) -----------------------------------------------------------

calibrations_router = APIRouter(prefix="/reviewer-calibrations", tags=["simulations"])


def _calibration_out(db: Session, record) -> CalibrationSummary:
    from app.modules.identity.models import User
    from app.simulation import calibration
    from app.simulation.scenarios import get_scenario

    scenario = get_scenario(record.scenario_id)
    creator = db.get(User, record.created_by)
    return CalibrationSummary(
        id=record.id,
        calibration_number=record.calibration_number,
        scenario_id=record.scenario_id,
        step_id=record.step_id,
        source=record.source,
        observation_count=record.observation_count,
        data_digest=record.data_digest,
        status=record.status,
        fitted=calibration.public(record.fitted),
        assumption=calibration.assumption(scenario, record.step_id)
        if scenario and record.step_id in scenario.config.reviewers
        else {},
        created_by_username=creator.username if creator else None,
        created_at=record.created_at,
    )


@calibrations_router.get(
    "", response_model=list[CalibrationSummary], summary="Reviewer calibrations, newest first"
)
def list_calibrations(
    db: DbSession,
    _: Authorized(Permission.SIMULATIONS_READ),
    scenario_id: Annotated[str | None, Query(max_length=64)] = None,
    status_filter: Annotated[
        str | None, Query(alias="status", pattern="^(active|superseded)$")
    ] = None,
) -> list[CalibrationSummary]:
    from sqlalchemy import select

    from app.simulation.models import ReviewerCalibration

    query = select(ReviewerCalibration).order_by(ReviewerCalibration.calibration_number.desc())
    if scenario_id:
        query = query.where(ReviewerCalibration.scenario_id == scenario_id)
    if status_filter:
        query = query.where(ReviewerCalibration.status == status_filter)
    return [_calibration_out(db, r) for r in db.execute(query.limit(200)).scalars()]


@calibrations_router.post(
    "",
    response_model=CalibrationSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Fit a review step's reviewers from observed reviews; becomes the active one",
)
def create_calibration(
    body: CalibrationCreate, db: DbSession, actor: Authorized(Permission.EXPERIMENTS_RUN)
) -> CalibrationSummary:
    from app.core.errors import BusinessRuleViolation, NotFoundError
    from app.simulation import calibration
    from app.simulation.scenarios import get_scenario

    scenario = get_scenario(body.scenario_id)
    if scenario is None:
        raise NotFoundError(f"Scenario '{body.scenario_id}' not found.")
    try:
        record = calibration.calibrate(
            db,
            scenario=scenario,
            step_id=body.step_id,
            source=body.source,
            observations=[o.model_dump() for o in body.observations],
            actor_id=actor.id,
        )
    except ValueError as exc:
        raise BusinessRuleViolation(str(exc)) from exc
    return _calibration_out(db, record)


@calibrations_router.get(
    "/{calibration_id}", response_model=CalibrationSummary, summary="One reviewer calibration"
)
def get_calibration(
    calibration_id: uuid.UUID, db: DbSession, _: Authorized(Permission.SIMULATIONS_READ)
) -> CalibrationSummary:
    from app.core.errors import NotFoundError
    from app.simulation.models import ReviewerCalibration

    record = db.get(ReviewerCalibration, calibration_id)
    if record is None:
        raise NotFoundError("Reviewer calibration not found.")
    return _calibration_out(db, record)
