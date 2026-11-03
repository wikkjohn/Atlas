"""Systems access (Phase 74): Information Security's record of what access each employee
has been granted, requested when HR hires them and revoked when they leave."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Sequence, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey

GRANT_NUMBER_SEQUENCE = Sequence("access_grant_number_seq", start=1)


class GrantStatus(StrEnum):
    REQUESTED = "requested"
    GRANTED = "granted"
    REVOKED = "revoked"


class AccessGrant(UUIDPrimaryKey, Base):
    __tablename__ = "access_grants"
    __table_args__ = (
        CheckConstraint("status IN ('requested', 'granted', 'revoked')", name="status_valid"),
        CheckConstraint("status <> 'granted' OR granted_at IS NOT NULL", name="granted_dated"),
        CheckConstraint("status <> 'revoked' OR revoked_at IS NOT NULL", name="revoked_dated"),
        # One live grant per employee and profile.
        Index(
            "uq_access_grants_live",
            "employee_id",
            "profile",
            unique=True,
            postgresql_where=text("status <> 'revoked'"),
        ),
    )

    grant_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    profile: Mapped[str] = mapped_column(String(40), nullable=False)  # by the employee's role
    status: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # The event that asked for it (the outbox), so a redelivery cannot ask twice.
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("domain_events.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
