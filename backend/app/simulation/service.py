"""Simulation run registry: starting runs, reading them back and comparing reproductions."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.pagination import PageParams, paginate
from app.modules.identity.models import User
from app.simulation import runner
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.scenarios import PROFILES, SCENARIOS, Scenario, get_scenario
from app.simulation.schemas import (
    CaseResultOut,
    ProfileOut,
    Reproduction,
    ScenarioOut,
    SimulationRunDetail,
    SimulationRunSummary,
    StartSimulation,
)

# A running simulation commits progress every few seconds; this long without one means the
# process running it stopped (a restart or crash) and the run will never finish.
STALE_AFTER = timedelta(minutes=5)
ACTIVE = (SimulationStatus.QUEUED, SimulationStatus.RUNNING)


def scenarios() -> list[ScenarioOut]:
    return [
        ScenarioOut(
            scenario_id=s.scenario_id,
            version=s.version,
            name=s.name,
            description=s.description,
            workflow_id=s.workflow_id,
            simulated_start=s.simulated_start,
            config=s.config.model_dump(mode="json"),
        )
        for _, s in sorted(SCENARIOS.items())
    ]


def profiles() -> list[ProfileOut]:
    return [
        ProfileOut(
            profile_id=p.profile_id,
            name=p.name,
            applications=p.applications,
            customers=p.customers,
            employees=p.employees,
            status=p.status,
            runnable=p.status == "verified",
            note=p.note,
        )
        for p in PROFILES.values()
    ]


def reap_stale(db: Session, now: datetime | None = None) -> int:
    """Fail runs whose process stopped: they would otherwise show as running forever."""
    cutoff = (now or datetime.now(UTC)) - STALE_AFTER
    stale = db.execute(
        select(SimulationRun)
        .where(
            SimulationRun.status.in_(list(ACTIVE)),
            SimulationRun.heartbeat_at.is_(None) & (SimulationRun.created_at < cutoff)
            | (SimulationRun.heartbeat_at < cutoff),
        )
        .with_for_update(skip_locked=True)
    ).scalars()
    count = 0
    for run in stale:
        last = run.heartbeat_at or run.created_at
        run.status = SimulationStatus.FAILED.value
        run.failure_reason = (
            f"Interrupted: no progress was recorded after {last.isoformat(timespec='seconds')}. "
            "The process running it stopped (for example a restart); start a new run."
        )
        run.completed_at = now or datetime.now(UTC)
        count += 1
    db.flush()
    return count


def _resolve(body: StartSimulation) -> tuple[Scenario, int, int]:
    scenario = get_scenario(body.scenario_id, body.scenario_version)
    if scenario is None:
        raise NotFoundError(
            f"Scenario {body.scenario_id}"
            + (f" v{body.scenario_version}" if body.scenario_version else "")
            + " is not registered."
        )
    if body.profile == "custom":
        if body.applications is None or body.employees is None:
            raise BusinessRuleViolation(
                "A custom run needs both applications and employees.",
                {"applications": body.applications, "employees": body.employees},
            )
        return scenario, body.applications, body.employees
    if body.applications is not None or body.employees is not None:
        raise BusinessRuleViolation(
            "Sizes are fixed by the profile; use the custom profile to choose them."
        )
    profile = PROFILES[body.profile]
    if profile.status != "verified":
        raise BusinessRuleViolation(
            f"The {profile.name} profile is a configuration target, not a runnable workload: "
            f"{profile.note}",
            {"profile": profile.profile_id, "status": profile.status},
        )
    return scenario, profile.applications, profile.employees


def start_run(db: Session, body: StartSimulation, actor_id: uuid.UUID) -> SimulationRun:
    scenario, applications, employees = _resolve(body)
    reap_stale(db)
    active = db.execute(
        select(SimulationRun.run_number).where(SimulationRun.status.in_(list(ACTIVE)))
    ).first()
    if active is not None:
        # One run at a time: runs share the database with the rest of the bank.
        raise ConflictError(
            f"Simulation run #{active[0]} is still in progress; start another when it finishes.",
            {"active_run": active[0]},
        )
    return runner.create_run(
        db,
        scenario,
        profile=body.profile,
        applications=applications,
        employees=employees,
        seed=body.seed,
        created_by=actor_id,
    )


def rerun_body(run: SimulationRun) -> StartSimulation:
    custom = run.profile == "custom"
    return StartSimulation(
        scenario_id=run.scenario_id,
        scenario_version=run.scenario_version,
        profile=run.profile,  # type: ignore[arg-type]
        seed=run.seed,
        applications=run.config["applications"] if custom else None,
        employees=run.config["employees"] if custom else None,
    )


def get_run(db: Session, run_id: uuid.UUID) -> SimulationRun:
    run = db.get(SimulationRun, run_id)
    if run is None:
        raise NotFoundError("Simulation run not found.")
    return run


def list_runs(
    db: Session, params: PageParams, *, status: str | None = None
) -> tuple[list[SimulationRunSummary], int]:
    query = select(SimulationRun).order_by(SimulationRun.run_number.desc())
    if status:
        query = query.where(SimulationRun.status == status)
    items, total = paginate(db, query, params)
    names = _usernames(db, {r.created_by for r in items})
    return [summary(r, names) for r in items], total


def _usernames(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.username).where(User.id.in_(ids))).all())


def summary(run: SimulationRun, names: dict[uuid.UUID, str]) -> SimulationRunSummary:
    progress = run.progress or {}
    total = progress.get("cases_total") or run.config.get("applications") or 0
    done = progress.get("cases_completed") or 0
    percent = (
        100.0
        if run.status == SimulationStatus.COMPLETED
        else (round(100 * done / total, 1) if total else 0.0)
    )
    return SimulationRunSummary(
        id=run.id,
        run_number=run.run_number,
        scenario_id=run.scenario_id,
        scenario_version=run.scenario_version,
        workflow_id=run.workflow_id,
        workflow_version=run.workflow_version,
        profile=run.profile,
        seed=run.seed,
        applications=run.config["applications"],
        employees=run.config["employees"],
        status=run.status,
        failure_reason=run.failure_reason,
        software_version=run.software_version,
        config_hash=run.config_hash,
        result_digest=run.result_digest,
        created_by_username=names.get(run.created_by),
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        wall_ms=run.wall_ms,
        progress=progress,
        percent_complete=percent,
    )


def reproductions(db: Session, run: SimulationRun) -> list[Reproduction]:
    """Other completed runs with the same scenario, seed, configuration and software."""
    if run.status != SimulationStatus.COMPLETED:
        return []
    others = db.execute(
        select(SimulationRun)
        .where(
            SimulationRun.id != run.id,
            SimulationRun.status == SimulationStatus.COMPLETED,
            SimulationRun.scenario_id == run.scenario_id,
            SimulationRun.scenario_version == run.scenario_version,
            SimulationRun.seed == run.seed,
            SimulationRun.config_hash == run.config_hash,
            SimulationRun.software_version == run.software_version,
        )
        .order_by(SimulationRun.run_number)
    ).scalars()
    return [
        Reproduction(
            id=o.id,
            run_number=o.run_number,
            result_digest=o.result_digest,
            matches=o.result_digest == run.result_digest,
        )
        for o in others
    ]


def detail(db: Session, run: SimulationRun) -> SimulationRunDetail:
    names = _usernames(db, {run.created_by})
    return SimulationRunDetail(
        **summary(run, names).model_dump(),
        config=run.config,
        results=run.results,
        simulated_start=run.simulated_start,
        simulated_end=run.simulated_end,
        staff_unit_id=run.staff_unit_id,
        reproductions=reproductions(db, run),
    )


def list_cases(
    db: Session,
    run_id: uuid.UUID,
    params: PageParams,
    *,
    kind: str | None = None,
    mismatched: bool = False,
) -> tuple[list[CaseResultOut], int]:
    query = (
        select(SimulationCaseResult)
        .where(SimulationCaseResult.run_id == run_id)
        .order_by(SimulationCaseResult.case_index)
    )
    if kind:
        query = query.where(SimulationCaseResult.kind == kind)
    if mismatched:
        query = query.where(
            SimulationCaseResult.outcome.is_distinct_from(SimulationCaseResult.expected_outcome)
        )
    items, total = paginate(db, query, params)
    return [
        CaseResultOut(
            case_index=c.case_index,
            execution_id=c.execution_id,
            kind=c.kind,
            expected_outcome=c.expected_outcome,
            status=c.status,
            outcome=c.outcome,
            matches_ground_truth=c.outcome == c.expected_outcome,
            risk_rating=c.risk_rating,
            flags=c.flags,
            manual_reviews=c.manual_reviews,
            review_minutes=round(c.review_seconds / 60, 1),
            queue_wait_minutes=round(c.queue_wait_seconds / 60, 1),
            overdue_tasks=c.overdue_tasks,
            arrived_at=c.arrived_at,
            completed_at=c.completed_at,
            cycle_hours=round(c.cycle_seconds / 3600, 3) if c.cycle_seconds is not None else None,
            path=c.path,
        )
        for c in items
    ], total
