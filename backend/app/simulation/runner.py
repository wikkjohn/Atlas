"""Discrete-event simulation runner.

A run replays a scenario on simulated time through the real workflow engine:

- Synthetic applications arrive across the scenario's arrival window and are started by
  simulated tellers (`engine.start` with the simulated `now`).
- Approvals are queued to a pool of simulated reviewers. Each reviewer works one case at a
  time; review time is lognormal and the decision matches the ground truth with the
  scenario's accuracy, so queues, waiting time and mistakes emerge from the model.
- Late documents arrive as `documents_submitted` signals; timeouts fire at their due time.
- Events are processed in simulated-time order from a heap; ties keep insertion order. Every
  random draw comes from a per-case stream (`case_random`), so the same scenario version,
  dataset, seed, configuration and software version reproduce the same results.

Work is committed in batches together with progress and a heartbeat, so the run can be
watched while it executes and an interrupted run is recognizable as such.
"""

import hashlib
import heapq
import json
import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import __version__
from app.config import get_settings
from app.core.errors import ConflictError, DomainError
from app.core.money import to_minor_units
from app.core.permissions import RoleCode, permissions_for
from app.modules.ai_tools.models import AITool
from app.modules.countries.models import Country, OperationalStatus
from app.modules.employees.schemas import EmployeeCreate
from app.modules.employees.service import create_employee
from app.modules.identity.service import AuthenticatedUser, create_service_account
from app.modules.organizations.models import Organization, OrganizationStatus, OrganizationType
from app.modules.organizations.schemas import OrganizationCreate
from app.modules.organizations.service import create_organization
from app.modules.workflows import engine, registry
from app.modules.workflows.definition import StepType
from app.modules.workflows.models import (
    ACTIVE_STATUSES,
    RunStatus,
    WorkflowExecution,
    WorkflowStepRun,
)
from app.simulation.clock import SimulationClock
from app.simulation.generators import (
    ApplicationGenerator,
    StaffGenerator,
    SyntheticApplication,
    SyntheticStaffMember,
    case_random,
    digest,
)
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.scenarios import MODES, Scenario, get_scenario

logger = logging.getLogger("atlas.simulation")

BATCH_EVENTS = 250  # events per transaction (progress and heartbeat are updated per batch)
STAFF_DIVISION = "Retail Banking"
STAFF_DEPARTMENT = "Simulated Operations"
STAFF_ROLES = {
    "teller": RoleCode.BANKING_EMPLOYEE,
    "manager": RoleCode.DEPARTMENT_MANAGER,
    "compliance": RoleCode.COMPLIANCE_OFFICER,
}
# Which simulated staff role reviews each approval step of WF-0001.
REVIEWER_ROLE = {"account_approval": "manager", "compliance_review": "compliance"}
# Synthetic annual pay in whole units of the country's currency, by role.
PAY = {"teller": 0.15, "manager": 0.45, "compliance": 0.35}  # position within the band
PAY_BAND = {"JPY": (5_000_000, 24_000_000)}
DEFAULT_PAY_BAND = (45_000, 200_000)


class SimulationSetupError(DomainError):
    """The run cannot start: the reason is shown to the user."""


def software_version() -> str:
    sha = get_settings().build_sha
    return f"{__version__}+{sha[:12]}" if sha else __version__


