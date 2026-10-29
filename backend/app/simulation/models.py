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
    text,
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


class HistoryState(StrEnum):
    """Where a run's case-level workflow history is (Phase 15)."""

    PRESENT = "present"  # in the simulation partitions
    ARCHIVED = "archived"  # moved to an archive file; can be restored
    PURGED = "purged"  # removed by a reset without an archive


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
    # Phase 6: experiment mode (baseline, ai_assisted, ai_automated), the AI tool used and
    # the suite the run was started in (runs of one suite share seed and workload).
    mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="baseline", server_default="baseline"
    )
    tool_record_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_tools.id", ondelete="RESTRICT"), nullable=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    history_state: Mapped[str] = mapped_column(
        String(10), nullable=False, default=HistoryState.PRESENT, server_default="present"
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
    # No foreign key: the execution's history can be archived (Phase 15) while this
    # measured result stays; restoring the archive brings the execution back.
    execution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
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
    ai_recommendation: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    automated: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")


class SimulationArchive(UUIDPrimaryKey, Base):
    """One archive (or purge) of a run's workflow history, with what it contained.

    The run's results and per-case outcomes stay in place; the executions, step runs,
    events and AI tool calls move to compressed COPY files under the archive directory.
    """

    __tablename__ = "simulation_archives"
    __table_args__ = (
        CheckConstraint("kind IN ('archive', 'purge')", name="kind_valid"),
        CheckConstraint("(kind = 'archive') = (location IS NOT NULL)", name="location_valid"),
        # At most one archive per run is in effect (not yet restored).
        Index(
            "uq_simulation_archives_active_run",
            "run_id",
            unique=True,
            postgresql_where=text("restored_at IS NULL"),
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("simulation_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    # Directory of the archive files, relative to the configured archive root.
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Per table: rows, bytes, sha256 of the file and the columns it holds.
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Counts the analytics still need once the history is gone (failed executions, ...).
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rows: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    restored_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
