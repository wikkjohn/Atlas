import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
    and_,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey


class ExecutionStatus(StrEnum):
    RUNNING = "running"  # has steps ready to run
    WAITING = "waiting"  # blocked on people, signals or timers
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = (ExecutionStatus.RUNNING, ExecutionStatus.WAITING)


class Realm(StrEnum):
    """Which partition a workflow's history lives in (migration 0013).

    Executions, step runs and events are LIST-partitioned on `realm`: the live bank's
    history and the simulation engine's history are separate tables underneath, so
    simulation history can be archived or reset without touching the live bank's.
    """

    LIVE = "live"
    SIMULATION = "simulation"


# The partitions behind each partitioned table (created by migration 0013).
PARTITIONED_TABLES = ("workflow_executions", "workflow_step_runs", "workflow_events")


def partition_name(table: str, realm: Realm | str) -> str:
    return f"{table}_{Realm(realm).value}"


# Database rows are keyed by (id, realm), as PostgreSQL requires the partition key in
# every unique constraint; the ORM still identifies a row by its id alone.
_ID_ONLY = {"primary_key": ["id"]}


class RunStatus(StrEnum):
    PENDING = "pending"  # ready (or scheduled for retry at not_before)
    WAITING = "waiting"  # human task, approval or wait state in progress
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DefinitionSource(StrEnum):
    CODE = "code"  # registered by a Python module; snapshotted here on first use
    STORED = "stored"  # imported as data through the definitions API (Phase 17)


class DefinitionStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"  # no new executions; running ones finish on this version


class WorkflowDefinitionRecord(UUIDPrimaryKey, Base):
    """Immutable snapshot of each definition version: code definitions are recorded on
    first use, stored definitions when they are imported. Only `status` ever changes."""

    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="uq_workflow_definitions_id_version"),
        CheckConstraint("source IN ('code', 'stored')", name="source_valid"),
        CheckConstraint("status IN ('active', 'retired')", name="status_valid"),
        CheckConstraint(
            "source = 'stored' OR (status = 'active' AND imported_by IS NULL)",
            name="code_definitions_are_plain",
        ),
        Index(
            "ix_workflow_definitions_stored",
            "workflow_id",
            "version",
            postgresql_where=text("source = 'stored'"),
        ),
    )

    workflow_id: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source: Mapped[str] = mapped_column(
        String(10), nullable=False, default=DefinitionSource.CODE, server_default="code"
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default=DefinitionStatus.ACTIVE, server_default="active"
    )
    imported_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_changed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'waiting', 'completed', 'failed', 'cancelled')",
            name="status_valid",
        ),
        CheckConstraint(
            "(realm = 'simulation') = (simulation_run_id IS NOT NULL)", name="realm_matches_run"
        ),
        PrimaryKeyConstraint("id", "realm"),
        UniqueConstraint(
            "initiated_by", "idempotency_key", "realm", name="uq_workflow_executions_idempotency"
        ),
        Index("ix_workflow_executions_workflow_status", "workflow_id", "status"),
        {"postgresql_partition_by": "LIST (realm)"},
    )
    __mapper_args__ = _ID_ONLY

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    realm: Mapped[str] = mapped_column(String(10), nullable=False)

    workflow_id: Mapped[str] = mapped_column(String(20), nullable=False)
    workflow_version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflow_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    outcome: Mapped[str | None] = mapped_column(String(50), nullable=True)
    current_steps: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    business_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    initiated_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    step_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Set for executions driven by the simulation engine (on simulated time); they are kept
    # out of the live task inbox, the timer sweep and default listings.
    simulation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("simulation_runs.id", ondelete="RESTRICT"), nullable=True, index=True
    )


class WorkflowStepRun(Base):
    """One visit of a step. Retries reuse the row (attempt++); revisits get a new row."""

    __tablename__ = "workflow_step_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'waiting', 'completed', 'failed', 'cancelled')",
            name="status_valid",
        ),
        PrimaryKeyConstraint("id", "realm"),
        UniqueConstraint(
            "execution_id", "sequence", "realm", name="uq_workflow_step_runs_sequence"
        ),
        ForeignKeyConstraint(
            ["execution_id", "realm"],
            ["workflow_executions.id", "workflow_executions.realm"],
            ondelete="RESTRICT",
        ),
        # The runner and the timer sweep look these up.
        Index(
            "ix_workflow_step_runs_due",
            "status",
            "not_before",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_workflow_step_runs_waiting_due",
            "due_at",
            postgresql_where=text("status = 'waiting'"),
        ),
        {"postgresql_partition_by": "LIST (realm)"},
    )
    __mapper_args__ = _ID_ONLY

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    realm: Mapped[str] = mapped_column(String(10), nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    step_id: Mapped[str] = mapped_column(String(64), nullable=False)
    step_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    branch: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    required_permissions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # BIGINT: a wait state (e.g. a collections case) can last months.
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# Joins a step run to its execution on the full key, so PostgreSQL can prune partitions on
# both sides when either is filtered by realm.
STEP_RUN_EXECUTION = and_(
    WorkflowExecution.id == WorkflowStepRun.execution_id,
    WorkflowExecution.realm == WorkflowStepRun.realm,
)


class WorkflowEvent(Base):
    """Append-only execution history (a database trigger forbids changes)."""

    __tablename__ = "workflow_events"
    __table_args__ = (
        PrimaryKeyConstraint("id", "realm"),
        UniqueConstraint("seq", "realm", name="uq_workflow_events_seq"),
        # Document timeouts are counted per simulation run (analytics, experiments); they
        # are rare among millions of events, so a small partial index finds them.
        Index(
            "ix_workflow_events_timeouts",
            "execution_id",
            postgresql_where=text("event_type = 'step.timed_out'"),
        ),
        ForeignKeyConstraint(
            ["execution_id", "realm"],
            ["workflow_executions.id", "workflow_executions.realm"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["step_run_id", "realm"],
            ["workflow_step_runs.id", "workflow_step_runs.realm"],
            ondelete="RESTRICT",
        ),
        {"postgresql_partition_by": "LIST (realm)"},
    )
    __mapper_args__ = _ID_ONLY

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    realm: Mapped[str] = mapped_column(String(10), nullable=False)
    # Database-assigned order: events sharing a timestamp still have a stable order.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    # Indexed so removing step runs (archiving simulation history) need not scan events.
    step_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
