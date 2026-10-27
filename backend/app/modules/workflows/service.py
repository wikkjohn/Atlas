"""Read models for the workflow API: definitions, executions, history, tasks, metrics."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import DomainError, NotFoundError
from app.core.pagination import PageParams, paginate
from app.modules.identity.models import User
from app.modules.identity.service import AuthenticatedUser
from app.modules.workflows import registry
from app.modules.workflows.definition import StepType, WorkflowDefinition
from app.modules.workflows.engine import check_task_access
from app.modules.workflows.models import (
    RunStatus,
    WorkflowEvent,
    WorkflowExecution,
    WorkflowStepRun,
)
from app.modules.workflows.schemas import (
    ExecutionDetail,
    ExecutionSummary,
    StepMetric,
    StepRunOut,
    TaskOut,
    WorkflowDefinitionOut,
    WorkflowEventOut,
    WorkflowMetrics,
    WorkflowSummary,
)


def _versions(workflow_id: str) -> list[int]:
    return sorted(d.version for d in registry.all_definitions() if d.workflow_id == workflow_id)


def summary(definition: WorkflowDefinition) -> WorkflowSummary:
    return WorkflowSummary(
        workflow_id=definition.workflow_id,
        name=definition.name,
        version=definition.version,
        versions=_versions(definition.workflow_id),
        description=definition.description,
        business_owner=definition.business_owner,
        trigger_type=definition.trigger_type,
        step_count=len(definition.steps),
    )


def list_workflows(q: str | None = None) -> list[WorkflowSummary]:
    latest: dict[str, WorkflowDefinition] = {}
    for definition in registry.all_definitions():
        latest[definition.workflow_id] = definition  # sorted by version, so last wins
    items = [summary(d) for d in latest.values()]
    if q:
        needle = q.casefold()
        items = [
            w
            for w in items
            if needle in f"{w.workflow_id} {w.name} {w.description} {w.business_owner}".casefold()
        ]
    return items


def get_definition(workflow_id: str, version: int | None = None) -> WorkflowDefinition:
    definition = registry.get_definition(workflow_id, version)
    if definition is None:
        raise NotFoundError(f"Workflow {workflow_id} is not registered.")
    return definition


def definition_out(definition: WorkflowDefinition) -> WorkflowDefinitionOut:
    return WorkflowDefinitionOut(
        **summary(definition).model_dump(),
        start=definition.start,
        input_schema=definition.input_schema,
        steps=[s.model_dump(mode="json", exclude_none=True) for s in definition.steps],
        transition_rules=definition.transition_rules(),
        approval_policies=definition.approval_policies(),
        failure_policies=definition.failure_policies(),
        timeout_policies=definition.timeout_policies(),
    )


def _usernames(db: Session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.username).where(User.id.in_(ids))).all())


def _summary(e: WorkflowExecution, names: dict[uuid.UUID, str]) -> ExecutionSummary:
    duration = (
        int((e.completed_at - e.started_at).total_seconds() * 1000) if e.completed_at else None
    )
    return ExecutionSummary(
        id=e.id,
        workflow_id=e.workflow_id,
        workflow_version=e.workflow_version,
        status=e.status,
        outcome=e.outcome,
        current_steps=e.current_steps,
        business_key=e.business_key,
        applicant=(e.context.get("input") or {}).get("applicant_name"),
        initiated_by=e.initiated_by,
        initiated_by_username=names.get(e.initiated_by),
        correlation_id=e.correlation_id,
        started_at=e.started_at,
        completed_at=e.completed_at,
        duration_ms=duration,
    )


def list_executions(
    db: Session,
    params: PageParams,
    *,
    workflow_id: str | None = None,
    status: str | None = None,
    outcome: str | None = None,
    business_key: str | None = None,
) -> tuple[list[ExecutionSummary], int]:
    query = select(WorkflowExecution).order_by(
        WorkflowExecution.started_at.desc(), WorkflowExecution.id
    )
    if workflow_id:
        query = query.where(WorkflowExecution.workflow_id == workflow_id)
    if status:
        query = query.where(WorkflowExecution.status == status)
    if outcome:
        query = query.where(WorkflowExecution.outcome == outcome)
    if business_key:
        query = query.where(WorkflowExecution.business_key == business_key)
    items, total = paginate(db, query, params)
    names = _usernames(db, {e.initiated_by for e in items})
    return [_summary(e, names) for e in items], total


def get_execution(db: Session, execution_id: uuid.UUID) -> WorkflowExecution:
    execution = db.get(WorkflowExecution, execution_id)
    if execution is None:
        raise NotFoundError("Workflow execution not found.")
    return execution


def _step_name(execution: WorkflowExecution, step_id: str) -> str:
    definition = registry.get_definition(execution.workflow_id, execution.workflow_version)
    try:
        return definition.step(step_id).name if definition else step_id
    except KeyError:
        return step_id


def execution_detail(db: Session, execution: WorkflowExecution) -> ExecutionDetail:
    runs = list(
        db.execute(
            select(WorkflowStepRun)
            .where(WorkflowStepRun.execution_id == execution.id)
            .order_by(WorkflowStepRun.sequence)
        ).scalars()
    )
    names = _usernames(db, {execution.initiated_by} | {r.actor_id for r in runs})
    return ExecutionDetail(
        **_summary(execution, names).model_dump(),
        context=execution.context,
        error=execution.error,
        steps=[
            StepRunOut(
                id=r.id,
                sequence=r.sequence,
                step_id=r.step_id,
                step_name=_step_name(execution, r.step_id),
                step_type=r.step_type,
                status=r.status,
                branch=r.branch,
                attempt=r.attempt,
                required_permissions=r.required_permissions,
                actor_id=r.actor_id,
                actor_username=names.get(r.actor_id) if r.actor_id else None,
                output=r.output,
                error=r.error,
                created_at=r.created_at,
                started_at=r.started_at,
                completed_at=r.completed_at,
                duration_ms=r.duration_ms,
                not_before=r.not_before,
                due_at=r.due_at,
                escalated_at=r.escalated_at,
            )
            for r in runs
        ],
    )


def history(db: Session, execution_id: uuid.UUID) -> list[WorkflowEventOut]:
    events = db.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.execution_id == execution_id)
        .order_by(WorkflowEvent.seq)
    ).scalars()
    return [
        WorkflowEventOut(
            id=e.id,
            event_type=e.event_type,
            occurred_at=e.occurred_at,
            step_run_id=e.step_run_id,
            actor_id=e.actor_id,
            data=e.data,
        )
        for e in events
    ]


def open_tasks(
    db: Session, user: AuthenticatedUser, params: PageParams, *, actionable_only: bool
) -> tuple[list[TaskOut], int]:
    """Open human tasks and approvals, each marked with whether `user` may act on it."""
    rows = db.execute(
        select(WorkflowStepRun, WorkflowExecution)
        .join(WorkflowExecution, WorkflowExecution.id == WorkflowStepRun.execution_id)
        .where(
            WorkflowStepRun.status == RunStatus.WAITING,
            WorkflowStepRun.step_type.in_([StepType.APPROVAL, StepType.HUMAN_TASK]),
        )
        .order_by(WorkflowStepRun.due_at.asc().nullslast(), WorkflowStepRun.created_at)
    ).all()
    names = _usernames(db, {e.initiated_by for _, e in rows})
    tasks: list[TaskOut] = []
    for run, execution in rows:
        definition = registry.get_definition(execution.workflow_id, execution.workflow_version)
        if definition is None:
            continue
        step = definition.step(run.step_id)
        blocked = None
        try:
            check_task_access(db, execution, step, user)
        except DomainError as exc:
            blocked = exc.message
        if actionable_only and blocked:
            continue
        ctx: dict[str, Any] = execution.context
        tasks.append(
            TaskOut(
                run_id=run.id,
                execution_id=execution.id,
                workflow_id=execution.workflow_id,
                step_id=run.step_id,
                step_name=step.name,
                step_type=run.step_type,
                opened_at=run.started_at,
                due_at=run.due_at,
                overdue=run.escalated_at is not None,
                required_permissions=run.required_permissions,
                can_act=blocked is None,
                blocked_reason=blocked,
                applicant=(ctx.get("input") or {}).get("applicant_name"),
                risk_rating=(ctx.get("assign_risk_rating") or {}).get("rating"),
                flags=(ctx.get("evaluate_compliance") or {}).get("flags") or [],
                initiated_by_username=names.get(execution.initiated_by),
            )
        )
    total = len(tasks)
    return tasks[params.offset : params.offset + params.limit], total


def metrics(db: Session, workflow_id: str) -> WorkflowMetrics:
    """Throughput, durations and failures per step: where cases slow down or break."""
    definition = get_definition(workflow_id)
    statuses = dict(
        db.execute(
            select(WorkflowExecution.status, func.count())
            .where(WorkflowExecution.workflow_id == workflow_id)
            .group_by(WorkflowExecution.status)
        ).all()
    )
    outcomes = dict(
        db.execute(
            select(WorkflowExecution.outcome, func.count())
            .where(
                WorkflowExecution.workflow_id == workflow_id,
                WorkflowExecution.outcome.is_not(None),
            )
            .group_by(WorkflowExecution.outcome)
        ).all()
    )
    avg_execution = db.execute(
        select(
            func.avg(
                func.extract("epoch", WorkflowExecution.completed_at - WorkflowExecution.started_at)
                * 1000
            )
        ).where(
            WorkflowExecution.workflow_id == workflow_id,
            WorkflowExecution.completed_at.is_not(None),
        )
    ).scalar_one()
    rows = {
        row.step_id: row
        for row in db.execute(
            select(
                WorkflowStepRun.step_id,
                func.count().label("runs"),
                func.count()
                .filter(WorkflowStepRun.status == RunStatus.COMPLETED)
                .label("completed"),
                func.count().filter(WorkflowStepRun.status == RunStatus.FAILED).label("failed"),
                func.count()
                .filter(WorkflowStepRun.status.in_([RunStatus.PENDING, RunStatus.WAITING]))
                .label("open"),
                func.coalesce(func.sum(func.greatest(WorkflowStepRun.attempt - 1, 0)), 0).label(
                    "retries"
                ),
                func.avg(WorkflowStepRun.duration_ms).label("avg_ms"),
                func.percentile_cont(0.5).within_group(WorkflowStepRun.duration_ms).label("p50"),
                func.percentile_cont(0.95).within_group(WorkflowStepRun.duration_ms).label("p95"),
                func.max(WorkflowStepRun.duration_ms).label("max_ms"),
            )
            .join(WorkflowExecution, WorkflowExecution.id == WorkflowStepRun.execution_id)
            .where(WorkflowExecution.workflow_id == workflow_id)
            .group_by(WorkflowStepRun.step_id)
        ).all()
    }
    steps = []
    for step in definition.steps:
        row = rows.get(step.id)
        steps.append(
            StepMetric(
                step_id=step.id,
                step_name=step.name,
                step_type=step.type.value,
                runs=row.runs if row else 0,
                completed=row.completed if row else 0,
                failed=row.failed if row else 0,
                open=row.open if row else 0,
                retries=int(row.retries) if row else 0,
                avg_ms=float(row.avg_ms) if row and row.avg_ms is not None else None,
                p50_ms=float(row.p50) if row and row.p50 is not None else None,
                p95_ms=float(row.p95) if row and row.p95 is not None else None,
                max_ms=row.max_ms if row else None,
            )
        )
    measured = [s for s in steps if s.p95_ms is not None]
    bottleneck = max(measured, key=lambda s: s.p95_ms or 0).step_id if measured else None
    return WorkflowMetrics(
        workflow_id=workflow_id,
        executions={str(k): v for k, v in statuses.items()},
        outcomes={str(k): v for k, v in outcomes.items()},
        avg_execution_ms=float(avg_execution) if avg_execution is not None else None,
        bottleneck_step=bottleneck,
        steps=steps,
    )
