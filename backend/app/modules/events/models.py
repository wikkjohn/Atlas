"""The outbox (Phase 74): events published by one department and their delivery to each
department that subscribes, recorded in the publisher's own transaction."""

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


class DeliveryStatus(StrEnum):
    PENDING = "pending"  # not yet attempted
    DELIVERED = "delivered"
    FAILED = "failed"  # attempted and failed; retried at next_attempt_at
    DEAD = "dead"  # out of attempts; waits for someone to retry it


class DomainEvent(UUIDPrimaryKey, Base):
    """Something that happened in one department, for the others: append-only."""

    __tablename__ = "domain_events"
    __table_args__ = (Index("ix_domain_events_topic_key", "topic", "key", "seq"),)

    seq: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    topic: Mapped[str] = mapped_column(String(80), nullable=False)  # e.g. hr.employee_hired
    key: Mapped[str] = mapped_column(String(120), nullable=False)  # what it is about
    publisher: Mapped[str] = mapped_column(String(40), nullable=False)  # the department
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EventDelivery(UUIDPrimaryKey, Base):
    """One event to one subscriber: delivered once, retried with back-off until it is."""

    __tablename__ = "event_deliveries"
    __table_args__ = (
        UniqueConstraint("event_id", "subscriber", name="uq_event_deliveries_event_subscriber"),
        CheckConstraint(
            "status IN ('pending', 'delivered', 'failed', 'dead')", name="status_valid"
        ),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        # The dispatcher looks for due deliveries; delivered ones are most rows.
        Index(
            "ix_event_deliveries_due",
            "next_attempt_at",
            postgresql_where=text("status IN ('pending', 'failed')"),
        ),
        Index("ix_event_deliveries_subscriber_status", "subscriber", "status"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("domain_events.id", ondelete="CASCADE"), nullable=False
    )
    subscriber: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
