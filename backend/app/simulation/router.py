import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import get_sessionmaker
from app.core.dependencies import DbSession
from app.core.pagination import Page, PageParamsDep
from app.core.permissions import Permission
from app.modules.identity.dependencies import Authorized
from app.simulation import runner, service
from app.simulation.models import SimulationStatus
from app.simulation.schemas import (
    CaseResultOut,
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


def _launch(
    db: Session, body: StartSimulation, actor_id: uuid.UUID, tasks: BackgroundTasks, factory
) -> SimulationRunDetail:
    run = service.start_run(db, body, actor_id)
    # The background task reads the run in its own session: make it visible first.
    db.commit()
    tasks.add_task(runner.execute_run, factory, run.id)
    return service.detail(db, run)


@router.post(
    "",
    response_model=SimulationRunDetail,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a simulation run (executes in the background)",
)
def start_run(
    body: StartSimulation,
    db: DbSession,
    actor: Authorized(Permission.SIMULATIONS_RUN),
    tasks: BackgroundTasks,
    factory: SessionFactory,
) -> SimulationRunDetail:
    return _launch(db, body, actor.id, tasks, factory)


@router.post(
    "/suites",
    response_model=list[SimulationRunSummary],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run several experiment modes on the same seed and workload, one after another",
)
def start_suite(
    body: StartSuite,
    db: DbSession,
    actor: Authorized(Permission.SIMULATIONS_RUN),
    tasks: BackgroundTasks,
    factory: SessionFactory,
) -> list[SimulationRunSummary]:
    runs = service.start_suite(db, body, actor.id)
    db.commit()
    tasks.add_task(runner.execute_batch, factory, [r.id for r in runs])
    names = {actor.id: actor.username}
    return [service.summary(r, names) for r in runs]


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
    db: DbSession,
    actor: Authorized(Permission.SIMULATIONS_RUN),
    tasks: BackgroundTasks,
    factory: SessionFactory,
) -> SimulationRunDetail:
    body = service.rerun_body(service.get_run(db, run_id))
    return _launch(db, body, actor.id, tasks, factory)


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
