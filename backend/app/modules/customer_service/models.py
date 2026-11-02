"""Customer service (Phase 51, roadmap Milestone D step 23): contact-centre cases, complaints
and SLA timers.

A case records a customer's enquiry, request or complaint from any channel, with a first
response and a resolution due by its priority. Waiting on the customer pauses the clock. A
sweep marks overdue cases breached and escalates them. A complaint is acknowledged, given a
final response within eight weeks, and may carry redress paid into the customer's account by
someone other than whoever proposed it.
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
    Index,
    Integer,
    Sequence,
    String,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey

CASE_SEQUENCE = Sequence("service_case_number_seq", start=1)


class CaseCategory(StrEnum):
    ENQUIRY = "enquiry"
    REQUEST = "request"
    COMPLAINT = "complaint"


class CasePriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class CaseStatus(StrEnum):
    OPEN = "open"
    AWAITING_CUSTOMER = "awaiting_customer"  # the SLA clock is paused
    RESOLVED = "resolved"


class ComplaintOutcome(StrEnum):
    UPHELD = "upheld"
    PARTLY_UPHELD = "partly_upheld"
    NOT_UPHELD = "not_upheld"


class RedressStatus(StrEnum):
    PROPOSED = "proposed"
    PAID = "paid"
    WITHDRAWN = "withdrawn"


class ServiceCase(UUIDPrimaryKey, Base):
    """One customer contact: an enquiry, a request or a complaint."""

    __tablename__ = "service_cases"
    __table_args__ = (
        CheckConstraint(
            "category IN ('enquiry', 'request', 'complaint')", name="category_valid"
        ),  # fmt: skip
        CheckConstraint(
            "channel IN ('phone', 'email', 'chat', 'branch', 'letter')", name="channel_valid"
        ),  # fmt: skip
        CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name="priority_valid"),
        CheckConstraint(
            "status IN ('open', 'awaiting_customer', 'resolved')", name="status_valid"
        ),  # fmt: skip
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('upheld', 'partly_upheld', 'not_upheld')",
            name="outcome_valid",
        ),
        CheckConstraint("outcome IS NULL OR category = 'complaint'", name="outcome_complaints"),
        CheckConstraint(
            "redress_status IS NULL OR redress_status IN ('proposed', 'paid', 'withdrawn')",
            name="redress_status_valid",
        ),
        CheckConstraint("redress_amount IS NULL OR redress_amount > 0", name="redress_positive"),
        CheckConstraint(
            "redress_approved_by IS NULL OR redress_approved_by <> redress_proposed_by",
            name="redress_four_eyes",
        ),
        Index("ix_service_cases_open_due", "status", "resolve_due"),
    )

    case_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    topic: Mapped[str] = mapped_column(String(30), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    opened_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # SLA: due times move later by any time spent awaiting the customer.
    first_response_due: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolve_due: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_breached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolution_breached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    escalated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    resolution: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)  # complaints
    redress_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    redress_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    redress_proposed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    redress_approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    redress_entry: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CaseEvent(UUIDPrimaryKey, Base):
    """The case's timeline: opened, responses, notes, pauses, breaches, redress, resolution."""

    __tablename__ = "service_case_events"

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("service_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
