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
from app.modules.experiments import portfolios, report, series, service, thresholds
from app.modules.experiments.models import ExperimentStatus
from app.modules.experiments.schemas import (
    BenchmarkRow,
    ExperimentCreate,
    ExperimentDetail,
    ExperimentFromRuns,
    ExperimentSummary,
    PortfolioCreate,
    PortfolioDetail,
    PortfolioSummary,
    ReEvaluation,
    SeriesCreate,
    SeriesDetail,
    SeriesSummary,
    ThresholdDecision,
    ThresholdProposal,
)
from app.modules.identity.dependencies import Authorized
from app.simulation.router import SessionFactory, launch_idempotent

experiments_router = APIRouter(prefix="/experiments", tags=["experiments"])
series_router = APIRouter(prefix="/experiment-series", tags=["experiments"])
portfolio_router = APIRouter(prefix="/experiment-portfolios", tags=["experiments"])
benchmarks_router = APIRouter(prefix="/benchmarks", tags=["experiments"])
thresholds_router = APIRouter(prefix="/scenario-thresholds", tags=["experiments"])


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
    "/{experiment_id}/under-scenario-thresholds",
    summary="The evaluation recomputed under the scenario's thresholds in force now (Phase 80)",
)
def under_scenario_thresholds(
    experiment_id: uuid.UUID, db: DbSession, _: Authorized(Permission.EXPERIMENTS_READ)
) -> dict:
    result = thresholds.reassess(db, service.get(db, experiment_id))
    if result is None:
        raise ConflictError("The experiment has not been evaluated yet.")
    return result


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


# --- Repeated-seed series (Phase 77) ----------------------------------------------------------


@series_router.get("", response_model=Page[SeriesSummary], summary="Experiment series")
def list_series(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.EXPERIMENTS_READ),
    tool_id: Annotated[str | None, Query(max_length=64)] = None,
) -> Page[SeriesSummary]:
    items, total = series.list_series(db, page, tool_id=tool_id)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@series_router.post(
    "",
    response_model=SeriesDetail,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Repeat an experiment over several seeds, then test its effect across them",
)
def create_series(
    body: SeriesCreate,
    request: Request,
    db: DbSession,
    actor: Authorized(Permission.EXPERIMENTS_RUN),
    tasks: BackgroundTasks,
    factory: SessionFactory,
    idempotency_key: IdempotencyKey = None,
):
    def create():
        created = series.create(db, body, actor.id)
        job = jobs.enqueue(
            db,
            "experiment_series.execute",
            {
                "series_id": str(created.id),
                "run_ids": [str(r) for r in series.run_ids(db, created)],
            },  # fmt: skip
            created_by=actor.id,
        )
        return series.detail(db, created), [job.id]

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


@series_router.get("/{series_id}", response_model=SeriesDetail, summary="One experiment series")
def get_series(
    series_id: uuid.UUID, db: DbSession, _: Authorized(Permission.EXPERIMENTS_READ)
) -> SeriesDetail:
    return series.detail(db, series.get(db, series_id))


# --- Portfolios (Phase 78) ---------------------------------------------------------------------


@portfolio_router.get("", response_model=Page[PortfolioSummary], summary="Experiment portfolios")
def list_portfolios(
    db: DbSession, page: PageParamsDep, _: Authorized(Permission.EXPERIMENTS_READ)
) -> Page[PortfolioSummary]:
    items, total = portfolios.list_portfolios(db, page)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@portfolio_router.get(
    "/plan",
    summary="The scenarios a tool family would be evaluated on, and those it would not",
)
def plan_portfolio(
    db: DbSession,
    _: Authorized(Permission.EXPERIMENTS_READ),
    family: Annotated[str, Query(min_length=3, max_length=64)],
    candidate_mode: Literal["ai_assisted", "ai_automated"] = "ai_assisted",
) -> dict:
    cells, skipped = portfolios.plan(db, family, candidate_mode)
    return {"cells": cells, "skipped": skipped}


