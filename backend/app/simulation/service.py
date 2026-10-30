"""Simulation run registry: starting runs, reading them back and comparing reproductions."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.pagination import PageParams, paginate
from app.jobs.models import JobSchedule
from app.modules.ai_tools.models import AITool, ToolStatus
from app.modules.ai_tools.service import find_tool
from app.modules.identity.models import User
from app.modules.workflows.models import PARTITIONED_TABLES, Realm, partition_name
from app.simulation import history, runner
from app.simulation.history import RETENTION_SCHEDULE
from app.simulation.models import (
    HistoryState,
    SimulationArchive,
    SimulationCaseResult,
    SimulationRun,
    SimulationShard,
    SimulationStatus,
)
from app.simulation.scenarios import MODES, PROFILES, SCENARIOS, Scenario, get_scenario
from app.simulation.schemas import (
    ArchiveOut,
    CaseResultOut,
    HistoryOverview,
    PartitionUsage,
    ProfileOut,
    Reproduction,
    ScenarioOut,
    ShardOut,
    SimulationRunDetail,
    SimulationRunSummary,
    StartSimulation,
    StartSuite,
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
            workload=s.workload,
            workflow_id=s.workflow_id,
            workflow_version=s.workflow_version,
            modes=list(MODES) if s.config.ai_assistance is not None else ["baseline"],
            simulated_start=s.simulated_start,
            config=s.config.model_dump(mode="json"),
        )
        for s in SCENARIOS.values()  # in registration order: retail onboarding first
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
            min_shards=p.min_shards,
        )
        for p in PROFILES.values()
    ]


def reap_stale(db: Session, now: datetime | None = None) -> int:
    """Fail runs whose process stopped: they would otherwise show as running forever."""
    cutoff = (now or datetime.now(UTC)) - STALE_AFTER
    # Queued members of a suite wait while an earlier member runs; they are not stale.
    busy_batches = set(
        db.execute(
            select(SimulationRun.batch_id).where(
                SimulationRun.status == SimulationStatus.RUNNING,
                SimulationRun.heartbeat_at >= cutoff,
                SimulationRun.batch_id.is_not(None),
            )
        ).scalars()
    )
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
        if run.status == SimulationStatus.QUEUED and run.batch_id in busy_batches:
            continue
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


def _resolve_tool(
    db: Session, scenario: Scenario, modes: list[str], tool_id: str | None, version: str | None
) -> AITool | None:
    if all(m == "baseline" for m in modes):
        return None
    if scenario.config.ai_assistance is None:
        raise BusinessRuleViolation(
            f"Scenario {scenario.scenario_id} v{scenario.version} has no AI modes; use a "
            "scenario version that supports them.",
            {"supported_modes": ["baseline"]},
        )
    if not tool_id:
        raise BusinessRuleViolation("AI modes need tool_id (a registered AI tool).")
    tool = find_tool(db, tool_id, version)
    if tool.status != ToolStatus.ACTIVE:
        raise BusinessRuleViolation(f"{tool.tool_id} {tool.tool_version} is disabled.")
    if scenario.workflow_id not in tool.compatible_workflows:
        raise BusinessRuleViolation(
            f"{tool.tool_id} {tool.tool_version} is not declared compatible with "
            f"{scenario.workflow_id}.",
            {"compatible_workflows": tool.compatible_workflows},
        )
    return tool


def _check_profile_shards(body: StartSimulation) -> None:
    profile = PROFILES.get(body.profile)
    if profile is not None and body.shards < profile.min_shards:
        raise BusinessRuleViolation(
            f"The {profile.name} profile runs as at least {profile.min_shards} parallel shards; "
            "one process would take hours.",
            {"profile": profile.profile_id, "min_shards": profile.min_shards},
        )


def _resolve(body: StartSimulation | StartSuite) -> tuple[Scenario, int, int]:
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


def _ensure_idle(db: Session) -> None:
    reap_stale(db)
    active = db.execute(
        select(SimulationRun.run_number)
        .where(SimulationRun.status.in_(list(ACTIVE)))
        .order_by(SimulationRun.run_number)
    ).first()
    if active is not None:
        # One run at a time: runs share the database with the rest of the bank.
        raise ConflictError(
            f"Simulation run #{active[0]} is still in progress; start another when it finishes. "
            "(A run whose process stopped is marked interrupted after 5 minutes.)",
            {"active_run": active[0]},
        )


def start_run(db: Session, body: StartSimulation, actor_id: uuid.UUID) -> SimulationRun:
    scenario, applications, employees = _resolve(body)
    _check_profile_shards(body)
    tool = _resolve_tool(db, scenario, [body.mode], body.tool_id, body.tool_version)
    _ensure_idle(db)
    return runner.create_run(
        db,
        scenario,
        profile=body.profile,
        applications=applications,
        employees=employees,
        seed=body.seed,
        created_by=actor_id,
        mode=body.mode,
        tool=tool,
        shards=body.shards,
    )


def start_suite(db: Session, body: StartSuite, actor_id: uuid.UUID) -> list[SimulationRun]:
    """One run per mode, same scenario, seed and workload: the experiment's equal footing."""
    scenario, applications, employees = _resolve(body)
    modes = list(dict.fromkeys(body.modes))
    tool = _resolve_tool(db, scenario, modes, body.tool_id, body.tool_version)
    _ensure_idle(db)
    batch_id = uuid.uuid4()
    return [
        runner.create_run(
            db,
            scenario,
            profile=body.profile,
            applications=applications,
            employees=employees,
            seed=body.seed,
            created_by=actor_id,
            mode=mode,
            tool=tool,
            batch_id=batch_id,
        )
        for mode in modes
    ]


