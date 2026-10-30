"""Importing, exporting and retiring stored workflow definitions (Phase 17).

A definition document is the JSON form of `WorkflowDefinition` (what `export` returns).
Importing validates it fully (validation.py); a valid new version is stored immutably,
re-importing an identical version is a no-op, and anything else is refused with every
problem listed. Retiring a version stops new executions; running ones finish on it.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.modules.workflows import store, validation
from app.modules.workflows.definition import WorkflowDefinition
from app.modules.workflows.models import (
    DefinitionSource,
    DefinitionStatus,
    WorkflowDefinitionRecord,
)


class DefinitionInvalid(BusinessRuleViolation):
    code = "definition_invalid"


def validate(db: Session, document: dict[str, Any]) -> validation.Report:
    return validation.validate(db, document)


def import_definition(
    db: Session, document: dict[str, Any], actor_id: uuid.UUID
) -> tuple[WorkflowDefinitionRecord, bool, validation.Report]:
    """Store a new version. Returns (record, created, report)."""
    report = validation.validate(db, document)
    if not report.valid:
        raise DefinitionInvalid(
            f"The definition has {len(report.errors)} problem(s); nothing was imported.",
            {"errors": report.errors, "warnings": report.warnings},
        )
    record, created = store_validated(db, report, actor_id)
    return record, created, report


def store_validated(
    db: Session, report: validation.Report, actor_id: uuid.UUID | None
) -> tuple[WorkflowDefinitionRecord, bool]:
    """Store a definition `validation.validate` passed (with the database). Returns
    (record, created); an identical, already stored version is returned unchanged."""
    assert report.valid and report.existing is not None
    definition = report.definition
    assert definition is not None
    if report.existing == "identical":
        record = store.stored_record(db, definition.workflow_id, definition.version)
        if record is None:  # identical to a code snapshot: cannot happen for a valid id
            raise ConflictError(f"{definition.workflow_id} v{definition.version} exists.")
        return record, False
    record = WorkflowDefinitionRecord(
        workflow_id=definition.workflow_id,
        version=definition.version,
        name=definition.name,
        definition=definition.canonical_json(),
        content_hash=definition.content_hash(),
        source=DefinitionSource.STORED,
        status=DefinitionStatus.ACTIVE,
        imported_by=actor_id,
    )
    try:
        with db.begin_nested():
            db.add(record)
            db.flush()
    except IntegrityError as exc:
        raise ConflictError(
            f"{definition.workflow_id} v{definition.version} was imported concurrently."
        ) from exc
    record_audit_event(
        db,
        actor_id=actor_id,
        action="workflow_definition.imported",
        entity_type="workflow_definition",
        entity_id=record.id,
        metadata={
            "workflow_id": record.workflow_id,
            "version": record.version,
            "content_hash": record.content_hash,
            "warnings": len(report.warnings),
            **(
                {"template_id": definition.origin.template_id}
                if definition.origin is not None
                else {}
            ),
        },
    )
    return record, True


def set_status(
    db: Session, workflow_id: str, version: int, status: DefinitionStatus, actor_id: uuid.UUID
) -> WorkflowDefinitionRecord:
    record = store.stored_record(db, workflow_id, version)
    if record is None:
        if store.is_code(workflow_id):
            raise ConflictError(f"{workflow_id} is registered in code; retire it in code.")
        raise NotFoundError(f"No stored definition {workflow_id} v{version}.")
    if record.status == status:
        return record
    record.status = status
    record.status_changed_at = datetime.now(UTC)
    record.status_changed_by = actor_id
    verb = "retired" if status == DefinitionStatus.RETIRED else "reactivated"
    record_audit_event(
        db,
        actor_id=actor_id,
        action=f"workflow_definition.{verb}",
        entity_type="workflow_definition",
        entity_id=record.id,
        metadata={"workflow_id": workflow_id, "version": version},
    )
    return record


def export(db: Session, workflow_id: str, version: int | None = None) -> dict[str, Any]:
    """The definition as an importable document (code definitions included)."""
    definition: WorkflowDefinition | None = store.resolve(db, workflow_id, version)
    if definition is None:
        raise NotFoundError(f"Workflow {workflow_id} is not registered.")
    return definition.canonical_json()
