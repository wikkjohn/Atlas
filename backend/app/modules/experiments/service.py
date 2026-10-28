"""Experiments: start, measure, evaluate, re-evaluate, report and benchmark."""

import logging
import statistics
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.pagination import PageParams, paginate
from app.modules.experiments.assumptions import EvaluationConfig
from app.modules.experiments.evaluation import evaluate
from app.modules.experiments.measurements import canonical_hash, measure, measurement_digest
from app.modules.experiments.models import (
    Experiment,
    ExperimentEvaluation,
    ExperimentMeasurement,
    ExperimentStatus,
)
from app.modules.experiments.schemas import (
    BenchmarkRow,
    Evaluation,
    ExperimentCreate,
    ExperimentDetail,
    ExperimentFromRuns,
    ExperimentSummary,
    Measurement,
    ReEvaluation,
    RunRef,
)
from app.modules.identity.models import User
from app.simulation import runner
from app.simulation import service as simulations
from app.simulation.models import SimulationRun, SimulationStatus
from app.simulation.schemas import StartSuite

logger = logging.getLogger("atlas.experiments")

HEADLINE = ("labour_hours", "cost_per_completed_case", "processing_time_hours", "accuracy")


def _config(costs, thresholds) -> tuple[dict[str, Any], str]:
    config = EvaluationConfig(costs=costs, thresholds=thresholds).model_dump(mode="json")
    return config, canonical_hash(config)


# --- Creation ---------------------------------------------------------------------------------


def create(db: Session, body: ExperimentCreate, actor_id: uuid.UUID) -> Experiment:
    """Queue the baseline and candidate runs; the evaluation follows when both finish."""
    if body.profile == "department":
        sizes: dict[str, Any] = {"profile": "custom", "applications": 10_000, "employees": 500}
    elif body.profile == "custom":
        sizes = {
            "profile": "custom",
            "applications": body.applications,
            "employees": body.employees,
        }
    else:
        sizes = {"profile": "small"}
    runs = simulations.start_suite(
        db,
        StartSuite(
            scenario_id=body.scenario_id,
            scenario_version=body.scenario_version,
            seed=body.seed,
            modes=["baseline", body.candidate_mode],
            tool_id=body.tool_id,
            tool_version=body.tool_version,
            **sizes,
        ),
        actor_id,
    )
    baseline, candidate = runs
    config, config_hash = _config(body.costs, body.thresholds)
    tool = candidate.config["ai_tool"]
    experiment = Experiment(
        name=body.name.strip(),
        scenario_id=candidate.scenario_id,
        scenario_version=candidate.scenario_version,
        baseline_run_id=baseline.id,
        candidate_run_id=candidate.id,
        candidate_mode=body.candidate_mode,
        tool_record_id=candidate.tool_record_id,
        tool_id=tool["tool_id"],
        tool_version=tool["tool_version"],
        configuration=config,
        configuration_hash=config_hash,
        status=ExperimentStatus.RUNNING.value,
        created_by=actor_id,
    )
    db.add(experiment)
    db.flush()
    db.refresh(experiment)
    return experiment


def create_from_runs(db: Session, body: ExperimentFromRuns, actor_id: uuid.UUID) -> Experiment:
    if body.baseline_run_id == body.candidate_run_id:
        raise BusinessRuleViolation("The baseline and candidate must be different runs.")
    baseline = simulations.get_run(db, body.baseline_run_id)
    candidate = simulations.get_run(db, body.candidate_run_id)
    if baseline.mode != "baseline":
        raise BusinessRuleViolation(
            f"Run #{baseline.run_number} is a {baseline.mode} run, not a baseline."
        )
    if candidate.mode == "baseline":
        raise BusinessRuleViolation(f"Run #{candidate.run_number} is a baseline, not a candidate.")
    for run in (baseline, candidate):
        if run.status != SimulationStatus.COMPLETED:
            raise BusinessRuleViolation(f"Run #{run.run_number} is {run.status}, not completed.")
    base_measure, cand_measure = measure(db, baseline), measure(db, candidate)
    differences = [
        key
        for key in base_measure["workload"]
        if base_measure["workload"][key] != cand_measure["workload"].get(key)
    ]
    if differences or base_measure["case_fingerprint"] != cand_measure["case_fingerprint"]:
        raise BusinessRuleViolation(
            "The runs did not process equivalent workloads, so they cannot be compared.",
            {"differences": differences or ["generated applications"]},
        )
    config, config_hash = _config(body.costs, body.thresholds)
    tool = candidate.config.get("ai_tool") or {}
    experiment = Experiment(
        name=body.name.strip(),
        scenario_id=candidate.scenario_id,
        scenario_version=candidate.scenario_version,
        baseline_run_id=baseline.id,
        candidate_run_id=candidate.id,
        candidate_mode=candidate.mode,
        tool_record_id=candidate.tool_record_id,
        tool_id=tool.get("tool_id"),
        tool_version=tool.get("tool_version"),
        configuration=config,
        configuration_hash=config_hash,
        status=ExperimentStatus.RUNNING.value,
        created_by=actor_id,
    )
    db.add(experiment)
    db.flush()
    _record(db, experiment, base_measure, cand_measure)
    return experiment


