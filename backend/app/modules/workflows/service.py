"""Read models for the workflow API: definitions, executions, history, tasks, metrics."""

import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.errors import DomainError, NotFoundError
from app.core.pagination import PageParams, paginate
from app.modules.identity.models import User
from app.modules.identity.service import AuthenticatedUser
from app.modules.workflows import library, registry, store, validation
from app.modules.workflows.definition import StepType, WorkflowDefinition
from app.modules.workflows.engine import check_task_access
from app.modules.workflows.models import (
    STEP_RUN_EXECUTION,
    DefinitionStatus,
    Realm,
    RunStatus,
    WorkflowDefinitionRecord,
    WorkflowEvent,
    WorkflowExecution,
    WorkflowStepRun,
)
from app.modules.workflows.schemas import (
    ExecutionDetail,
    ExecutionSummary,
    LibraryHandlerOut,
    StepMetric,
    StepRunOut,
    StoredDefinitionOut,
    TaskOut,
    ValidationReportOut,
    WorkflowDefinitionOut,
    WorkflowEventOut,
    WorkflowMetrics,
    WorkflowSummary,
)


def summary(
    definition: WorkflowDefinition,
    versions: list[int],
    source: str = "code",
    status: str = "active",
) -> WorkflowSummary:
    return WorkflowSummary(
        workflow_id=definition.workflow_id,
        name=definition.name,
        version=definition.version,
        versions=versions,
        description=definition.description,
        business_owner=definition.business_owner,
        trigger_type=definition.trigger_type,
        step_count=len(definition.steps),
        source=source,
        status=status,
    )


def _catalogue(db: Session) -> dict[str, tuple[WorkflowDefinition, list[int], str, str]]:
    """Each workflow's latest (active) definition, its versions, source and status."""
    found: dict[str, tuple[WorkflowDefinition, list[int], str, str]] = {}
    for definition in registry.all_definitions():  # sorted by version, so last wins
        versions = [*found.get(definition.workflow_id, (None, []))[1], definition.version]
        found[definition.workflow_id] = (definition, versions, "code", "active")
    by_workflow: dict[str, list[WorkflowDefinitionRecord]] = {}
    for record in store.stored_records(db):
        by_workflow.setdefault(record.workflow_id, []).append(record)
    for workflow_id, records in by_workflow.items():
        active = [r for r in records if r.status == DefinitionStatus.ACTIVE]
        shown = (active or records)[-1]
        found[workflow_id] = (
            store.parsed(shown),
            [r.version for r in records],
            "stored",
            shown.status,
        )
    return dict(sorted(found.items()))


def list_workflows(db: Session, q: str | None = None) -> list[WorkflowSummary]:
    items = [summary(*entry) for entry in _catalogue(db).values()]
    if q:
        needle = q.casefold()
        items = [
            w
            for w in items
            if needle in f"{w.workflow_id} {w.name} {w.description} {w.business_owner}".casefold()
        ]
    return items


def get_definition(db: Session, workflow_id: str, version: int | None = None) -> WorkflowDefinition:
    definition = store.resolve(db, workflow_id, version)
    if definition is None:
        raise NotFoundError(f"Workflow {workflow_id} is not registered.")
    return definition


def definition_out(db: Session, definition: WorkflowDefinition) -> WorkflowDefinitionOut:
    entry = _catalogue(db).get(definition.workflow_id)
    versions, source = (entry[1], entry[2]) if entry else ([definition.version], "code")
    status = "active"
    if source == "stored":
        record = store.stored_record(db, definition.workflow_id, definition.version)
        status = record.status if record else "active"
    return WorkflowDefinitionOut(
        **summary(definition, versions, source, status).model_dump(),
        start=definition.start,
        input_schema=definition.input_schema,
        presentation=(
            definition.presentation.model_dump(exclude_none=True)
            if definition.presentation
            else None
        ),
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


def _summary(db: Session, e: WorkflowExecution, names: dict[uuid.UUID, str]) -> ExecutionSummary:
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
        subject=store.present(db, e)["subject"],
        initiated_by=e.initiated_by,
        initiated_by_username=names.get(e.initiated_by),
        correlation_id=e.correlation_id,
        started_at=e.started_at,
        completed_at=e.completed_at,
        duration_ms=duration,
        simulation_run_id=e.simulation_run_id,
    )