def _hash(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def resolve_config(
    db: Session,
    scenario: Scenario,
    *,
    profile: str,
    applications: int,
    employees: int,
    mode: str = "baseline",
    tool: AITool | None = None,
) -> dict[str, Any]:
    """The complete configuration of a run; stored with it and hashed to compare runs."""
    definition = registry.get_definition(scenario.workflow_id, scenario.workflow_version)
    if definition is None:
        raise SimulationSetupError(
            f"Workflow {scenario.workflow_id} v{scenario.workflow_version} is not registered."
        )
    if mode not in MODES:
        raise SimulationSetupError(f"Unknown mode '{mode}'.")
    ai_capable = scenario.config.ai_assistance is not None
    if mode != "baseline" and not ai_capable:
        raise SimulationSetupError(
            f"Scenario {scenario.scenario_id} v{scenario.version} does not support AI modes."
        )
    if mode != "baseline" and tool is None:
        raise SimulationSetupError(f"The {mode} mode needs an AI tool.")
    countries = sorted(
        db.execute(
            select(Country.iso_country_code).where(
                Country.operational_status == OperationalStatus.ACTIVE
            )
        ).scalars()
    )
    if not countries:
        raise SimulationSetupError("No active country is configured; applications need one.")
    config = {
        "scenario_id": scenario.scenario_id,
        "scenario_version": scenario.version,
        "workflow_id": definition.workflow_id,
        "workflow_version": definition.version,
        "simulated_start": scenario.simulated_start.isoformat(),
        "profile": profile,
        "applications": applications,
        "customers": applications,  # every application registers one new customer
        "employees": employees,
        "scenario": scenario.config.model_dump(mode="json", exclude_none=True),
        # The dataset the run draws on: active countries decide where applicants live.
        "dataset": {"countries": countries, "watchlist": "synthetic-watchlist-v1"},
    }
    if ai_capable:
        config["mode"] = mode
        config["ai_mode"] = MODES[mode]
        if mode != "baseline":
            assert tool is not None
            # Everything that determines the tool's behaviour, so runs of different tool
            # versions or configurations never count as reproductions of each other.
            config["ai_tool"] = {
                "tool_id": tool.tool_id,
                "tool_version": tool.tool_version,
                "adapter": tool.adapter,
                "allowed_actions": tool.allowed_actions,
                "configuration": tool.configuration,
                "input_schema_hash": _hash(tool.input_schema),
                "output_schema_hash": _hash(tool.output_schema),
            }
    return config


def create_run(
    db: Session,
    scenario: Scenario,
    *,
    profile: str,
    applications: int,
    employees: int,
    seed: int,
    created_by: uuid.UUID,
    mode: str = "baseline",
    tool: AITool | None = None,
    batch_id: uuid.UUID | None = None,
) -> SimulationRun:
    config = resolve_config(
        db,
        scenario,
        profile=profile,
        applications=applications,
        employees=employees,
        mode=mode,
        tool=tool if mode != "baseline" else None,
    )
    run = SimulationRun(
        scenario_id=scenario.scenario_id,
        scenario_version=scenario.version,
        workflow_id=config["workflow_id"],
        workflow_version=config["workflow_version"],
        profile=profile,
        seed=seed,
        config=config,
        config_hash=_hash(config),
        software_version=software_version(),
        status=SimulationStatus.QUEUED.value,
        created_by=created_by,
        progress={"cases_total": applications, "cases_started": 0, "cases_completed": 0},
        simulated_start=scenario.simulated_start,
        mode=mode,
        tool_record_id=tool.id if tool is not None and mode != "baseline" else None,
        batch_id=batch_id,
    )
    db.add(run)
    db.flush()
    db.refresh(run)
    return run


# --- Runtime state ----------------------------------------------------------------------------


@dataclass
class _Case:
    app: SyntheticApplication
    arrived: int  # simulated seconds since the start
    execution_id: uuid.UUID | None = None
    seen_runs: set[uuid.UUID] = field(default_factory=set)
    visits: int = 0
    reviews: int = 0
    review_seconds: int = 0
    queue_wait_seconds: int = 0
    overdue: int = 0
    documents_sent: bool = False
    done: bool = False


@dataclass
class _Staff:
    member: SyntheticStaffMember
    principal: AuthenticatedUser


@dataclass(order=True)
class _Event:
    at: int  # simulated seconds since the start
    seq: int
    kind: str = field(compare=False)
    case: int = field(compare=False)
    data: Any = field(compare=False, default=None)


class _Simulation:
    def __init__(self, db: Session, run: SimulationRun, scenario: Scenario) -> None:
        self.db = db
        self.run_id = run.id
        self.run_number = run.run_number
        self.seed = run.seed
        self.scenario = scenario
        self.config = scenario.config
        self.ai_mode = run.config.get("ai_mode")  # None: the scenario has no AI modes
        self.settings = (
            {"ai_mode": self.ai_mode, "ai_tool_id": str(run.tool_record_id)}
            if self.ai_mode is not None and run.tool_record_id is not None
            else {"ai_mode": self.ai_mode}
            if self.ai_mode is not None
            else None
        )
        self.workflow_version = run.workflow_version
        self.clock = SimulationClock(scenario.simulated_start)
        self.applications = run.config["applications"]
        self.employees = run.config["employees"]
        self.countries = run.config["dataset"]["countries"]
        self.events: list[_Event] = []
        self.seq = 0
        self.cases: dict[int, _Case] = {}
        self.tellers: list[_Staff] = []
        self.pools: dict[str, list[tuple[int, int]]] = {}  # step -> heap of (free_at, staff)
        self.reviewers: dict[str, list[_Staff]] = {}
        self.processed = 0
        self.started = 0
        self.completed = 0
        self.case_rows: list[tuple] = []
        self.pending_results: list[SimulationCaseResult] = []

    # Time ---------------------------------------------------------------------------------

    def at(self, seconds: int) -> datetime:
        return self.clock.start + timedelta(seconds=seconds)

    def seconds(self, moment: datetime) -> int:
        return math.ceil((moment - self.clock.start).total_seconds())

    def push(self, at: int, kind: str, case: int, data: Any = None) -> None:
        self.seq += 1
        heapq.heappush(self.events, _Event(at, self.seq, kind, case, data))

    # Setup --------------------------------------------------------------------------------

    def hire_staff(self) -> uuid.UUID:
        db = self.db
        division = db.execute(
            select(Organization)
            .join(Country, Country.id == Organization.country_id)
            .where(
                Organization.organization_type == OrganizationType.BUSINESS_DIVISION,
                Organization.name == STAFF_DIVISION,
                Organization.status == OrganizationStatus.ACTIVE,
                Country.operational_status == OperationalStatus.ACTIVE,
            )
            .order_by(Country.iso_country_code)
            .limit(1)
        ).scalar_one_or_none()
        if division is None:
            raise SimulationSetupError(
                f"No active '{STAFF_DIVISION}' division exists to employ the simulated staff. "
                "Create the organization structure first (e.g. `python -m app.cli seed-demo`)."
            )
        department = db.execute(
            select(Organization).where(
                Organization.parent_organization_id == division.id,
                Organization.name == STAFF_DEPARTMENT,
            )
        ).scalar_one_or_none()
        if department is None:
            department = create_organization(
                db,
                OrganizationCreate(
                    name=STAFF_DEPARTMENT,
                    organization_type=OrganizationType.DEPARTMENT,
                    parent_organization_id=division.id,
                ),
                actor_id=None,
            )
        team = create_organization(
            db,
            OrganizationCreate(
                name=f"Simulation run {self.run_number}",
                organization_type=OrganizationType.TEAM,
                parent_organization_id=department.id,
            ),
            actor_id=None,
        )
        country = db.get(Country, team.country_id)
        assert country is not None
        low, high = PAY_BAND.get(country.default_currency, DEFAULT_PAY_BAND)

        staff = StaffGenerator(self.seed, self.config.staff_mix).generate(self.employees)
        for member in staff:
            role = STAFF_ROLES[member.role]
            pay = int(low + (high - low) * PAY[member.role]) // 1000 * 1000
            employee = create_employee(
                db,
                EmployeeCreate(
                    first_name=member.first_name,
                    last_name=member.last_name,
                    email=f"sim{self.run_number}.{member.index}@atlasbank.example",
                    organization_id=team.id,
                    job_title=member.job_title,
                    role=role,
                    annual_compensation=to_minor_units(pay, country.default_currency),
                ),
                actor_id=None,
            )
            user = create_service_account(
                db,
                username=f"sim{self.run_number}-{member.index:05d}",
                email=f"sim{self.run_number}.{member.index}@users.atlasbank.example",
                display_name=f"{member.first_name} {member.last_name} (simulated)",
                role=role,
                employee_id=employee.id,
                actor_id=None,
            )
            person = _Staff(
                member,
                AuthenticatedUser(
                    id=user.id,
                    username=user.username,
                    role=role.value,
                    permissions=permissions_for(role.value),
                ),
            )
            if member.role == "teller":
                self.tellers.append(person)
            for step, reviewer_role in REVIEWER_ROLE.items():
                if member.role == reviewer_role:
                    self.reviewers.setdefault(step, []).append(person)
        for step, people in self.reviewers.items():
            self.pools[step] = [(0, i) for i in range(len(people))]
            heapq.heapify(self.pools[step])
        return team.id

    def schedule_arrivals(self) -> None:
        generator = ApplicationGenerator(
            seed=self.seed,
            mix=self.config.mix.normalized(),
            countries=self.countries,
            arrival_window_seconds=int(self.config.arrival_window_hours * 3600),
            document_delay_seconds=(
                int(self.config.document_delay_hours[0] * 3600),
                int(self.config.document_delay_hours[1] * 3600),
            ),
            today=self.clock.start.date(),
        )
        for app in generator.generate(self.applications):
            self.cases[app.index] = _Case(app=app, arrived=app.arrival_offset_seconds)
            self.push(app.arrival_offset_seconds, "arrive", app.index)

    # Events -------------------------------------------------------------------------------

    def handle(self, event: _Event) -> None:
        case = self.cases[event.case]
        now = self.at(event.at)
        if event.kind == "arrive":
            teller = self.tellers[case.app.index % len(self.tellers)]
            payload = {k: v for k, v in case.app.payload.items() if not k.startswith("_")}
            execution, _ = engine.start(
                self.db,
                workflow_id=self.scenario.workflow_id,
                version=self.workflow_version,
                payload=payload,
                initiator=teller.principal,
                now=now,
                simulation_run_id=self.run_id,
                settings=self.settings,
            )
            case.execution_id = execution.id
            self.started += 1
        elif event.kind == "review":
            run_id, staff_index, decision, step = event.data
            reviewer = self.reviewers[step][staff_index]
            try:
                engine.complete_task(
                    self.db,
                    run_id,
                    reviewer.principal,
                    decision=decision,
                    note=f"Simulated review ({decision}).",
                    now=now,
                )
            except ConflictError:
                pass  # the task closed in the meantime (e.g. the case was cancelled)
        elif event.kind == "documents":
            late = case.app.payload["_late_document"]
            assert case.execution_id is not None
            engine.signal(
                self.db,
                case.execution_id,
                "documents_submitted",
                {"documents": [late]},
                self.tellers[case.app.index % len(self.tellers)].principal.id,
                now=now,
            )
        elif event.kind == "timer":
            run = self.db.get(WorkflowStepRun, event.data)
            if run is None or run.status != RunStatus.WAITING or run.escalated_at is not None:
                return  # already handled before it became due
            if run.step_type != StepType.WAIT:
                case.overdue += 1
            execution = self.db.get(WorkflowExecution, case.execution_id)
            assert execution is not None
            engine.process_timers(self.db, execution, now)
        elif event.kind == "advance":
            assert case.execution_id is not None
            engine.advance(self.db, case.execution_id, now=now)
        self.inspect(case, event.at)

    def inspect(self, case: _Case, at: int) -> None:
        """Look at the case after an event and schedule whatever happens next."""
        db = self.db
        db.flush()
        execution = db.get(WorkflowExecution, case.execution_id)
        assert execution is not None
        if execution.status not in ACTIVE_STATUSES:
            self.finish(case, execution)
            return
        open_runs = db.execute(
            select(WorkflowStepRun)
            .where(
                WorkflowStepRun.execution_id == execution.id,
                WorkflowStepRun.status.in_([RunStatus.WAITING, RunStatus.PENDING]),
            )
            .order_by(WorkflowStepRun.sequence)
        ).scalars()
        for run in open_runs:
            if run.status == RunStatus.PENDING:
                # A retry waiting for its backoff: come back when it is due.
                if run.not_before is not None:
                    self.push(max(at, self.seconds(run.not_before)), "advance", case.app.index)
                continue
            if run.id in case.seen_runs:
                continue
            case.seen_runs.add(run.id)
            if run.due_at is not None:
                self.push(max(at, self.seconds(run.due_at)), "timer", case.app.index, run.id)
            if run.step_type == StepType.APPROVAL:
                self.assign_review(case, run, at, execution.context)
            elif run.step_type == StepType.WAIT and not case.documents_sent:
                delay = case.app.document_delay_seconds
                if delay is not None and case.app.payload.get("_late_document"):
                    case.documents_sent = True
                    self.push(at + delay, "documents", case.app.index)
                # Otherwise the documents never arrive and the wait times out.
            elif run.step_type == StepType.HUMAN_TASK:
                raise SimulationSetupError(
                    f"The scenario has no simulated behaviour for human task '{run.step_id}'."
                )

    def assign_review(
        self, case: _Case, run: WorkflowStepRun, at: int, context: dict[str, Any]
    ) -> None:
        pool = self.pools.get(run.step_id)
        model = self.config.reviewers.get(run.step_id)
        if pool is None or model is None:
            raise SimulationSetupError(
                f"The scenario has no simulated reviewers for approval step '{run.step_id}'."
            )
        case.visits += 1
        rng = case_random(self.seed, case.app.index, f"review:{run.step_id}:{case.visits}")
        free_at, staff_index = heapq.heappop(pool)
        begin = max(at, free_at)
        truth = "approve" if case.app.expected_outcome == "approved" else "reject"
        wrong = "reject" if truth == "approve" else "approve"
        # With an AI recommendation in front of them, reviewers work faster and follow it
        # more often — the scenario's stated assumptions, not measured behaviour. An
        # escalation or an unavailable tool gives no help.
        ai = context.get("ai_kyc_review") or {}
        recommendation = ai.get("recommendation") if ai.get("available") else None
        time_factor, accuracy = 1.0, model.accuracy
        assist = self.config.ai_assistance
        if assist is not None and recommendation in ("approve", "reject"):
            time_factor = assist.review_time_factor
            accuracy = (
                assist.accuracy_when_ai_correct
                if recommendation == truth
                else assist.accuracy_when_ai_wrong
            )
        mu = math.log(model.mean_minutes * 60) - model.sigma**2 / 2  # mean = mean_minutes
        service = max(60, round(rng.lognormvariate(mu, model.sigma) * time_factor))
        heapq.heappush(pool, (begin + service, staff_index))
        decision = truth if rng.random() < accuracy else wrong
        case.reviews += 1
        case.review_seconds += service
        case.queue_wait_seconds += begin - at
        self.push(
            begin + service, "review", case.app.index, (run.id, staff_index, decision, run.step_id)
        )

    def finish(self, case: _Case, execution: WorkflowExecution) -> None:
        if case.done:
            return
        case.done = True
        self.completed += 1
        path = list(
            self.db.execute(
                select(WorkflowStepRun.step_id)
                .where(
                    WorkflowStepRun.execution_id == execution.id,
                    WorkflowStepRun.status == RunStatus.COMPLETED,
                )
                .order_by(WorkflowStepRun.sequence)
            ).scalars()
        )
        context = execution.context
        ai = context.get("ai_kyc_review") or {}
        completed_at = execution.completed_at
        cycle = (
            round((completed_at - self.at(case.arrived)).total_seconds()) if completed_at else None
        )
        result = SimulationCaseResult(
            run_id=self.run_id,
            case_index=case.app.index,
            execution_id=execution.id,
            kind=case.app.kind,
            expected_outcome=case.app.expected_outcome,
            status=execution.status,
            outcome=execution.outcome,
            risk_rating=(context.get("assign_risk_rating") or {}).get("rating"),
            flags=(context.get("evaluate_compliance") or {}).get("flags") or [],
            manual_reviews=case.reviews,
            review_seconds=case.review_seconds,
            queue_wait_seconds=case.queue_wait_seconds,
            overdue_tasks=case.overdue,
            arrived_at=self.at(case.arrived),
            completed_at=completed_at,
            cycle_seconds=cycle,
            path=path,
            ai_recommendation=ai.get("recommendation") if ai.get("available") else None,
            ai_status=ai.get("invocation_status")
            or ("unavailable" if ai and ai.get("mode") != "off" else None),
            automated=bool((context.get("policy_approval") or {}).get("approved")),
        )
        self.pending_results.append(result)
        self.case_rows.append(_row(result))

    # Loop ---------------------------------------------------------------------------------

    def run(self, wall_start: float) -> None:
        batch = 0
        while self.events:
            event = heapq.heappop(self.events)
            self.clock.advance_to(self.at(event.at))
            self.handle(event)
            self.processed += 1
            batch += 1
            if batch >= BATCH_EVENTS:
                self.checkpoint(wall_start)
                batch = 0
        self.checkpoint(wall_start)

    def checkpoint(self, wall_start: float) -> None:
        db = self.db
        db.add_all(self.pending_results)
        self.pending_results = []
        run = db.get(SimulationRun, self.run_id)
        assert run is not None
        run.progress = self.progress(wall_start)
        run.heartbeat_at = datetime.now(UTC)
        db.commit()
        # Keep the session small: nothing loaded so far is needed again.
        db.expunge_all()

    def progress(self, wall_start: float) -> dict[str, Any]:
        return {
            "cases_total": self.applications,
            "cases_started": self.started,
            "cases_completed": self.completed,
            "events_processed": self.processed,
            "events_pending": len(self.events),
            "simulated_now": self.clock.now.isoformat(),
            "wall_seconds": round(time.monotonic() - wall_start, 1),
        }


def _row(result: SimulationCaseResult) -> tuple:
    """The per-case values that must match between reproductions (no ids, no wall time)."""
    return (
        result.case_index,
        result.kind,
        result.expected_outcome,
        result.status,
        result.outcome,
        result.risk_rating,
        result.flags,
        result.manual_reviews,
        result.review_seconds,
        result.queue_wait_seconds,
        result.overdue_tasks,
        result.cycle_seconds,
        result.path,
        result.ai_recommendation,
        result.ai_status,
        result.automated,
    )


# --- Results ----------------------------------------------------------------------------------


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _hours(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds / 3600, 3)


def summarize(rows: list[tuple], sim: _Simulation, wall_ms: int) -> dict[str, Any]:
    by_kind: dict[str, dict[str, int]] = {}
    outcomes: dict[str, int] = {}
    ratings: dict[str, int] = {}
    false_approvals = false_rejections = correct = 0
    cycles: list[float] = []
    waits: list[float] = []
    reviews = review_seconds = overdue = straight_through = 0
    for (
        _,
        kind,
        expected,
        _status,
        outcome,
        rating,
        _flags,
        manual,
        reviewed,
        waited,
        late,
        cycle,
        _path,
        *_ai,
    ) in rows:
        entry = by_kind.setdefault(kind, {"cases": 0, "approved": 0, "rejected": 0, "other": 0})
        entry["cases"] += 1
        key = outcome if outcome in ("approved", "rejected") else "other"
        entry[key] += 1
        outcomes[outcome or "none"] = outcomes.get(outcome or "none", 0) + 1
        if rating:
            ratings[rating] = ratings.get(rating, 0) + 1
        if outcome == expected:
            correct += 1
        elif outcome == "approved":
            false_approvals += 1
        elif outcome == "rejected":
            false_rejections += 1
        if cycle is not None:
            cycles.append(cycle)
        if manual:
            waits.append(waited)
        else:
            straight_through += 1
        reviews += manual
        review_seconds += reviewed
        overdue += late
    total = sim.applications
    finished = len(rows)
    return {
        "cases": total,
        "completed": finished,
        "unfinished": total - finished,
        "outcomes": outcomes,
        "by_kind": dict(sorted(by_kind.items())),
        "risk_ratings": ratings,
        "ground_truth": {
            "correct": correct,
            "false_approvals": false_approvals,
            "false_rejections": false_rejections,
            "accuracy": round(correct / finished, 4) if finished else None,
        },
        "manual_reviews": reviews,
        "straight_through_rate": round(straight_through / finished, 4) if finished else None,
        "review_labor_hours": _hours(review_seconds),
        "overdue_tasks": overdue,
        "cycle_time_hours": {
            "avg": _hours(sum(cycles) / len(cycles)) if cycles else None,
            "p50": _hours(_percentile(cycles, 0.5)),
            "p95": _hours(_percentile(cycles, 0.95)),
            "max": _hours(max(cycles)) if cycles else None,
        },
        "review_queue_wait_hours": {
            "avg": _hours(sum(waits) / len(waits)) if waits else None,
            "p95": _hours(_percentile(waits, 0.95)),
        },
        "staff": {
            "tellers": len(sim.tellers),
            **{f"{step}_reviewers": len(people) for step, people in sim.reviewers.items()},
        },
        "simulated_hours": _hours(sim.clock.elapsed.total_seconds()),
        "ai": _ai_summary(rows, sim.ai_mode),
        "execution": {
            "events_processed": sim.processed,
            "workflow_steps_completed": sum(len(r[12]) for r in rows),
            "wall_ms": wall_ms,
            "cases_per_second": round(finished / (wall_ms / 1000), 2) if wall_ms else None,
        },
    }


def _ai_summary(rows: list[tuple], ai_mode: str | None) -> dict[str, Any] | None:
    """How the AI tool behaved in this run (None for scenarios without AI modes)."""
    if ai_mode is None:
        return None
    statuses: dict[str, int] = {}
    recommendations: dict[str, int] = {}
    decisive = agreed = automated = 0
    for row in rows:
        expected, recommendation, status, was_automated = row[2], row[13], row[14], row[15]
        if status:
            statuses[status] = statuses.get(status, 0) + 1
        if recommendation:
            recommendations[recommendation] = recommendations.get(recommendation, 0) + 1
            if recommendation in ("approve", "reject"):
                decisive += 1
                agreed += (recommendation == "approve") == (expected == "approved")
        automated += bool(was_automated)
    calls = sum(statuses.values())
    return {
        "mode": ai_mode,
        "invocations": calls,
        "invocation_statuses": statuses,
        "failed_invocations": calls - statuses.get("succeeded", 0),
        "recommendations": recommendations,
        "escalations": recommendations.get("escalate", 0),
        "recommendation_accuracy": round(agreed / decisive, 4) if decisive else None,
        "automated_approvals": automated,
    }


# --- Entry point ------------------------------------------------------------------------------


def execute_run(session_factory: sessionmaker[Session], run_id: uuid.UUID) -> None:
    """Run a queued simulation to completion. Failures are recorded on the run, not raised."""
    wall_start = time.monotonic()
    db = session_factory()
    try:
        run = db.get(SimulationRun, run_id)
        if run is None or run.status != SimulationStatus.QUEUED:
            return
        scenario = get_scenario(run.scenario_id, run.scenario_version)
        if scenario is None:
            raise SimulationSetupError(
                f"Scenario {run.scenario_id} v{run.scenario_version} is not registered."
            )
        if registry.get_definition(scenario.workflow_id, run.workflow_version) is None:
            raise SimulationSetupError(
                f"{scenario.workflow_id} v{run.workflow_version} is no longer registered."
            )
        run.status = SimulationStatus.RUNNING.value
        run.started_at = run.heartbeat_at = datetime.now(UTC)
        db.commit()

        sim = _Simulation(db, run, scenario)
        team_id = sim.hire_staff()
        run.staff_unit_id = team_id
        sim.schedule_arrivals()
        sim.run(wall_start)

        wall_ms = round((time.monotonic() - wall_start) * 1000)
        rows = sorted(sim.case_rows)
        run = db.get(SimulationRun, run_id)
        assert run is not None
        run.results = summarize(rows, sim, wall_ms)
        run.result_digest = digest(rows)
        run.simulated_end = sim.clock.now
        run.wall_ms = wall_ms
        run.completed_at = datetime.now(UTC)
        run.progress = sim.progress(wall_start)
        if len(rows) < sim.applications:
            run.status = SimulationStatus.FAILED.value
            run.failure_reason = (
                f"{sim.applications - len(rows)} case(s) were still open when no simulated "
                "event remained (the scenario cannot finish them)."
            )
        else:
            run.status = SimulationStatus.COMPLETED.value
        db.commit()
        logger.info(
            "simulation run finished",
            extra={"run": run.run_number, "status": run.status, "wall_ms": wall_ms},
        )
    except Exception as exc:  # recorded on the run; the caller is a background task
        db.rollback()
        reason = exc.message if isinstance(exc, DomainError) else f"{type(exc).__name__}: {exc}"
        logger.exception("simulation run failed", extra={"run_id": str(run_id)})
        mark_failed(session_factory, run_id, reason, wall_start)
    finally:
        db.close()


def execute_batch(session_factory: sessionmaker[Session], run_ids: list[uuid.UUID]) -> None:
    """Run a suite's runs one after another (each records its own outcome)."""
    for run_id in run_ids:
        execute_run(session_factory, run_id)


def mark_failed(
    session_factory: sessionmaker[Session], run_id: uuid.UUID, reason: str, wall_start: float
) -> None:
    with session_factory() as db:
        run = db.get(SimulationRun, run_id)
        if run is None:
            return
        run.status = SimulationStatus.FAILED.value
        run.failure_reason = reason[:2000]
        run.completed_at = datetime.now(UTC)
        run.wall_ms = round((time.monotonic() - wall_start) * 1000)
        db.commit()