# --- Measurement and evaluation ---------------------------------------------------------------


def _record(
    db: Session, experiment: Experiment, base: dict[str, Any], cand: dict[str, Any]
) -> None:
    for role, metrics, run_id in (
        ("baseline", base, experiment.baseline_run_id),
        ("candidate", cand, experiment.candidate_run_id),
    ):
        db.add(
            ExperimentMeasurement(
                experiment_id=experiment.id,
                run_id=run_id,
                role=role,
                metrics=metrics,
                measurement_digest=measurement_digest(metrics),
            )
        )
    derived = evaluate(base, cand, EvaluationConfig.model_validate(experiment.configuration))
    db.add(ExperimentEvaluation(experiment_id=experiment.id, **derived))
    experiment.status = ExperimentStatus.COMPLETED.value
    experiment.completed_at = datetime.now(UTC)
    db.flush()


def refresh(db: Session, experiment: Experiment) -> Experiment:
    """Bring a running experiment up to date with its runs (evaluate or fail)."""
    if experiment.status != ExperimentStatus.RUNNING:
        return experiment
    # Lock, then look again: a background task and a reader may both arrive here.
    db.flush()
    locked = db.execute(
        select(Experiment).where(Experiment.id == experiment.id).with_for_update()
    ).scalar_one()
    db.refresh(locked)
    if locked.status != ExperimentStatus.RUNNING:
        return locked
    experiment = locked
    simulations.reap_stale(db)
    baseline = db.get(SimulationRun, experiment.baseline_run_id)
    candidate = db.get(SimulationRun, experiment.candidate_run_id)
    assert baseline is not None and candidate is not None
    failed = [r for r in (baseline, candidate) if r.status == SimulationStatus.FAILED]
    if failed:
        experiment.status = ExperimentStatus.FAILED.value
        experiment.failure_reason = "; ".join(
            f"{r.mode} run #{r.run_number} failed: {r.failure_reason}" for r in failed
        )
        experiment.completed_at = datetime.now(UTC)
        db.flush()
    elif all(r.status == SimulationStatus.COMPLETED for r in (baseline, candidate)):
        _record(db, experiment, measure(db, baseline), measure(db, candidate))
    return experiment


def execute(
    session_factory: sessionmaker[Session], experiment_id: uuid.UUID, run_ids: list[uuid.UUID]
) -> None:
    """Background task: run the experiment's simulations, then evaluate."""
    runner.execute_batch(session_factory, run_ids)
    with session_factory() as db:
        try:
            experiment = db.get(Experiment, experiment_id)
            if experiment is not None:
                refresh(db, experiment)
            db.commit()
        except Exception as exc:  # recorded on the experiment; nothing awaits this task
            db.rollback()
            logger.exception("experiment evaluation failed")
            experiment = db.get(Experiment, experiment_id)
            if experiment is not None:
                experiment.status = ExperimentStatus.FAILED.value
                experiment.failure_reason = f"Evaluation failed: {type(exc).__name__}: {exc}"
                experiment.completed_at = datetime.now(UTC)
                db.commit()


def re_evaluate(db: Session, experiment: Experiment) -> ReEvaluation:
    """Recompute the derived results from the stored raw measurements."""
    stored = _evaluation(db, experiment)
    if stored is None:
        raise ConflictError("The experiment has not been evaluated yet.")
    rows = {m.role: m.metrics for m in _measurements(db, experiment)}
    derived = evaluate(
        rows["baseline"],
        rows["candidate"],
        EvaluationConfig.model_validate(experiment.configuration),
    )
    return ReEvaluation(
        stored_digest=stored.evaluation_digest,
        recomputed_digest=derived["evaluation_digest"],
        matches=derived["evaluation_digest"] == stored.evaluation_digest,
    )


# --- Reading ----------------------------------------------------------------------------------


def get(db: Session, experiment_id: uuid.UUID) -> Experiment:
    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        raise NotFoundError("Experiment not found.")
    return refresh(db, experiment)