def list_executions(
    db: Session,
    params: PageParams,
    *,
    workflow_id: str | None = None,
    status: str | None = None,
    outcome: str | None = None,
    business_key: str | None = None,
    simulation_run_id: uuid.UUID | None = None,
) -> tuple[list[ExecutionSummary], int]:
    query = select(WorkflowExecution).order_by(
        WorkflowExecution.started_at.desc(), WorkflowExecution.id
    )
    # Simulated executions are listed only for their own run.
    query = query.where(
        and_(
            WorkflowExecution.realm == Realm.SIMULATION,
            WorkflowExecution.simulation_run_id == simulation_run_id,
        )
        if simulation_run_id
        else WorkflowExecution.realm == Realm.LIVE
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
    return [_summary(db, e, names) for e in items], total


def get_execution(db: Session, execution_id: uuid.UUID) -> WorkflowExecution:
    execution = db.get(WorkflowExecution, execution_id)
    if execution is None:
        raise NotFoundError("Workflow execution not found.")
    return execution


def _step_name(db: Session, execution: WorkflowExecution, step_id: str) -> str:
    definition = store.for_execution(db, execution)
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
        **_summary(db, execution, names).model_dump(),
        context=execution.context,
        error=execution.error,
        steps=[
            StepRunOut(
                id=r.id,
                sequence=r.sequence,
                step_id=r.step_id,
                step_name=_step_name(db, execution, r.step_id),
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
        .join(WorkflowExecution, STEP_RUN_EXECUTION)
        .where(
            WorkflowStepRun.status == RunStatus.WAITING,
            WorkflowStepRun.step_type.in_([StepType.APPROVAL, StepType.HUMAN_TASK]),
            WorkflowExecution.realm == Realm.LIVE,
        )
        .order_by(WorkflowStepRun.due_at.asc().nullslast(), WorkflowStepRun.created_at)
    ).all()
    names = _usernames(db, {e.initiated_by for _, e in rows})
    tasks: list[TaskOut] = []
    for run, execution in rows:
        definition = store.for_execution(db, execution)
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
        shown = store.present(db, execution)
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
                subject=shown["subject"],
                risk_rating=shown["risk_rating"],
                flags=shown["flags"],
                initiated_by_username=names.get(execution.initiated_by),
            )
        )
    total = len(tasks)
    return tasks[params.offset : params.offset + params.limit], total


def metrics(db: Session, workflow_id: str) -> WorkflowMetrics:
    """Throughput, durations and failures per step: where cases slow down or break."""
    definition = get_definition(db, workflow_id)
    statuses = dict(
        db.execute(
            select(WorkflowExecution.status, func.count())
            .where(
                WorkflowExecution.workflow_id == workflow_id,
                WorkflowExecution.realm == Realm.LIVE,
            )
            .group_by(WorkflowExecution.status)
        ).all()
    )
    outcomes = dict(
        db.execute(
            select(WorkflowExecution.outcome, func.count())
            .where(
                WorkflowExecution.workflow_id == workflow_id,
                WorkflowExecution.realm == Realm.LIVE,
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
            WorkflowExecution.realm == Realm.LIVE,
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
            .join(WorkflowExecution, STEP_RUN_EXECUTION)
            .where(
                WorkflowExecution.workflow_id == workflow_id,
                WorkflowExecution.realm == Realm.LIVE,
            )
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


def stored_definition_out(
    db: Session, record: WorkflowDefinitionRecord, names: dict[uuid.UUID, str] | None = None
) -> StoredDefinitionOut:
    names = names if names is not None else _usernames(db, {record.imported_by})
    executions = db.execute(
        select(func.count()).where(WorkflowExecution.definition_id == record.id)
    ).scalar_one()
    return StoredDefinitionOut(
        id=record.id,
        workflow_id=record.workflow_id,
        version=record.version,
        name=record.name,
        status=record.status,
        content_hash=record.content_hash,
        step_count=len(record.definition.get("steps", [])),
        imported_by=record.imported_by,
        imported_by_username=names.get(record.imported_by) if record.imported_by else None,
        imported_at=record.registered_at,
        status_changed_at=record.status_changed_at,
        executions=executions,
    )


def stored_definitions(db: Session) -> list[StoredDefinitionOut]:
    records = store.stored_records(db)
    names = _usernames(db, {r.imported_by for r in records})
    return [stored_definition_out(db, r, names) for r in records]


def library_handlers() -> list[LibraryHandlerOut]:
    return [
        LibraryHandlerOut(
            name=h.name,
            step_type=h.step_type.value,
            summary=h.summary,
            output=h.output,
            params_schema=h.params_schema(),
        )
        for h in sorted(library.LIBRARY.values(), key=lambda h: h.name)
    ]


def report_out(report: validation.Report) -> ValidationReportOut:
    d = report.definition
    return ValidationReportOut(
        valid=report.valid,
        workflow_id=d.workflow_id if d else None,
        version=d.version if d else None,
        content_hash=d.content_hash() if d else None,
        existing=report.existing if report.valid else None,
        errors=report.errors,
        warnings=report.warnings,
    )
