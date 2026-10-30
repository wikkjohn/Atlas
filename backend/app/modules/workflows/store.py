"""Where a workflow definition comes from: code or the database.

Code definitions are registered when their module is imported (registry.py). Stored
definitions are imported as data (authoring.py) and live in `workflow_definitions`; any
process loads them on demand, so a worker runs a newly imported workflow without a
restart. A stored version never changes once imported (only its active/retired status
does), so each process keeps the parsed definition and its input validator in memory.
"""

import uuid
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.modules.workflows import registry
from app.modules.workflows.definition import WorkflowDefinition
from app.modules.workflows.models import (
    DefinitionSource,
    DefinitionStatus,
    WorkflowDefinitionRecord,
    WorkflowExecution,
)

_PARSED: dict[uuid.UUID, WorkflowDefinition] = {}
_VALIDATORS: dict[uuid.UUID, Draft202012Validator] = {}


def is_code(workflow_id: str) -> bool:
    return registry.get_definition(workflow_id) is not None


def parsed(record: WorkflowDefinitionRecord) -> WorkflowDefinition:
    found = _PARSED.get(record.id)
    if found is None:
        found = WorkflowDefinition.model_validate(record.definition)
        _PARSED[record.id] = found
    return found


def input_validator(record: WorkflowDefinitionRecord) -> Draft202012Validator:
    found = _VALIDATORS.get(record.id)
    if found is None:
        found = Draft202012Validator(parsed(record).input_schema, format_checker=FormatChecker())
        _VALIDATORS[record.id] = found
    return found


def stored_records(db: Session, workflow_id: str | None = None) -> list[WorkflowDefinitionRecord]:
    query = select(WorkflowDefinitionRecord).where(
        WorkflowDefinitionRecord.source == DefinitionSource.STORED
    )
    if workflow_id is not None:
        query = query.where(WorkflowDefinitionRecord.workflow_id == workflow_id)
    return list(
        db.execute(
            query.order_by(WorkflowDefinitionRecord.workflow_id, WorkflowDefinitionRecord.version)
        ).scalars()
    )


def stored_record(
    db: Session, workflow_id: str, version: int | None = None
) -> WorkflowDefinitionRecord | None:
    """A stored version, or (without a version) the latest active one."""
    query = select(WorkflowDefinitionRecord).where(
        WorkflowDefinitionRecord.source == DefinitionSource.STORED,
        WorkflowDefinitionRecord.workflow_id == workflow_id,
    )
    if version is not None:
        query = query.where(WorkflowDefinitionRecord.version == version)
    else:
        query = query.where(WorkflowDefinitionRecord.status == DefinitionStatus.ACTIVE)
    query = query.order_by(WorkflowDefinitionRecord.version.desc()).limit(1)
    return db.execute(query).scalar_one_or_none()


def resolve(db: Session, workflow_id: str, version: int | None = None) -> WorkflowDefinition | None:
    """A definition to read: code first, then stored (any status when a version is given)."""
    if is_code(workflow_id):
        return registry.get_definition(workflow_id, version)
    record = stored_record(db, workflow_id, version)
    if record is None and version is None:
        # Every version retired: still readable, as the latest one.
        records = stored_records(db, workflow_id)
        record = records[-1] if records else None
    return parsed(record) if record is not None else None


def for_start(
    db: Session, workflow_id: str, version: int | None
) -> tuple[WorkflowDefinition, WorkflowDefinitionRecord | None]:
    """The definition a new execution runs on, with its stored record (None for code)."""
    if is_code(workflow_id):
        definition = registry.get_definition(workflow_id, version)
        if definition is None:
            raise NotFoundError(f"Workflow {workflow_id} v{version} is not registered.")
        return definition, None
    record = stored_record(db, workflow_id, version)
    if record is None:
        if stored_records(db, workflow_id):
            raise ConflictError(
                f"Every version of {workflow_id} is retired; reactivate one to start cases."
                if version is None
                else f"{workflow_id} v{version} does not exist."
            )
        raise NotFoundError(f"Workflow {workflow_id} is not registered.")
    if record.status != DefinitionStatus.ACTIVE:
        raise ConflictError(
            f"{workflow_id} v{record.version} is retired; it accepts no new executions."
        )
    return parsed(record), record


def for_execution(db: Session, execution: WorkflowExecution) -> WorkflowDefinition | None:
    """The exact definition an execution was started on (whatever its status now)."""
    found = registry.get_definition(execution.workflow_id, execution.workflow_version)
    if found is not None:
        return found
    if execution.definition_id in _PARSED:
        return _PARSED[execution.definition_id]
    record = db.get(WorkflowDefinitionRecord, execution.definition_id)
    if record is None or record.source != DefinitionSource.STORED:
        return None
    return parsed(record)


def present(db: Session, execution: WorkflowExecution, context: dict[str, Any] | None = None):
    """Subject, risk and flags of a case, from its workflow's presentation."""
    context = execution.context if context is None else context
    if registry.presenter(execution.workflow_id) is not None:
        return registry.present(execution.workflow_id, context)
    definition = None if is_code(execution.workflow_id) else for_execution(db, execution)
    if definition is not None and definition.presentation is not None:
        return definition.presentation.present(context)
    return {"subject": None, "risk_rating": None, "flags": []}


def workflow_ids(db: Session) -> set[str]:
    """Every workflow that can be started: code ones and stored ones with an active version."""
    stored = db.execute(
        select(WorkflowDefinitionRecord.workflow_id)
        .where(
            WorkflowDefinitionRecord.source == DefinitionSource.STORED,
            WorkflowDefinitionRecord.status == DefinitionStatus.ACTIVE,
        )
        .distinct()
    ).scalars()
    return {d.workflow_id for d in registry.all_definitions()} | set(stored)


def forget() -> None:
    """Drop the in-memory copies (tests roll stored definitions back between cases)."""
    _PARSED.clear()
    _VALIDATORS.clear()
