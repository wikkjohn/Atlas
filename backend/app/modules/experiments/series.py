"""Repeated-seed experiment series (Phase 77, roadmap Milestone G step 2).

A series runs the same experiment (scenario, tool, mode, sizes, assumptions) once per seed.
Each replicate is an ordinary experiment, measured and evaluated as before; when all have
completed, the series computes statistics across them (`significance.series_statistics`):
per metric the mean paired difference, its confidence interval and a Holm-adjusted
significance test. A failed replicate fails the series: statistics over the seeds that
happened to succeed would not be the series that was asked for.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import BusinessRuleViolation, NotFoundError
from app.core.pagination import PageParams, paginate
from app.modules.experiments import service
from app.modules.experiments.models import (
    Experiment,
    ExperimentEvaluation,
    ExperimentSeries,
    ExperimentStatus,
)
from app.modules.experiments.schemas import (
    ExperimentCreate,
    SeriesCreate,
    SeriesDetail,
    SeriesSummary,
)
from app.modules.experiments.significance import series_statistics
from app.modules.identity.models import User
from app.simulation import runner
from app.simulation import service as simulations
from app.simulation.schemas import MAX_SEED

logger = logging.getLogger("atlas.experiments")


def create(db: Session, body: SeriesCreate, actor_id: uuid.UUID) -> ExperimentSeries:
    """Queue one baseline and one candidate run per seed."""
    seeds = body.seed_list()
    if max(seeds) > MAX_SEED:
        raise BusinessRuleViolation(f"Seeds must stay at or below {MAX_SEED}.")
    if body.profile == "custom" and (body.applications is None or body.employees is None):
        raise BusinessRuleViolation("A custom series needs both applications and employees.")
    simulations.reap_stale(db)
    simulations._ensure_idle(db)  # once: the series' own runs then queue behind each other
    config, config_hash = service._config(body.costs, body.thresholds)
    series = ExperimentSeries(
        name=body.name.strip(),
        scenario_id=body.scenario_id,
        scenario_version=body.scenario_version or 0,
        candidate_mode=body.candidate_mode,
        seeds=seeds,
        confidence=body.confidence,
        configuration=config,
        configuration_hash=config_hash,
        status=ExperimentStatus.RUNNING.value,
        created_by=actor_id,
    )
    db.add(series)
    db.flush()
    fields = body.model_dump(
        include={
            "scenario_id",
            "scenario_version",
            "tool_id",
            "tool_version",
            "candidate_mode",
            "profile",
            "applications",
            "employees",
            "costs",
            "thresholds",
        }  # fmt: skip
    )
    for seed in seeds:
        experiment = service.create(
            db,
            ExperimentCreate(name=f"{series.name} · seed {seed}", seed=seed, **fields),
            actor_id,
            series_id=series.id,
            check_idle=False,
        )
    # The replicates resolved the scenario version and the tool: the series records them.
    series.scenario_version = experiment.scenario_version
    series.tool_record_id = experiment.tool_record_id
    series.tool_id = experiment.tool_id
    series.tool_version = experiment.tool_version
    db.flush()
    db.refresh(series)
    return series


def replicates(db: Session, series: ExperimentSeries) -> list[Experiment]:
    return list(
        db.execute(
            select(Experiment)
            .where(Experiment.series_id == series.id)
            .order_by(Experiment.experiment_number)
        ).scalars()
    )


def run_ids(db: Session, series: ExperimentSeries) -> list[uuid.UUID]:
    return [r for e in replicates(db, series) for r in (e.baseline_run_id, e.candidate_run_id)]


def refresh(db: Session, series: ExperimentSeries) -> ExperimentSeries:
    """Bring a running series up to date with its replicates."""
    if series.status != ExperimentStatus.RUNNING:
        return series
    db.flush()
    series = db.execute(
        select(ExperimentSeries).where(ExperimentSeries.id == series.id).with_for_update()
    ).scalar_one()
    db.refresh(series)
    if series.status != ExperimentStatus.RUNNING:
        return series
    experiments = [service.refresh(db, e) for e in replicates(db, series)]
    failed = [e for e in experiments if e.status == ExperimentStatus.FAILED]
    if failed:
        series.status = ExperimentStatus.FAILED.value
        series.failure_reason = "; ".join(
            f"seed {_seed(db, e)}: {e.failure_reason}" for e in failed
        )[:4000]
        series.completed_at = datetime.now(UTC)
    elif experiments and all(e.status == ExperimentStatus.COMPLETED for e in experiments):
        series.statistics = compute(db, series, experiments)
        series.verdict = series.statistics["verdict"]
        series.status = ExperimentStatus.COMPLETED.value
        series.completed_at = datetime.now(UTC)
    db.flush()
    return series


def _seed(db: Session, experiment: Experiment) -> int:
    run = simulations.get_run(db, experiment.baseline_run_id)
    return run.seed


def compute(db: Session, series: ExperimentSeries, experiments: list[Experiment]) -> dict:
    """The statistics, from the replicates' stored evaluations (recomputable)."""
    rows = []
    for experiment in experiments:
        evaluation = db.execute(
            select(ExperimentEvaluation).where(ExperimentEvaluation.experiment_id == experiment.id)
        ).scalar_one()
        rows.append(
            {
                "seed": _seed(db, experiment),
                "experiment_number": experiment.experiment_number,
                "verdict": evaluation.verdict,
                "comparisons": evaluation.comparisons,
            }
        )
    return series_statistics(rows, series.confidence)