def rerun_body(run: SimulationRun) -> StartSimulation:
    custom = run.profile == "custom"
    tool = run.config.get("ai_tool") or {}
    return StartSimulation(
        scenario_id=run.scenario_id,
        scenario_version=run.scenario_version,
        profile=run.profile,  # type: ignore[arg-type]
        seed=run.seed,
        applications=run.config["applications"] if custom else None,
        employees=run.config["employees"] if custom else None,
        mode=run.mode,  # type: ignore[arg-type]
        tool_id=tool.get("tool_id"),
        tool_version=tool.get("tool_version"),
        shards=run.config.get("shards", 1),
    )


def get_run(db: Session, run_id: uuid.UUID) -> SimulationRun:
    run = db.get(SimulationRun, run_id)
    if run is None:
        raise NotFoundError("Simulation run not found.")
    return run


def list_runs(
    db: Session,
    params: PageParams,
    *,
    status: str | None = None,
    batch_id: uuid.UUID | None = None,
    mode: str | None = None,
) -> tuple[list[SimulationRunSummary], int]:
    query = select(SimulationRun).order_by(SimulationRun.run_number.desc())
    if status:
        query = query.where(SimulationRun.status == status)
    if batch_id:
        query = query.where(SimulationRun.batch_id == batch_id)
    if mode:
        query = query.where(SimulationRun.mode == mode)
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
        mode=run.mode,
        tool_id=(run.config.get("ai_tool") or {}).get("tool_id"),
        tool_version=(run.config.get("ai_tool") or {}).get("tool_version"),
        batch_id=run.batch_id,
        shards=run.config.get("shards", 1),
        history_state=run.history_state,
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
        archive=active_archive(db, run),
        shard_progress=[
            ShardOut(
                shard=sh.shard,
                status=sh.status,
                cases_total=sh.cases_total,
                cases_completed=sh.cases_completed,
                events_processed=sh.events_processed,
                worker=sh.worker,
                started_at=sh.started_at,
                completed_at=sh.completed_at,
                wall_ms=sh.wall_ms,
                error=sh.error,
            )
            for sh in db.execute(
                select(SimulationShard)
                .where(SimulationShard.run_id == run.id)
                .order_by(SimulationShard.shard)
            ).scalars()
        ],
    )


def archive_out(record: SimulationArchive, run_number: int, names: dict) -> ArchiveOut:
    return ArchiveOut(
        id=record.id,
        run_id=record.run_id,
        run_number=run_number,
        kind=record.kind,
        location=record.location,
        rows=record.rows,
        bytes=record.bytes,
        tables={t: e["rows"] for t, e in record.manifest.get("tables", {}).items()},
        created_by_username=names.get(record.created_by),
        created_at=record.created_at,
    )


def active_archive(db: Session, run: SimulationRun) -> ArchiveOut | None:
    record = db.execute(
        select(SimulationArchive).where(
            SimulationArchive.run_id == run.id, SimulationArchive.restored_at.is_(None)
        )
    ).scalar_one_or_none()
    if record is None:
        return None
    return archive_out(record, run.run_number, _usernames(db, {record.created_by}))


def _directory_bytes(root: Path) -> int:
    if not root.is_dir():
        return 0
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def history_overview(db: Session) -> HistoryOverview:
    partitions = []
    for table in PARTITIONED_TABLES:
        for realm in Realm:
            name = partition_name(table, realm)
            rows, size = db.execute(
                text(
                    "SELECT GREATEST(c.reltuples, 0)::bigint, pg_total_relation_size(c.oid) "
                    "FROM pg_class c WHERE c.oid = CAST(:name AS regclass)"
                ),
                {"name": name},
            ).one()
            partitions.append(
                PartitionUsage(table=table, realm=realm.value, rows_estimate=rows, bytes=size)
            )
    states = dict(
        db.execute(
            select(SimulationRun.history_state, func.count()).group_by(SimulationRun.history_state)
        ).all()
    )
    recent = db.execute(
        select(SimulationArchive, SimulationRun.run_number)
        .join(SimulationRun, SimulationRun.id == SimulationArchive.run_id)
        .order_by(SimulationArchive.created_at.desc())
        .limit(10)
    ).all()
    names = _usernames(db, {r.created_by for r, _ in recent if r.created_by})
    retention = db.execute(
        select(JobSchedule.enabled).where(JobSchedule.name == RETENTION_SCHEDULE)
    ).scalar_one_or_none()
    root = history.archive_root()
    return HistoryOverview(
        partitions=partitions,
        runs_by_history_state={state.value: states.get(state.value, 0) for state in HistoryState},
        archive_directory=str(root),
        archive_bytes=_directory_bytes(root),
        recent_archives=[archive_out(r, number, names) for r, number in recent],
        retention_schedule_enabled=retention,
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
            ai_recommendation=c.ai_recommendation,
            ai_status=c.ai_status,
            automated=c.automated,
        )
        for c in items
    ], total
