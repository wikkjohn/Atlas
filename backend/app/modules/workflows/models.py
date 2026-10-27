import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
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


class RunStatus(StrEnum):
    PENDING = "pending"  # ready (or scheduled for retry at not_before)
    WAITING = "waiting"  # human task, approval or wait state in progress
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowDefinitionRecord(UUIDPrimaryKey, Base):
    """Immutable snapshot of each definition version that has been used."""

    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="uq_workflow_definitions_id_version"),
    )

    workflow_id: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkflowExecution(UUIDPrimaryKey, Base):
    __tablename__ = "workflow_executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'waiting', 'completed', 'failed', 'cancelled')",
            name="status_valid",
        ),
        UniqueConstraint(
            "initiated_by", "idempotency_key", name="uq_workflow_executions_idempotency"
        ),
        Index("ix_workflow_executions_workflow_status", "workflow_id", "status"),
    )

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


class WorkflowStepRun(UUIDPrimaryKey, Base):
    """One visit of a step. Retries reuse the row (attempt++); revisits get a new row."""

    __tablename__ = "workflow_step_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'waiting', 'completed', 'failed', 'cancelled')",
            name="status_valid",
        ),
        UniqueConstraint("execution_id", "sequence", name="uq_workflow_step_runs_sequence"),
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
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflow_executions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
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
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowEvent(UUIDPrimaryKey, Base):
    """Append-only execution history (a database trigger forbids changes)."""

    __tablename__ = "workflow_events"

    # Database-assigned order: events sharing a timestamp still have a stable order.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False, unique=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflow_executions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    step_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("workflow_step_runs.id", ondelete="RESTRICT"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
