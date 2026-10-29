import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Query, Request, status
from fastapi.responses import JSONResponse, Response

from app.core.dependencies import DbSession
from app.core.errors import ConflictError
from app.core.idempotency import IdempotencyKey, run_idempotent
from app.core.pagination import Page, PageParamsDep
from app.core.permissions import Permission
from app.jobs import engine as jobs
from app.modules.experiments import report, service
from app.modules.experiments.models import ExperimentStatus
from app.modules.experiments.schemas import (
    BenchmarkRow,
    ExperimentCreate,
    ExperimentDetail,
    ExperimentFromRuns,
    ExperimentSummary,
    ReEvaluation,
)
from app.modules.identity.dependencies import Authorized
from app.simulation.router import SessionFactory, launch_idempotent

experiments_router = APIRouter(prefix="/experiments", tags=["experiments"])
benchmarks_router = APIRouter(prefix="/benchmarks", tags=["experiments"])


@experiments_router.get("", response_model=Page[ExperimentSummary], summary="Experiments")
def list_experiments(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.EXPERIMENTS_READ),
    status: ExperimentStatus | None = None,
    tool_id: Annotated[str | None, Query(max_length=64)] = None,
) -> Page[ExperimentSummary]:
    items, total = service.list_experiments(db, page, status=status, tool_id=tool_id)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@experiments_router.post(
    "",
    response_model=ExperimentDetail,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run a baseline and a candidate on the same workload, then evaluate",
)
def create_experiment(
    body: ExperimentCreate,
    request: Request,
    db: DbSession,
    actor: Authorized(Permission.EXPERIMENTS_RUN),
    tasks: BackgroundTasks,
    factory: SessionFactory,
    idempotency_key: IdempotencyKey = None,
):
    def create():
        experiment = service.create(db, body, actor.id)
        runs = [experiment.baseline_run_id, experiment.candidate_run_id]
        job = jobs.enqueue(
            db,
            "experiment.execute",
            {"experiment_id": str(experiment.id), "run_ids": [str(r) for r in runs]},
            created_by=actor.id,
        )
        return service.detail(db, experiment), [job.id]

    def schedule(job_ids: list) -> None:
        jobs.dispatch(tasks, factory, job_ids)

    return launch_idempotent(
        db,
        request,
        key=idempotency_key,
        actor_id=actor.id,
        payload=body,
        create=create,
        schedule=schedule,
    )


@experiments_router.post(
    "/from-runs",
    response_model=ExperimentDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Evaluate two completed, equivalent runs (e.g. with other cost assumptions)",
)
def create_from_runs(
    body: ExperimentFromRuns,
    request: Request,
    db: DbSession,
    actor: Authorized(Permission.EXPERIMENTS_RUN),
    idempotency_key: IdempotencyKey = None,
):
    return run_idempotent(
        db,
        key=idempotency_key,
        actor_id=actor.id,
        method="POST",
        path=request.url.path,
        payload=body,
        status_code=status.HTTP_201_CREATED,
        operation=lambda: service.detail(db, service.create_from_runs(db, body, actor.id)),
    )


@experiments_router.get("/{experiment_id}", response_model=ExperimentDetail)
def get_experiment(
    experiment_id: uuid.UUID, db: DbSession, _: Authorized(Permission.EXPERIMENTS_READ)
) -> ExperimentDetail:
    return service.detail(db, service.get(db, experiment_id))


@experiments_router.post(
    "/{experiment_id}/re-evaluate",
    response_model=ReEvaluation,
    summary="Recompute the evaluation from the stored raw measurements",
)
def re_evaluate(
    experiment_id: uuid.UUID, db: DbSession, _: Authorized(Permission.EXPERIMENTS_READ)
) -> ReEvaluation:
    return service.re_evaluate(db, service.get(db, experiment_id))


@experiments_router.get(
    "/{experiment_id}/report",
    summary="Exportable proof-of-concept report",
    responses={200: {"content": {"text/markdown": {}, "application/json": {}}}},
)
def get_report(
    experiment_id: uuid.UUID,
    db: DbSession,
    _: Authorized(Permission.EXPERIMENTS_READ),
    format: Literal["markdown", "json"] = "markdown",
) -> Response:
    detail = service.detail(db, service.get(db, experiment_id))
    if detail.evaluation is None:
        raise ConflictError(
            f"Experiment #{detail.experiment_number} is {detail.status}; "
            "only evaluated experiments have a report."
        )
    filename = f"atlas-experiment-{detail.experiment_number}"
    if format == "json":
        return JSONResponse(
            detail.model_dump(mode="json"),
            headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
        )
    return Response(
        report.markdown(detail),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}.md"'},
    )


@benchmarks_router.get(
    "",
    response_model=list[BenchmarkRow],
    summary="Completed experiments by tool version and mode",
)
def list_benchmarks(
    db: DbSession, _: Authorized(Permission.EXPERIMENTS_READ)
) -> list[BenchmarkRow]:
    return service.benchmarks(db)
