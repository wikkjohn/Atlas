"""Thin departments' requests (Phase 61, roadmap Milestone D step 33).

Every thin department's processes share one request record: a title, an amount when the
process carries one, a target for completion, and a decision by someone other than the
requester when the process needs approval. See `registry.py` for the departments.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Sequence,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey

REQUEST_SEQUENCE = Sequence("department_request_number_seq", start=1)


class RequestStatus(StrEnum):
    SUBMITTED = "submitted"  # waiting for approval
    APPROVED = "approved"  # approved (or needing none), waiting to be completed
    REJECTED = "rejected"
    COMPLETED = "completed"


class DepartmentRequest(UUIDPrimaryKey, Base):
    """A request to one of a thin department's processes."""

    __tablename__ = "department_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('submitted', 'approved', 'rejected', 'completed')", name="status_valid"
        ),  # fmt: skip
        CheckConstraint("amount IS NULL OR amount > 0", name="amount_positive"),
        CheckConstraint("decided_by IS NULL OR decided_by <> requested_by", name="four_eyes"),
    )

    request_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    department: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    process: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # US cents, when the process carries an amount.
    amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    breached: Mapped[bool] = mapped_column(nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(String(300))
    requested_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
