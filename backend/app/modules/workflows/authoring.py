"""Importing, exporting and retiring stored workflow definitions (Phase 17).

A definition document is the JSON form of `WorkflowDefinition` (what `export` returns).
Importing validates it fully (validation.py); a valid new version is stored immutably,
re-importing an identical version is a no-op, and anything else is refused with every
problem listed. Retiring a version stops new executions; running ones finish on it.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import (
    BusinessRuleViolation,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.modules.workflows import store, validation
from app.modules.workflows.definition import Catalogue, WorkflowDefinition
from app.modules.workflows.models import (
    DefinitionSource,
    DefinitionStatus,
    WorkflowCatalogueEntry,
    WorkflowDefinitionRecord,
)


class DefinitionInvalid(BusinessRuleViolation):
    code = "definition_invalid"


def validate(db: Session, document: dict[str, Any]) -> validation.Report:
    return validation.validate(db, document)


def import_definition(
    db: Session,
    document: dict[str, Any],
    actor_id: uuid.UUID,
    *,
    status: DefinitionStatus = DefinitionStatus.ACTIVE,
) -> tuple[WorkflowDefinitionRecord, bool, validation.Report]:
    """Store a new version. Returns (record, created, report).

    The API imports drafts that go through review (Phase 22); the seed, the template
    generator and `workflows import --publish` publish directly as `active`."""
    report = validation.validate(db, document)
    if not report.valid:
        raise DefinitionInvalid(
            f"The definition has {len(report.errors)} problem(s); nothing was imported.",
            {"errors": report.errors, "warnings": report.warnings},
        )
    record, created = store_validated(db, report, actor_id, status=status)
    return record, created, report


def store_validated(
    db: Session,
    report: validation.Report,
    actor_id: uuid.UUID | None,
    *,
    status: DefinitionStatus = DefinitionStatus.ACTIVE,
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
        status=status,
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
    if definition.catalogue is not None:
        classify(db, definition.workflow_id, definition.catalogue, actor_id)
    return record, True


def classify(
    db: Session,
    workflow_id: str,
    catalogue: Catalogue,
    actor_id: uuid.UUID | None,
    owner_id: uuid.UUID | None | object = ...,
) -> WorkflowCatalogueEntry:
    """Set a workflow's classification (and, when given, its owner)."""
    entry = db.execute(
        select(WorkflowCatalogueEntry).where(WorkflowCatalogueEntry.workflow_id == workflow_id)
    ).scalar_one_or_none()
    if entry is None:
        entry = WorkflowCatalogueEntry(workflow_id=workflow_id)
        db.add(entry)
    entry.department = catalogue.department
    entry.countries = sorted(set(catalogue.countries))
    entry.products = sorted(set(catalogue.products))
    entry.tags = sorted(set(catalogue.tags))
    if owner_id is not ...:
        entry.owner_id = owner_id  # type: ignore[assignment]
    entry.updated_at = datetime.now(UTC)
    entry.updated_by = actor_id
    db.flush()
    return entry


# --- Lifecycle (Phase 22) --------------------------------------------------------------------


def _version(db: Session, workflow_id: str, version: int) -> WorkflowDefinitionRecord:
    record = store.stored_record(db, workflow_id, version)
    if record is None:
        if store.is_code(workflow_id):
            raise ConflictError(f"{workflow_id} is registered in code; it changes in code.")
        raise NotFoundError(f"No stored definition {workflow_id} v{version}.")
    return record


def _move(
    db: Session,
    record: WorkflowDefinitionRecord,
    allowed_from: tuple[DefinitionStatus, ...],
    to: DefinitionStatus,
    actor_id: uuid.UUID,
    action: str,
    note: str | None = None,
) -> WorkflowDefinitionRecord:
    if record.status not in allowed_from:
        raise ConflictError(
            f"{record.workflow_id} v{record.version} is {record.status}; it cannot be {action}."
        )
    now = datetime.now(UTC)
    record.status = to
    record.status_changed_at, record.status_changed_by = now, actor_id
    record_audit_event(
        db,
        actor_id=actor_id,
        action=f"workflow_definition.{action}",
        entity_type="workflow_definition",
        entity_id=record.id,
        metadata={"workflow_id": record.workflow_id, "version": record.version, "note": note},
    )
    return record


def submit(db: Session, workflow_id: str, version: int, actor_id: uuid.UUID):
    record = _move(
        db,
        _version(db, workflow_id, version),
        (DefinitionStatus.DRAFT,),
        DefinitionStatus.IN_REVIEW,
        actor_id,
        "submitted",
    )
    record.submitted_by, record.submitted_at = actor_id, record.status_changed_at
    record.reviewed_by = record.reviewed_at = record.review_note = None
    return record


def approve(
    db: Session, workflow_id: str, version: int, actor_id: uuid.UUID, note: str | None = None
) -> WorkflowDefinitionRecord:
    """Four-eyes: neither the importer nor the submitter approves; and the version's latest
    generated test run must have passed."""
    record = _version(db, workflow_id, version)
    if actor_id in (record.imported_by, record.submitted_by):
        raise PermissionDeniedError(
            "Four-eyes rule: the person who imported or submitted this version cannot approve it.",
            {"rule": "four_eyes"},
        )
    from app.modules.workflows.models import WorkflowTestRun

    latest = db.execute(
        select(WorkflowTestRun)
        .where(WorkflowTestRun.definition_id == record.id)
        .order_by(WorkflowTestRun.ran_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest is None or latest.failed:
        raise ConflictError(
            "Run the generated tests on this version first; approval needs a passing run."
            if latest is None
            else f"The latest generated test run failed {latest.failed} case(s); fix and re-test.",
            {"rule": "tests_must_pass"},
        )
    _move(
        db,
        record,
        (DefinitionStatus.IN_REVIEW,),
        DefinitionStatus.ACTIVE,
        actor_id,
        "approved",
        note,
    )
    record.reviewed_by, record.reviewed_at, record.review_note = (
        actor_id,
        record.status_changed_at,
        note,
    )
    return record


def reject(
    db: Session, workflow_id: str, version: int, actor_id: uuid.UUID, note: str
) -> WorkflowDefinitionRecord:
    record = _move(
        db,
        _version(db, workflow_id, version),
        (DefinitionStatus.IN_REVIEW,),
        DefinitionStatus.DRAFT,
        actor_id,
        "returned",
        note,
    )
    record.reviewed_by, record.reviewed_at, record.review_note = (
        actor_id,
        record.status_changed_at,
        note,
    )
    return record


def set_status(
    db: Session, workflow_id: str, version: int, status: DefinitionStatus, actor_id: uuid.UUID
) -> WorkflowDefinitionRecord:
    """Retire an active version, or reactivate a retired one."""
    record = _version(db, workflow_id, version)
    if record.status == status:
        return record
    if status == DefinitionStatus.RETIRED:
        return _move(db, record, (DefinitionStatus.ACTIVE,), status, actor_id, "retired")
    return _move(db, record, (DefinitionStatus.RETIRED,), status, actor_id, "reactivated")


def export(db: Session, workflow_id: str, version: int | None = None) -> dict[str, Any]:
    """The definition as an importable document (code definitions included)."""
    definition: WorkflowDefinition | None = store.resolve(db, workflow_id, version)
    if definition is None:
        raise NotFoundError(f"Workflow {workflow_id} is not registered.")
    return definition.canonical_json()
