from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey


class JobWorker(UUIDPrimaryKey, Base):
    """A worker process, registered when it starts and updated while it runs."""

    __tablename__ = "job_workers"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    pid: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    succeeded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retried: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SlowQuery(Base):
    """A database statement that took longer than the configured threshold."""

    __tablename__ = "slow_queries"
    __table_args__ = (Index("ix_slow_queries_occurred_at", "occurred_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    # The statement with its parameters left out (they may carry synthetic personal data).
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    # Which process ran it: "api" or a worker's name.
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    # The API route (method and path template) or job kind it ran for, when known.
    context: Mapped[str | None] = mapped_column(String(200), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