def execute(
    session_factory: sessionmaker[Session], series_id: uuid.UUID, ids: list[uuid.UUID]
) -> None:
    """Background job: every replicate's runs, one after another, then the statistics."""
    runner.execute_batch(session_factory, ids)
    with session_factory() as db:
        try:
            series = db.get(ExperimentSeries, series_id)
            if series is not None:
                refresh(db, series)
            db.commit()
        except Exception as exc:  # recorded on the series; nothing awaits this job
            db.rollback()
            logger.exception("experiment series evaluation failed")
            series = db.get(ExperimentSeries, series_id)
            if series is not None:
                series.status = ExperimentStatus.FAILED.value
                series.failure_reason = f"Evaluation failed: {type(exc).__name__}: {exc}"
                series.completed_at = datetime.now(UTC)
                db.commit()


def get(db: Session, series_id: uuid.UUID) -> ExperimentSeries:
    series = db.get(ExperimentSeries, series_id)
    if series is None:
        raise NotFoundError("Experiment series not found.")
    return refresh(db, series)


def summary(db: Session, series: ExperimentSeries) -> SeriesSummary:
    creator = db.get(User, series.created_by)
    done = db.execute(
        select(func.count()).where(
            Experiment.series_id == series.id, Experiment.status == ExperimentStatus.COMPLETED
        )
    ).scalar_one()
    return SeriesSummary(
        id=series.id,
        series_number=series.series_number,
        name=series.name,
        scenario_id=series.scenario_id,
        scenario_version=series.scenario_version,
        candidate_mode=series.candidate_mode,
        tool_id=series.tool_id,
        tool_version=series.tool_version,
        seeds=series.seeds,
        confidence=series.confidence,
        status=series.status,
        failure_reason=series.failure_reason,
        verdict=series.verdict,
        replicates_completed=done,
        created_by_username=creator.username if creator else None,
        created_at=series.created_at,
        completed_at=series.completed_at,
    )


def detail(db: Session, series: ExperimentSeries) -> SeriesDetail:
    return SeriesDetail(
        **summary(db, series).model_dump(),
        configuration=series.configuration,
        statistics=series.statistics,
        experiments=[service.summary(db, e) for e in replicates(db, series)],
    )


def list_series(
    db: Session, params: PageParams, *, tool_id: str | None = None
) -> tuple[list[SeriesSummary], int]:
    query = select(ExperimentSeries).order_by(ExperimentSeries.series_number.desc())
    if tool_id:
        query = query.where(ExperimentSeries.tool_id == tool_id)
    items, total = paginate(db, query, params)
    return [summary(db, refresh(db, s)) for s in items], total