def _measurements(db: Session, experiment: Experiment) -> list[ExperimentMeasurement]:
    return list(
        db.execute(
            select(ExperimentMeasurement)
            .where(ExperimentMeasurement.experiment_id == experiment.id)
            .order_by(ExperimentMeasurement.role)
        ).scalars()
    )


def _evaluation(db: Session, experiment: Experiment) -> ExperimentEvaluation | None:
    return db.execute(
        select(ExperimentEvaluation).where(ExperimentEvaluation.experiment_id == experiment.id)
    ).scalar_one_or_none()


def _run_ref(run: SimulationRun) -> RunRef:
    summary = simulations.summary(run, {})
    return RunRef(
        id=run.id,
        run_number=run.run_number,
        mode=run.mode,
        status=run.status,
        percent_complete=summary.percent_complete,
        failure_reason=run.failure_reason,
    )


def summary(db: Session, experiment: Experiment) -> ExperimentSummary:
    evaluation = _evaluation(db, experiment)
    creator = db.get(User, experiment.created_by)
    headline: dict[str, float | None] = {}
    if evaluation is not None:
        for row in evaluation.comparisons:
            if row["metric"] in HEADLINE:
                headline[row["metric"]] = row["relative_change"]
    baseline = db.get(SimulationRun, experiment.baseline_run_id)
    candidate = db.get(SimulationRun, experiment.candidate_run_id)
    assert baseline is not None and candidate is not None
    return ExperimentSummary(
        id=experiment.id,
        experiment_number=experiment.experiment_number,
        name=experiment.name,
        scenario_id=experiment.scenario_id,
        scenario_version=experiment.scenario_version,
        candidate_mode=experiment.candidate_mode,
        tool_id=experiment.tool_id,
        tool_version=experiment.tool_version,
        status=experiment.status,
        failure_reason=experiment.failure_reason,
        verdict=evaluation.verdict if evaluation else None,
        created_by_username=creator.username if creator else None,
        created_at=experiment.created_at,
        completed_at=experiment.completed_at,
        baseline=_run_ref(baseline),
        candidate=_run_ref(candidate),
        headline=headline,
    )


def detail(db: Session, experiment: Experiment) -> ExperimentDetail:
    evaluation = _evaluation(db, experiment)
    return ExperimentDetail(
        **summary(db, experiment).model_dump(),
        configuration=experiment.configuration,
        configuration_hash=experiment.configuration_hash,
        measurements=[
            Measurement.model_validate(m, from_attributes=True)
            for m in _measurements(db, experiment)
        ],
        evaluation=Evaluation.model_validate(evaluation, from_attributes=True)
        if evaluation
        else None,
    )


def list_experiments(
    db: Session,
    params: PageParams,
    *,
    status: str | None = None,
    tool_id: str | None = None,
) -> tuple[list[ExperimentSummary], int]:
    query = select(Experiment).order_by(Experiment.experiment_number.desc())
    if status:
        query = query.where(Experiment.status == status)
    if tool_id:
        query = query.where(Experiment.tool_id == tool_id)
    items, total = paginate(db, query, params)
    return [summary(db, refresh(db, e)) for e in items], total


def benchmarks(db: Session) -> list[BenchmarkRow]:
    """Completed experiments grouped by tool version and mode."""
    rows = db.execute(
        select(Experiment, ExperimentEvaluation)
        .join(ExperimentEvaluation, ExperimentEvaluation.experiment_id == Experiment.id)
        .where(Experiment.status == ExperimentStatus.COMPLETED, Experiment.tool_id.is_not(None))
        .order_by(Experiment.experiment_number)
    ).all()
    groups: dict[tuple[str, str, str], list[tuple[Experiment, ExperimentEvaluation]]] = {}
    for experiment, evaluation in rows:
        key = (experiment.tool_id or "", experiment.tool_version or "", experiment.candidate_mode)
        groups.setdefault(key, []).append((experiment, evaluation))
    result = []
    for (tool_id, version, mode), items in sorted(groups.items()):
        changes: dict[str, list[float]] = {k: [] for k in HEADLINE}
        for _, evaluation in items:
            for row in evaluation.comparisons:
                if row["metric"] in changes and row["relative_change"] is not None:
                    changes[row["metric"]].append(row["relative_change"])
        latest_experiment, latest_evaluation = items[-1]
        result.append(
            BenchmarkRow(
                tool_id=tool_id,
                tool_version=version,
                candidate_mode=mode,
                experiments=len(items),
                successful=sum(e.verdict == "successful" for _, e in items),
                latest_experiment_id=latest_experiment.id,
                latest_verdict=latest_evaluation.verdict,
                median_relative_change={
                    k: round(statistics.median(v), 6) if v else None for k, v in changes.items()
                },
            )
        )
    return result
