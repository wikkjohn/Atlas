"""Enterprise metrics. Every figure is a query over the platform's own records; the one
estimate (simulation operating cost) applies the default, stated cost assumptions to what
the runs recorded, through the same cost function experiments use."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import Account
from app.modules.ai_tools.models import AITool, AIToolInvocation, ToolStatus
from app.modules.analytics.schemas import Metric, Overview, RecentExperiment, RecentRun
from app.modules.countries.models import Country, OperationalStatus
from app.modules.employees.models import Employee
from app.modules.experiments.assumptions import CostAssumptions
from app.modules.experiments.evaluation import costs
from app.modules.experiments.models import Experiment, ExperimentEvaluation, ExperimentStatus
from app.modules.workflows import registry, store
from app.modules.workflows.models import (
    STEP_RUN_EXECUTION,
    Realm,
    RunStatus,
    WorkflowEvent,
    WorkflowExecution,
    WorkflowStepRun,
)
from app.simulation.models import (
    SimulationArchive,
    SimulationCaseResult,
    SimulationRun,
    SimulationStatus,
)
from app.simulation.workloads import WORKLOADS, customer_keyed

ESCALATION_STEPS = sorted({step for w in WORKLOADS.values() for step in w.escalation_steps})

AI_ERRORS = ("failed", "timeout", "invalid_input", "invalid_output")


def _count(db: Session, query) -> int:
    return db.execute(query).scalar_one()


def simulation_costs(db: Session, assumptions: CostAssumptions) -> tuple[float, int]:
    """Estimated operating cost of every completed simulation run (default assumptions)."""
    runs = list(
        db.execute(
            select(SimulationRun.id).where(SimulationRun.status == SimulationStatus.COMPLETED)
        ).scalars()
    )
    if not runs:
        return 0.0, 0
    case = SimulationCaseResult
    per_run = {
        row.run_id: row
        for row in db.execute(
            select(
                case.run_id,
                func.count().label("cases"),
                func.count().filter(case.status == "completed").label("completed"),
                func.coalesce(func.sum(case.review_seconds), 0).label("review_seconds"),
                func.count().filter(case.automated.is_(True)).label("automated"),
                # Escalation steps are workflow-specific, so their union counts each run's own.
                func.count()
                .filter(or_(*(case.path.contains([step]) for step in ESCALATION_STEPS)))
                .label("escalations"),
                func.coalesce(func.sum(case.overdue_tasks), 0).label("overdue"),
                func.count()
                .filter(case.outcome == "approved", case.expected_outcome == "rejected")
                .label("fa"),
                func.count()
                .filter(case.outcome == "rejected", case.expected_outcome == "approved")
                .label("fr"),
            )
            .where(case.run_id.in_(runs))
            .group_by(case.run_id)
        ).all()
    }
    failed = dict(
        db.execute(
            select(WorkflowExecution.simulation_run_id, func.count())
            .where(
                WorkflowExecution.realm == Realm.SIMULATION,
                WorkflowExecution.simulation_run_id.in_(runs),
                WorkflowExecution.status == "failed",
            )
            .group_by(WorkflowExecution.simulation_run_id)
        ).all()
    )
    timeouts = dict(
        db.execute(
            select(WorkflowExecution.simulation_run_id, func.count())
            .join(
                WorkflowEvent,
                and_(
                    WorkflowEvent.execution_id == WorkflowExecution.id,
                    WorkflowEvent.realm == WorkflowExecution.realm,
                ),
            )
            .where(
                WorkflowExecution.realm == Realm.SIMULATION,
                WorkflowExecution.simulation_run_id.in_(runs),
                WorkflowEvent.event_type == "step.timed_out",
            )
            .group_by(WorkflowExecution.simulation_run_id)
        ).all()
    )
    calls: dict[Any, dict[str, int]] = {}
    for run_id, status, n in db.execute(
        select(AIToolInvocation.simulation_run_id, AIToolInvocation.status, func.count())
        .where(AIToolInvocation.simulation_run_id.in_(runs))
        .group_by(AIToolInvocation.simulation_run_id, AIToolInvocation.status)
    ).all():
        calls.setdefault(run_id, {})[status] = n
    # Runs whose history was archived or purged: the counts saved when it was removed.
    for run_id, summary in db.execute(
        select(SimulationArchive.run_id, SimulationArchive.summary).where(
            SimulationArchive.run_id.in_(runs), SimulationArchive.restored_at.is_(None)
        )
    ).all():
        failed[run_id] = summary["failed_executions"]
        timeouts[run_id] = summary["document_timeouts"]
        calls[run_id] = summary["ai_calls"]
    total = 0.0
    for run_id, row in per_run.items():
        statuses = calls.get(run_id, {})
        ai_errors = sum(statuses.get(s, 0) for s in AI_ERRORS)
        measurement = {
            "cases": row.cases,
            "completed": row.completed,
            "review_seconds": row.review_seconds,
            "automated_approvals": row.automated,
            "escalations": row.escalations,
            "exceptions": row.overdue + timeouts.get(run_id, 0) + failed.get(run_id, 0) + ai_errors,
            "false_approvals": row.fa,
            "false_rejections": row.fr,
            "ai": {"executed_invocations": sum(statuses.values()) - statuses.get("blocked", 0)},
        }
        total += costs(measurement, assumptions)["operating_total"]
    return round(total, 2), len(per_run)


def overview(db: Session) -> Overview:
    staff_units = select(SimulationRun.staff_unit_id).where(
        SimulationRun.staff_unit_id.is_not(None)
    )
    employees = _count(
        db,
        select(func.count())
        .select_from(Employee)
        .where(Employee.employment_status != "terminated"),
    )
    simulated_staff = _count(
        db,
        select(func.count()).select_from(Employee).where(Employee.organization_id.in_(staff_units)),
    )
    countries = _count(db, select(func.count()).select_from(Country))
    active_countries = _count(
        db,
        select(func.count())
        .select_from(Country)
        .where(Country.operational_status == OperationalStatus.ACTIVE),
    )
    workflow_ids = store.workflow_ids(db)
    versions = len(registry.all_definitions()) + len(store.stored_records(db))

    live = WorkflowExecution.realm == Realm.LIVE
    outcomes = dict(
        db.execute(
            select(WorkflowExecution.status, func.count())
            .where(live)
            .group_by(WorkflowExecution.status)
        ).all()
    )
    simulated_outcomes = dict(
        db.execute(
            select(WorkflowExecution.status, func.count())
            .where(WorkflowExecution.realm == Realm.SIMULATION)
            .group_by(WorkflowExecution.status)
        ).all()
    )
    open_tasks = _count(
        db,
        select(func.count())
        .select_from(WorkflowStepRun)
        .join(WorkflowExecution, STEP_RUN_EXECUTION)
        .where(
            live,
            WorkflowStepRun.status == RunStatus.WAITING,
            WorkflowStepRun.step_type.in_(["approval", "human_task"]),
        ),
    )
    avg_live_ms = db.execute(
        select(
            func.avg(
                func.extract("epoch", WorkflowExecution.completed_at - WorkflowExecution.started_at)
                * 1000
            )
        ).where(live, WorkflowExecution.completed_at.is_not(None))
    ).scalar_one()
    avg_sim_seconds = db.execute(
        select(func.avg(SimulationCaseResult.cycle_seconds)).where(
            SimulationCaseResult.cycle_seconds.is_not(None)
        )
    ).scalar_one()

    accounts = _count(db, select(func.count()).select_from(Account))
    simulated_customers = customer_keyed(WorkflowExecution.realm == Realm.SIMULATION)
    simulated_accounts = _count(
        db,
        select(func.count())
        .select_from(Account)
        .where(Account.customer_id.in_(simulated_customers)),
    )
    # Plus those of runs whose history was archived or purged (counted when it was removed).
    simulated_accounts += db.execute(
        select(
            func.coalesce(func.sum(SimulationArchive.summary["accounts"].as_integer()), 0)
        ).where(SimulationArchive.restored_at.is_(None))
    ).scalar_one()

    runs_by_status = dict(
        db.execute(select(SimulationRun.status, func.count()).group_by(SimulationRun.status)).all()
    )
    tools = _count(db, select(func.count()).select_from(AITool))
    active_tools = _count(
        db, select(func.count()).select_from(AITool).where(AITool.status == ToolStatus.ACTIVE)
    )
    experiments_done = _count(
        db,
        select(func.count())
        .select_from(Experiment)
        .where(Experiment.status == ExperimentStatus.COMPLETED),
    )
    successful = _count(
        db,
        select(func.count())
        .select_from(ExperimentEvaluation)
        .where(ExperimentEvaluation.verdict == "successful"),
    )
    assumptions = CostAssumptions()
    sim_cost, costed_runs = simulation_costs(db, assumptions)

    metrics = [
        Metric(
            key="employees",
            label="Employees",
            value=employees,
            unit="count",
            detail=f"{employees - simulated_staff:,} enterprise staff and {simulated_staff:,} "
            "simulated staff hired by simulation runs (not terminated)",
        ),
        Metric(
            key="countries",
            label="Configured countries",
            value=countries,
            unit="count",
            detail=f"{active_countries} active",
        ),
        Metric(
            key="workflows",
            label="Registered workflows",
            value=len(workflow_ids),
            unit="count",
            detail=f"{versions} definition version(s)",
            synthetic=False,
        ),
        Metric(
            key="active_simulations",
            label="Active simulation runs",
            value=runs_by_status.get("running", 0) + runs_by_status.get("queued", 0),
            unit="count",
            detail=f"{runs_by_status.get('completed', 0)} completed, "
            f"{runs_by_status.get('failed', 0)} failed",
        ),
        Metric(
            key="completed_executions",
            label="Completed workflow executions",
            value=outcomes.get("completed", 0),
            unit="count",
            detail=f"Live cases; plus {simulated_outcomes.get('completed', 0):,} simulated",
        ),
        Metric(
            key="failed_executions",
            label="Failed workflow executions",
            value=outcomes.get("failed", 0),
            unit="count",
            detail=f"Live cases; plus {simulated_outcomes.get('failed', 0):,} simulated",
        ),
        Metric(
            key="accounts",
            label="Customer accounts created",
            value=accounts,
            unit="count",
            detail=f"{simulated_accounts:,} of them opened by simulation runs",
        ),
        Metric(
            key="ai_tools",
            label="Registered AI tools",
            value=tools,
            unit="count",
            detail=f"{active_tools} active version(s)",
            synthetic=False,
        ),
        Metric(
            key="experiments",
            label="Completed experiments",
            value=experiments_done,
            unit="count",
            detail=f"{successful} met every success criterion",
        ),
        Metric(
            key="avg_process_duration",
            label="Average process duration",
            value=round(avg_sim_seconds / 3600, 2) if avg_sim_seconds is not None else None,
            unit="hours",
            detail="Simulated cases of every workflow, arrival to decision"
            + (
                f"; live cases {float(avg_live_ms) / 1000:,.1f} s"
                if avg_live_ms is not None
                else ""
            ),
        ),
        Metric(
            key="simulation_cost",
            label="Estimated simulation operating cost",
            value=sim_cost,
            unit="currency",
            detail=f"{costed_runs} completed run(s) at the default assumptions "
            f"({assumptions.currency_label}); an estimate, not spending",
            estimate=True,
        ),
    ]
    recent_runs = db.execute(
        select(SimulationRun).order_by(SimulationRun.run_number.desc()).limit(5)
    ).scalars()
    recent_experiments = db.execute(
        select(Experiment, ExperimentEvaluation.verdict)
        .outerjoin(ExperimentEvaluation, ExperimentEvaluation.experiment_id == Experiment.id)
        .order_by(Experiment.experiment_number.desc())
        .limit(5)
    ).all()
    return Overview(
        generated_at=datetime.now(UTC),
        metrics=metrics,
        workflow_outcomes={str(k): v for k, v in outcomes.items()},
        open_tasks=open_tasks,
        simulation_runs_by_status={str(k): v for k, v in runs_by_status.items()},
        cost_assumptions=assumptions.model_dump(mode="json"),
        recent_runs=[
            RecentRun(
                id=r.id,
                run_number=r.run_number,
                mode=r.mode,
                status=r.status,
                applications=r.config["applications"],
                created_at=r.created_at,
            )
            for r in recent_runs
        ],
        recent_experiments=[
            RecentExperiment(
                id=e.id,
                experiment_number=e.experiment_number,
                name=e.name,
                status=e.status,
                verdict=verdict,
                tool_id=e.tool_id,
                created_at=e.created_at,
            )
            for e, verdict in recent_experiments
        ],
    )
