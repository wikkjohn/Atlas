"""Durable, database-backed workflow engine.

Execution model
- Every state change is a row change in PostgreSQL; nothing lives only in memory.
- `advance` locks the execution row (SELECT … FOR UPDATE), so two workers can never run
  the same execution, and therefore never the same step, at the same time.
- A step's handler runs inside a savepoint together with its state transition: either
  both commit or neither does. If the process dies mid-step, the transaction rolls back
  and the step is still `pending`, so `run_due` simply runs it again on resume.
- Failures are retried with exponential backoff (`not_before`); when retries are
  exhausted the step's `on_failure` route is taken, or the execution fails.
- Human tasks and approvals wait for an authorized person; wait states for a signal or a
  timer. Time is always passed in (`now`) so the simulation clock can drive it.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from app.core.audit import record_audit_event
from app.core.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.logging import correlation_id_var
from app.core.permissions import Permission
from app.modules.identity.service import AuthenticatedUser
from app.modules.workflows import registry
from app.modules.workflows.definition import (
    HANDLER_TYPES,
    WAITING_TYPES,
    RetryPolicy,
    StepDefinition,
    StepType,
    WorkflowDefinition,
    resolve,
)
from app.modules.workflows.models import (
    ACTIVE_STATUSES,
    ExecutionStatus,
    RunStatus,
    WorkflowDefinitionRecord,
    WorkflowEvent,
    WorkflowExecution,
    WorkflowStepRun,
)

logger = logging.getLogger("atlas.workflows")

MAX_STEPS_PER_ADVANCE = 500


class StepError(Exception):
    """A business failure inside a step. Not retried."""

    def __init__(self, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class RetryableStepError(StepError):
    """A transient failure (e.g. a dependency was unavailable). Retried per policy."""


class WorkflowInputError(DomainError):
    status_code = 422
    code = "validation_error"


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class StepContext:
    """What a step handler receives."""

    db: Session
    execution: WorkflowExecution
    run: WorkflowStepRun
    step: StepDefinition
    now: datetime

    @property
    def input(self) -> dict[str, Any]:
        return self.execution.context["input"]

    @property
    def context(self) -> dict[str, Any]:
        return self.execution.context

    @property
    def initiator_id(self) -> uuid.UUID:
        return self.execution.initiated_by

    def get(self, path: str, default: Any = None) -> Any:
        found, value = resolve(self.execution.context, path)
        return value if found else default

    def set(self, key: str, value: Any) -> None:
        self.execution.context[key] = value
        flag_modified(self.execution, "context")

    def set_outcome(self, outcome: str) -> None:
        self.set("outcome", outcome)

    def set_business_key(self, key: str) -> None:
        self.execution.business_key = key


# --- Definitions ----------------------------------------------------------------------------


def definition_record(db: Session, definition: WorkflowDefinition) -> WorkflowDefinitionRecord:
    """The stored snapshot of this definition version (created on first use)."""
    digest = definition.content_hash()
    db.execute(
        insert(WorkflowDefinitionRecord)
        .values(
            id=uuid.uuid4(),
            workflow_id=definition.workflow_id,
            version=definition.version,
            name=definition.name,
            definition=definition.canonical_json(),
            content_hash=digest,
        )
        .on_conflict_do_nothing(index_elements=["workflow_id", "version"])
    )
    record = db.execute(
        select(WorkflowDefinitionRecord).where(
            WorkflowDefinitionRecord.workflow_id == definition.workflow_id,
            WorkflowDefinitionRecord.version == definition.version,
        )
    ).scalar_one()
    if record.content_hash != digest:
        raise ConflictError(
            f"{definition.workflow_id} v{definition.version} changed after it was first used; "
            "definitions are immutable — publish a new version."
        )
    return record


def _definition_for(execution: WorkflowExecution) -> WorkflowDefinition:
    definition = registry.get_definition(execution.workflow_id, execution.workflow_version)
    if definition is None:
        raise ConflictError(
            f"{execution.workflow_id} v{execution.workflow_version} is not loaded in this "
            "process; it cannot be advanced."
        )
    return definition


# --- The driver: all mutations of one locked execution ---------------------------------------


@dataclass
class _Driver:
    db: Session
    definition: WorkflowDefinition
    execution: WorkflowExecution
    now: datetime
    # Real time: re-read the clock before each step so durations are measured. With an
    # explicit `now` (tests, the simulation clock) time stands still within one advance.
    live: bool = False
    _pending_audit: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    # Events and bookkeeping

    def event(
        self,
        event_type: str,
        run: WorkflowStepRun | None = None,
        actor_id: uuid.UUID | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.db.add(
            WorkflowEvent(
                execution_id=self.execution.id,
                step_run_id=run.id if run is not None else None,
                event_type=event_type,
                occurred_at=self.now,
                actor_id=actor_id,
                data=data or {},
            )
        )

    def touch(self) -> None:
        self.execution.updated_at = self.now
        flag_modified(self.execution, "context")

    def sync_current_steps(self) -> None:
        self.db.flush()
        self.execution.current_steps = list(
            self.db.execute(
                select(WorkflowStepRun.step_id)
                .where(
                    WorkflowStepRun.execution_id == self.execution.id,
                    WorkflowStepRun.status.in_([RunStatus.PENDING, RunStatus.WAITING]),
                )
                .order_by(WorkflowStepRun.sequence)
            ).scalars()
        )

    # Scheduling and routing

    def schedule(self, step_id: str, branch: str | None = None) -> WorkflowStepRun:
        step = self.definition.step(step_id)
        self.execution.step_counter += 1
        run = WorkflowStepRun(
            execution_id=self.execution.id,
            sequence=self.execution.step_counter,
            step_id=step.id,
            step_type=step.type.value,
            status=RunStatus.PENDING.value,
            branch=branch,
            attempt=0,
            required_permissions=list(step.approval.permissions) if step.approval else [],
            created_at=self.now,
        )
        self.db.add(run)
        self.db.flush()
        self.event("step.scheduled", run, data={"step": step.id, "branch": branch})
        return run

    def choose(self, step: StepDefinition) -> str | None:
        for transition in step.transitions:
            if transition.when is None or transition.when.evaluate(self.execution.context):
                return transition.to
        return step.next

    def goto(self, target: str, branch: str | None = None) -> None:
        step = self.definition.step(target)
        if step.type == StepType.JOIN:
            joins = self.execution.context.setdefault("_joins", {})
            joins[target] = joins.get(target, 0) + 1
            self.touch()  # the arrival count lives in the JSONB context
            expected = len(self.definition.parallel_for_join(target).branches)
            if joins[target] < expected:
                return
            joins[target] = 0
            branch = None
        self.schedule(target, branch)

    def route(self, step: StepDefinition, run: WorkflowStepRun) -> None:
        target = self.choose(step)
        if target is None:
            self.finish(
                ExecutionStatus.FAILED,
                error={"code": "no_route", "step": step.id, "message": "No transition matched."},
            )
            return
        self.goto(target, run.branch)

    # Run state changes

    def complete_run(
        self, run: WorkflowStepRun, output: dict[str, Any], actor_id: uuid.UUID | None = None
    ) -> None:
        if self.live:
            self.now = utc_now()
        run.status = RunStatus.COMPLETED.value
        run.output = output
        run.error = None
        run.actor_id = actor_id
        run.completed_at = self.now
        run.duration_ms = int(((self.now - (run.started_at or self.now)).total_seconds()) * 1000)
        self.execution.context[run.step_id] = output
        self.touch()
        self.event("step.completed", run, actor_id, {"step": run.step_id, "attempt": run.attempt})

    def fail_run(
        self, run: WorkflowStepRun, step: StepDefinition, error: dict, retryable: bool
    ) -> None:
        policy = step.retry or RetryPolicy()
        run.error = error
        if retryable and run.attempt < policy.max_attempts:
            delay = policy.backoff_seconds * 2 ** (run.attempt - 1)
            run.status = RunStatus.PENDING.value
            run.not_before = self.now + timedelta(seconds=delay)
            self.event(
                "step.retry_scheduled",
                run,
                data={"attempt": run.attempt, "retry_in_seconds": delay, "error": error},
            )
            return
        run.status = RunStatus.FAILED.value
        run.completed_at = self.now
        run.duration_ms = int(((self.now - (run.started_at or self.now)).total_seconds()) * 1000)
        self.event("step.failed", run, data={"attempt": run.attempt, "error": error})
        self.execution.context["_failure"] = {"step": step.id, **error}
        self.touch()
        if step.on_failure:
            self.goto(step.on_failure, run.branch)
        else:
            self.finish(ExecutionStatus.FAILED, error={"step": step.id, **error})

    def finish(
        self,
        status: ExecutionStatus,
        outcome: str | None = None,
        error: dict[str, Any] | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> None:
        self.db.flush()  # sessions do not autoflush; queries must see this run's changes
        for run in self.db.execute(
            select(WorkflowStepRun).where(
                WorkflowStepRun.execution_id == self.execution.id,
                WorkflowStepRun.status.in_([RunStatus.PENDING, RunStatus.WAITING]),
            )
        ).scalars():
            run.status = RunStatus.CANCELLED.value
            run.completed_at = self.now
        self.execution.status = status.value
        self.execution.outcome = outcome
        self.execution.error = error
        self.execution.completed_at = self.now
        self.touch()
        self.event(
            f"execution.{status.value}",
            actor_id=actor_id,
            data={"outcome": outcome, "error": error},
        )
        self._pending_audit.append(
            (
                f"workflow.{status.value}",
                {"outcome": outcome, "error": error, "workflow_id": self.execution.workflow_id},
            )
        )

    # Running steps

    def run_step(self, run: WorkflowStepRun) -> None:
        if self.live:
            self.now = utc_now()
        step = self.definition.step(run.step_id)
        run.attempt += 1
        run.started_at = run.started_at or self.now
        run.not_before = None
        self.event("step.started", run, data={"step": step.id, "attempt": run.attempt})

        if step.type in HANDLER_TYPES:
            self._run_handler(run, step)
        elif step.type == StepType.DECISION:
            target = self.choose(step)
            if target is None:
                self.complete_run(run, {"route": None})
                self.finish(
                    ExecutionStatus.FAILED,
                    error={
                        "code": "no_route",
                        "step": step.id,
                        "message": "No transition matched.",
                    },
                )
            else:
                self.complete_run(run, {"route": target})
                self.goto(target, run.branch)
        elif step.type in WAITING_TYPES:
            run.status = RunStatus.WAITING.value
            if step.timeout:
                run.due_at = self.now + timedelta(seconds=step.timeout.after_seconds)
            kind = "wait.started" if step.type == StepType.WAIT else "task.opened"
            self.event(
                kind, run, data={"step": step.id, "due_at": run.due_at and run.due_at.isoformat()}
            )
        elif step.type == StepType.PARALLEL:
            self.complete_run(run, {"branches": step.branches})
            for branch_start in step.branches:
                self.schedule(branch_start, branch=branch_start)
        elif step.type == StepType.JOIN:
            self.complete_run(run, {})
            self.route(step, run)
        elif step.type == StepType.COMPLETION:
            self.complete_run(run, {})
            self.finish(
                ExecutionStatus.COMPLETED,
                outcome=step.outcome or self.execution.context.get("outcome"),
            )
        elif step.type == StepType.FAILURE:
            self.complete_run(run, {})
            self.finish(
                ExecutionStatus.FAILED,
                outcome=step.outcome or "failed",
                error=self.execution.context.get("_failure") or {"step": step.id},
            )

    def _run_handler(self, run: WorkflowStepRun, step: StepDefinition) -> None:
        handler = registry.handler_for(step.type, step.handler or "")
        if handler is None:
            self.fail_run(run, step, {"code": "handler_missing", "message": step.handler}, False)
            return
        context = StepContext(self.db, self.execution, run, step, self.now)
        try:
            # The handler's writes and nothing else are undone if it raises.
            with self.db.begin_nested():
                output = handler(context) or {}
        except RetryableStepError as exc:
            self.fail_run(run, step, _error(exc.code, exc.message, exc.details), retryable=True)
        except StepError as exc:
            self.fail_run(run, step, _error(exc.code, exc.message, exc.details), retryable=False)
        except DomainError as exc:
            self.fail_run(run, step, _error(exc.code, exc.message, exc.details), retryable=False)
        except Exception as exc:  # noqa: BLE001 - unknown failures are retried, then recorded
            logger.warning("workflow step %s raised %r", step.id, exc)
            self.fail_run(
                run,
                step,
                _error("unexpected_error", f"{exc.__class__.__name__}: {exc}"),
                retryable=True,
            )
        else:
            self.complete_run(run, output)
            self.route(step, run)

    def advance(self, max_steps: int = MAX_STEPS_PER_ADVANCE) -> int:
        ran = 0
        while ran < max_steps and self.execution.status in ACTIVE_STATUSES:
            self.db.flush()  # the next query must see the previous step's state changes
            run = self.db.execute(
                select(WorkflowStepRun)
                .where(
                    WorkflowStepRun.execution_id == self.execution.id,
                    WorkflowStepRun.status == RunStatus.PENDING,
                    or_(
                        WorkflowStepRun.not_before.is_(None), WorkflowStepRun.not_before <= self.now
                    ),
                )
                .order_by(WorkflowStepRun.sequence)
                .limit(1)
            ).scalar_one_or_none()
            if run is None:
                break
            self.run_step(run)
            ran += 1
        self.settle()
        return ran

    def settle(self) -> None:
        """Recompute current steps and the running/waiting status; flush audit records."""
        self.sync_current_steps()
        if self.execution.status in ACTIVE_STATUSES:
            statuses = set(
                self.db.execute(
                    select(WorkflowStepRun.status).where(
                        WorkflowStepRun.execution_id == self.execution.id,
                        WorkflowStepRun.status.in_([RunStatus.PENDING, RunStatus.WAITING]),
                    )
                ).scalars()
            )
            if RunStatus.PENDING in statuses:
                self.execution.status = ExecutionStatus.RUNNING.value
            elif RunStatus.WAITING in statuses:
                self.execution.status = ExecutionStatus.WAITING.value
            else:
                self.finish(
                    ExecutionStatus.FAILED,
                    error={"code": "stalled", "message": "No active steps remain."},
                )
                self.sync_current_steps()
        for action, metadata in self._pending_audit:
            record_audit_event(
                self.db,
                actor_id=None,
                action=action,
                entity_type="workflow_execution",
                entity_id=self.execution.id,
                metadata=metadata,
            )
        self._pending_audit.clear()


def _error(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _lock(
    db: Session, execution_id: uuid.UUID, *, skip_locked: bool = False
) -> WorkflowExecution | None:
    query = select(WorkflowExecution).where(WorkflowExecution.id == execution_id)
    query = query.with_for_update(skip_locked=skip_locked)
    return db.execute(query).scalar_one_or_none()


def _driver(db: Session, execution: WorkflowExecution, now: datetime | None) -> _Driver:
    return _Driver(
        db=db,
        definition=_definition_for(execution),
        execution=execution,
        now=now or utc_now(),
        live=now is None,
    )


# --- Public API ------------------------------------------------------------------------------


def start(
    db: Session,
    *,
    workflow_id: str,
    payload: dict[str, Any],
    initiator: AuthenticatedUser,
    version: int | None = None,
    idempotency_key: str | None = None,
    now: datetime | None = None,
    max_steps: int = MAX_STEPS_PER_ADVANCE,
    simulation_run_id: uuid.UUID | None = None,
    settings: dict[str, Any] | None = None,
) -> tuple[WorkflowExecution, bool]:
    """Start an execution and run it until it waits, completes or fails.

    `settings` are execution options outside the business input (e.g. the AI mode and tool
    of an experiment); handlers read them as `_settings` in the context.

    Returns (execution, replayed). With an idempotency key, a repeated start by the same
    user returns the original execution instead of starting another.
    """
    live = now is None
    now = now or utc_now()
    definition = registry.get_definition(workflow_id, version)
    if definition is None:
        raise NotFoundError(f"Workflow {workflow_id} is not registered.")
    if idempotency_key:
        existing = db.execute(
            select(WorkflowExecution).where(
                WorkflowExecution.initiated_by == initiator.id,
                WorkflowExecution.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, True
    model: type[BaseModel] = registry.input_model(definition.workflow_id, definition.version)
    try:
        data = model.model_validate(payload)
    except ValidationError as exc:
        raise WorkflowInputError(
            "The workflow input is invalid.",
            [
                {"location": list(e["loc"]), "message": e["msg"], "type": e["type"]}
                for e in exc.errors()
            ],
        ) from exc

    record = definition_record(db, definition)
    execution = WorkflowExecution(
        workflow_id=definition.workflow_id,
        workflow_version=definition.version,
        definition_id=record.id,
        status=ExecutionStatus.RUNNING.value,
        current_steps=[],
        context={
            "input": data.model_dump(mode="json"),
            **({"_settings": settings} if settings else {}),
        },
        initiated_by=initiator.id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id_var.get(),
        started_at=now,
        updated_at=now,
        step_counter=0,
        simulation_run_id=simulation_run_id,
    )
    try:
        with db.begin_nested():
            db.add(execution)
            db.flush()
    except IntegrityError:
        # A concurrent start with the same key won.
        existing = db.execute(
            select(WorkflowExecution).where(
                WorkflowExecution.initiated_by == initiator.id,
                WorkflowExecution.idempotency_key == idempotency_key,
            )
        ).scalar_one()
        return existing, True

    driver = _Driver(db=db, definition=definition, execution=execution, now=now, live=live)
    driver.event(
        "execution.started",
        actor_id=initiator.id,
        data={"workflow": definition.workflow_id, "version": definition.version},
    )
    driver.schedule(definition.start)
    record_audit_event(
        db,
        actor_id=initiator.id,
        action="workflow.started",
        entity_type="workflow_execution",
        entity_id=execution.id,
        metadata={"workflow_id": definition.workflow_id, "version": definition.version},
    )
    driver.advance(max_steps)
    return execution, False


def advance(
    db: Session,
    execution_id: uuid.UUID,
    *,
    now: datetime | None = None,
    max_steps: int = MAX_STEPS_PER_ADVANCE,
) -> WorkflowExecution:
    """Run every due step of one execution (resumption after a restart uses this)."""
    execution = _lock(db, execution_id)
    if execution is None:
        raise NotFoundError("Workflow execution not found.")
    if execution.status in ACTIVE_STATUSES:
        _driver(db, execution, now).advance(max_steps)
    return execution


def complete_task(
    db: Session,
    run_id: uuid.UUID,
    actor: AuthenticatedUser,
    *,
    decision: str | None = None,
    data: dict[str, Any] | None = None,
    note: str | None = None,
    now: datetime | None = None,
) -> WorkflowExecution:
    """Complete a human task or approval, enforcing its permission and four-eyes policy."""
    found = db.get(WorkflowStepRun, run_id)
    if found is None:
        raise NotFoundError("Task not found.")
    execution = _lock(db, found.execution_id)
    assert execution is not None
    run = db.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.id == run_id).with_for_update()
    ).scalar_one()
    db.refresh(run)
    if run.status != RunStatus.WAITING:
        raise ConflictError(f"This task is {run.status}; it can no longer be completed.")
    driver = _driver(db, execution, now)
    step = driver.definition.step(run.step_id)
    if step.type not in (StepType.APPROVAL, StepType.HUMAN_TASK) or step.approval is None:
        raise ConflictError("This step is not a task; send a signal instead.")

    check_task_access(db, execution, step, actor)
    if step.type == StepType.APPROVAL:
        if decision not in ("approve", "reject"):
            raise WorkflowInputError("decision must be 'approve' or 'reject'.")
        output: dict[str, Any] = {
            "decision": decision,
            "approved": decision == "approve",
            "actor_id": str(actor.id),
            "note": note,
        }
    else:
        output = {**_validate_form(step, data or {}), "actor_id": str(actor.id), "note": note}

    driver.complete_run(run, output, actor.id)
    driver.event("task.completed", run, actor.id, {"step": step.id, "decision": decision})
    record_audit_event(
        db,
        actor_id=actor.id,
        action="workflow.task_completed",
        entity_type="workflow_execution",
        entity_id=execution.id,
        metadata={"step": step.id, "decision": decision, "note": note},
    )
    driver.route(step, run)
    driver.advance()
    return execution


def check_task_access(
    db: Session, execution: WorkflowExecution, step: StepDefinition, actor: AuthenticatedUser
) -> None:
    """Raise unless `actor` may complete this task (permissions and four-eyes)."""
    assert step.approval is not None
    missing = [p for p in step.approval.permissions if not actor.can(Permission(p))]
    if missing:
        raise PermissionDeniedError(
            "Your role cannot complete this task.", {"required_permissions": missing}
        )
    for reference in step.approval.distinct_from:
        if reference == "initiator":
            if actor.id == execution.initiated_by:
                raise PermissionDeniedError(
                    "Four-eyes rule: the person who started this case cannot decide it.",
                    {"rule": "four_eyes", "distinct_from": "initiator"},
                )
            continue
        db.flush()
        earlier = db.execute(
            select(WorkflowStepRun.actor_id).where(
                WorkflowStepRun.execution_id == execution.id,
                WorkflowStepRun.step_id == reference,
                WorkflowStepRun.status == RunStatus.COMPLETED,
            )
        ).scalars()
        if actor.id in set(earlier):
            raise PermissionDeniedError(
                f"Four-eyes rule: you already acted on '{reference}' in this case.",
                {"rule": "four_eyes", "distinct_from": reference},
            )


def _validate_form(step: StepDefinition, data: dict[str, Any]) -> dict[str, Any]:
    types = {"string": str, "integer": int, "boolean": bool}
    cleaned, errors = {}, []
    for f in step.form:
        if f.name not in data or data[f.name] is None:
            if f.required:
                errors.append({"field": f.name, "message": "required"})
            continue
        value = data[f.name]
        expected = types[f.type]
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            errors.append({"field": f.name, "message": f"must be {f.type}"})
            continue
        cleaned[f.name] = value
    if errors:
        raise WorkflowInputError("The task form is invalid.", errors)
    return cleaned


def signal(
    db: Session,
    execution_id: uuid.UUID,
    name: str,
    payload: dict[str, Any],
    actor_id: uuid.UUID | None,
    *,
    now: datetime | None = None,
) -> WorkflowExecution:
    """Deliver a named signal to a waiting wait-state."""
    execution = _lock(db, execution_id)
    if execution is None:
        raise NotFoundError("Workflow execution not found.")
    driver = _driver(db, execution, now)
    db.flush()
    waiting = db.execute(
        select(WorkflowStepRun).where(
            WorkflowStepRun.execution_id == execution.id,
            WorkflowStepRun.status == RunStatus.WAITING,
            WorkflowStepRun.step_type == StepType.WAIT,
        )
    ).scalars()
    run = next((r for r in waiting if driver.definition.step(r.step_id).signal == name), None)
    if run is None:
        raise ConflictError(f"The execution is not waiting for '{name}'.")
    step = driver.definition.step(run.step_id)
    driver.complete_run(run, {"signal": name, **payload}, actor_id)
    driver.event("signal.received", run, actor_id, {"signal": name})
    driver.route(step, run)
    driver.advance()
    return execution


def cancel(
    db: Session,
    execution_id: uuid.UUID,
    actor_id: uuid.UUID,
    reason: str,
    *,
    now: datetime | None = None,
) -> WorkflowExecution:
    execution = _lock(db, execution_id)
    if execution is None:
        raise NotFoundError("Workflow execution not found.")
    if execution.status not in ACTIVE_STATUSES:
        raise ConflictError(f"The execution is already {execution.status}.")
    driver = _driver(db, execution, now)
    driver.finish(
        ExecutionStatus.CANCELLED, outcome="cancelled", error={"reason": reason}, actor_id=actor_id
    )
    # The workflow closes what it opened (e.g. a pending payment), in the same transaction.
    cleanup = registry.cancel_handler(execution.workflow_id)
    if cleanup is not None:
        cleanup(db, execution, reason, driver.now)
    driver.settle()
    return execution


def process_timers(db: Session, execution: WorkflowExecution, now: datetime) -> int:
    """Apply timeout policies to overdue waits and tasks of one locked execution."""
    driver = _driver(db, execution, now)
    db.flush()
    overdue = list(
        db.execute(
            select(WorkflowStepRun)
            .where(
                WorkflowStepRun.execution_id == execution.id,
                WorkflowStepRun.status == RunStatus.WAITING,
                WorkflowStepRun.due_at <= now,
                WorkflowStepRun.escalated_at.is_(None),
            )
            .order_by(WorkflowStepRun.sequence)
        ).scalars()
    )
    for run in overdue:
        step = driver.definition.step(run.step_id)
        assert step.timeout is not None
        if step.timeout.action == "transition":
            run.status = RunStatus.CANCELLED.value
            run.completed_at = now
            run.output = {"timed_out": True}
            execution.context[run.step_id] = {"timed_out": True}
            driver.touch()
            driver.event("step.timed_out", run, data={"step": step.id, "to": step.timeout.to})
            driver.goto(step.timeout.to or "", run.branch)
        else:
            run.escalated_at = now
            driver.event("task.overdue", run, data={"step": step.id})
            record_audit_event(
                db,
                actor_id=None,
                action="workflow.task_overdue",
                entity_type="workflow_execution",
                entity_id=execution.id,
                metadata={
                    "step": step.id,
                    "due_at": run.due_at.isoformat() if run.due_at else None,
                },
            )
    if overdue:
        driver.advance()
    return len(overdue)


@dataclass
class RunReport:
    executions: int = 0
    steps: int = 0
    timers: int = 0
    skipped_locked: int = 0


def run_due(
    session_factory: sessionmaker[Session], *, now: datetime | None = None, limit: int = 1000
) -> RunReport:
    """Resume work: advance every execution with due steps or expired timers.

    Each execution is processed in its own transaction. Executions another worker holds
    are skipped (SKIP LOCKED) and picked up on a later pass.
    """
    cutoff = now or utc_now()  # which work is due; steps themselves use live time if now is None
    report = RunReport()
    with session_factory() as db:
        candidates = list(
            db.execute(
                select(WorkflowStepRun.execution_id)
                .join(WorkflowExecution, WorkflowExecution.id == WorkflowStepRun.execution_id)
                .where(
                    WorkflowExecution.status.in_(list(ACTIVE_STATUSES)),
                    # Simulated executions run on simulated time; only their run drives them.
                    WorkflowExecution.simulation_run_id.is_(None),
                    or_(
                        (WorkflowStepRun.status == RunStatus.PENDING)
                        & or_(
                            WorkflowStepRun.not_before.is_(None),
                            WorkflowStepRun.not_before <= cutoff,
                        ),
                        (WorkflowStepRun.status == RunStatus.WAITING)
                        & (WorkflowStepRun.due_at <= cutoff)
                        & WorkflowStepRun.escalated_at.is_(None),
                    ),
                )
                .distinct()
                .limit(limit)
            ).scalars()
        )
    for execution_id in candidates:
        with session_factory() as db, db.begin():
            execution = _lock(db, execution_id, skip_locked=True)
            if execution is None:
                report.skipped_locked += 1
                continue
            if execution.status not in ACTIVE_STATUSES:
                continue
            report.timers += process_timers(db, execution, cutoff)
            report.steps += _driver(db, execution, now).advance()
            report.executions += 1
    return report
