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


class ExperimentStatus(StrEnum):
    RUNNING = "running"  # its simulation runs are executing
    COMPLETED = "completed"  # evaluated
    FAILED = "failed"  # a run failed or the evaluation could not be made


class Verdict(StrEnum):
    SUCCESSFUL = "successful"
    NOT_SUCCESSFUL = "not_successful"


class Experiment(UUIDPrimaryKey, Base):
    """A comparison of one baseline run and one candidate run of the same workload."""

    __tablename__ = "experiments"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="status_valid"),
        CheckConstraint("baseline_run_id <> candidate_run_id", name="distinct_runs"),
    )

    experiment_number: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), nullable=False, unique=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    scenario_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario_version: Mapped[int] = mapped_column(nullable=False)
    baseline_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("simulation_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    candidate_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("simulation_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    candidate_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    tool_record_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_tools.id", ondelete="RESTRICT"), nullable=True
    )
    tool_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tool_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Cost assumptions and success thresholds, fully resolved (defaults filled in).
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExperimentMeasurement(UUIDPrimaryKey, Base):
    """RAW measurements of one run, read from what the run recorded. Never derived from
    assumptions; the evaluation reads only these."""

    __tablename__ = "experiment_measurements"
    __table_args__ = (
        UniqueConstraint("experiment_id", "role", name="uq_experiment_measurements_role"),
        CheckConstraint("role IN ('baseline', 'candidate')", name="role_valid"),
    )

    experiment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("simulation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    measurement_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExperimentEvaluation(UUIDPrimaryKey, Base):
    """DERIVED results: costs, metric comparisons, criteria, verdict — recomputable from
    the raw measurements and the experiment's configuration."""

    __tablename__ = "experiment_evaluations"

    experiment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    evaluation_version: Mapped[str] = mapped_column(String(20), nullable=False)
    costs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    comparisons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    conclusion: Mapped[str] = mapped_column(Text, nullable=False)
    limitations: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    evaluation_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