@portfolio_router.post(
    "",
    response_model=PortfolioDetail,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Evaluate a tool family on every scenario it serves, in each country",
)
def create_portfolio(
    body: PortfolioCreate,
    request: Request,
    db: DbSession,
    actor: Authorized(Permission.EXPERIMENTS_RUN),
    tasks: BackgroundTasks,
    factory: SessionFactory,
    idempotency_key: IdempotencyKey = None,
):
    def create():
        created = portfolios.create(db, body, actor.id)
        job = jobs.enqueue(
            db,
            "experiment_portfolio.execute",
            {
                "portfolio_id": str(created.id),
                "run_ids": [str(r) for r in portfolios.run_ids(db, created)],
            },  # fmt: skip
            created_by=actor.id,
        )
        return portfolios.detail(db, created), [job.id]

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


@portfolio_router.get(
    "/{portfolio_id}", response_model=PortfolioDetail, summary="One experiment portfolio"
)
def get_portfolio(
    portfolio_id: uuid.UUID, db: DbSession, _: Authorized(Permission.EXPERIMENTS_READ)
) -> PortfolioDetail:
    return portfolios.detail(db, portfolios.get(db, portfolio_id))


@portfolio_router.get(
    "/{portfolio_id}/under-scenario-thresholds",
    summary="The portfolio's cells re-judged under each scenario's thresholds (Phase 80)",
)
def portfolio_under_scenario_thresholds(
    portfolio_id: uuid.UUID, db: DbSession, _: Authorized(Permission.EXPERIMENTS_READ)
) -> dict:
    result = thresholds.reassess_portfolio(db, portfolios.get(db, portfolio_id))
    if result is None:
        raise ConflictError("The portfolio has not completed yet.")
    return result


# --- Scenario thresholds (Phase 80) ------------------------------------------------------------


@thresholds_router.get("", summary="The success thresholds in force for every AI scenario")
def list_thresholds(db: DbSession, _: Authorized(Permission.EXPERIMENTS_READ)) -> dict:
    return {
        "tiers": {
            tier: {"description": thresholds.TIER_DESCRIPTIONS[tier], **t.model_dump(mode="json")}
            for tier, t in thresholds.TIERS.items()
        },
        "scenarios": thresholds.overview(db),
    }


@thresholds_router.get("/{scenario_id}/history", summary="A scenario's threshold versions")
def threshold_history(
    scenario_id: str, db: DbSession, _: Authorized(Permission.EXPERIMENTS_READ)
) -> list[dict]:
    return thresholds.history(db, scenario_id)


@thresholds_router.post(
    "", status_code=status.HTTP_201_CREATED, summary="Propose a scenario's thresholds"
)
def propose_thresholds(
    body: ThresholdProposal, db: DbSession, actor: Authorized(Permission.EXPERIMENTS_RUN)
) -> dict:
    record = thresholds.propose(
        db,
        scenario_id=body.scenario_id,
        risk_tier=body.risk_tier,
        thresholds=body.thresholds,
        rationale=body.rationale,
        actor_id=actor.id,
    )
    return thresholds.version_out(db, record)


@thresholds_router.post(
    "/{record_id}/approve", summary="Approve proposed thresholds (not one's own); they apply"
)
def approve_thresholds(
    record_id: uuid.UUID,
    body: ThresholdDecision,
    db: DbSession,
    actor: Authorized(Permission.RISK_APPROVE),
) -> dict:
    return thresholds.version_out(db, thresholds.approve(db, record_id, actor.id, body.note))


@thresholds_router.post("/{record_id}/reject", summary="Reject proposed thresholds")
def reject_thresholds(
    record_id: uuid.UUID,
    body: ThresholdDecision,
    db: DbSession,
    actor: Authorized(Permission.RISK_APPROVE),
) -> dict:
    return thresholds.version_out(db, thresholds.reject(db, record_id, actor.id, body.note))
