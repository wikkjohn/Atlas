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
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey


class SimulationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SimulationRun(UUIDPrimaryKey, Base):
    """One simulation run: everything needed to reproduce it, its progress and results."""

    __tablename__ = "simulation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')", name="status_valid"
        ),
        Index("ix_simulation_runs_reproduction", "scenario_id", "seed", "config_hash"),
    )

    run_number: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), nullable=False, unique=True
    )
    scenario_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario_version: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_id: Mapped[str] = mapped_column(String(20), nullable=False)
    workflow_version: Mapped[int] = mapped_column(Integer, nullable=False)
    profile: Mapped[str] = mapped_column(String(30), nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # The fully resolved configuration (scenario config, sizes, dataset fingerprint).
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    software_version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Live counters while running: cases started/finished, events processed, simulated time.
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    results: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    result_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    simulated_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    simulated_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    wall_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    staff_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True
    )


class SimulationCaseResult(UUIDPrimaryKey, Base):
    """The measured result of one simulated case, next to its ground truth."""

    __tablename__ = "simulation_case_results"
    __table_args__ = (
        UniqueConstraint("run_id", "case_index", name="uq_simulation_case_results_case"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_index: Mapped[int] = mapped_column(Integer, nullable=False)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("workflow_executions.id", ondelete="RESTRICT"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    expected_outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(50), nullable=True)
    risk_rating: Mapped[str | None] = mapped_column(String(20), nullable=True)
    flags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    manual_reviews: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queue_wait_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overdue_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    arrived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cycle_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    path: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
