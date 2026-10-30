"""Durable background jobs and their schedules.

The queue lives in PostgreSQL: a job can be queued in the same transaction as the change
that needs it (both commit or neither does), workers claim jobs with `FOR UPDATE SKIP
LOCKED` (so any number of worker processes share the queue without handing one job to
two of them), and every job's history stays queryable next to the data it touched.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey


class JobStatus(StrEnum):
    QUEUED = "queued"  # waiting for run_at and a free worker
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"  # out of attempts, or a failure that must not be retried
    CANCELLED = "cancelled"


ACTIVE_JOB_STATUSES = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)


class Job(UUIDPrimaryKey, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="status_valid",
        ),
        CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="attempts_valid"),
        CheckConstraint("(status = 'running') = (locked_by IS NOT NULL)", name="running_is_locked"),
        # The claim query: the next due job.
        Index("ix_jobs_due", "status", "run_at", "priority"),
        # At most one queued or running job per dedupe key (e.g. one scheduled run).
        Index(
            "uq_jobs_active_dedupe_key",
            "dedupe_key",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running') AND dedupe_key IS NOT NULL"),
        ),
    )

    job_number: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), nullable=False, unique=True
    )
    kind: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)  # lower first
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    schedule_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobSchedule(UUIDPrimaryKey, Base):
    """A job queued every `interval_seconds` while enabled; with a `business_calendar` (a
    country code, Phase 26) only on that country's business days, in its local time."""

    __tablename__ = "job_schedules"
    __table_args__ = (CheckConstraint("interval_seconds >= 60", name="interval_valid"),)

    name: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    business_calendar: Mapped[str | None] = mapped_column(String(2), nullable=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
