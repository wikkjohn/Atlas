import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
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


class ExperimentPortfolio(UUIDPrimaryKey, Base):
    """A tool family evaluated across workflows, departments and countries (Phase 78): one
    repeated-seed series per cell (a scenario the family serves, in one country), and
    statistics across the cells."""

    __tablename__ = "experiment_portfolios"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="status_valid"),
    )

    portfolio_number: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), nullable=False, unique=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    family: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    candidate_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    countries: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    seeds: Mapped[list[int]] = mapped_column(JSONB, nullable=False)
    applications: Mapped[int] = mapped_column(nullable=False)
    employees: Mapped[int] = mapped_column(nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Derived: recomputable from the cells' series statistics.
    statistics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExperimentSeries(UUIDPrimaryKey, Base):
    """The same experiment repeated over several seeds (Phase 77): one baseline and one
    candidate run per seed, each evaluated as an experiment, and statistics across them."""

    __tablename__ = "experiment_series"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="status_valid"),
        CheckConstraint("confidence > 0.5 AND confidence < 1", name="confidence_valid"),
    )

    series_number: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), nullable=False, unique=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    scenario_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario_version: Mapped[int] = mapped_column(nullable=False)
    candidate_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    tool_record_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_tools.id", ondelete="RESTRICT"), nullable=True
    )
    tool_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tool_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    seeds: Mapped[list[int]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Derived: recomputable from the replicates' stored evaluations.
    statistics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # One country, or None for every active one (Phase 78).
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    # A cell of a portfolio (Phase 78), or None for a series on its own.
    portfolio_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("experiment_portfolios.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )


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
    # One replicate of a series (Phase 77), or None for a single experiment.
    series_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("experiment_series.id", ondelete="RESTRICT"), nullable=True, index=True
    )


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
