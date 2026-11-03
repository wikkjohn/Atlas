"""IT operations (Phase 59, roadmap Milestone D step 31).

The bank's applications are catalogued with an owning department and a criticality tier.
An incident against an application gets a priority from its impact and urgency, and with it
targets to respond and to resolve; a P1 is not closed without a post-incident review. A
change to an application is risk-rated and approved by someone other than whoever raised
it (by an executive for a high-risk change or a tier-1 application); nothing but an
emergency change goes into a tier-1 application during the month-end freeze, an emergency
change must answer an open P1 or P2 incident, and approved changes to one application never
overlap. A change that fails opens an incident against its application.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Sequence,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey

APPLICATION_SEQUENCE = Sequence("application_number_seq", start=1)
INCIDENT_SEQUENCE = Sequence("incident_number_seq", start=1)
CHANGE_SEQUENCE = Sequence("change_number_seq", start=1)
OUTAGE_SEQUENCE = Sequence("application_outage_number_seq", start=1)


class IncidentStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    CLOSED = "closed"


class ChangeStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    IMPLEMENTED = "implemented"
    FAILED = "failed"


class Application(UUIDPrimaryKey, Base):
    """An application the bank runs, owned by a department."""

    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint("tier BETWEEN 1 AND 3", name="tier_valid"),
        CheckConstraint("status IN ('active', 'retired')", name="status_valid"),
        CheckConstraint(
            "hosting IN ('on_premise', 'private_cloud', 'public_cloud', 'saas')",
            name="hosting_valid",
        ),
    )

    application_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # 1: customers or money stop when it stops; 2: a department stops; 3: an inconvenience.
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # The registry (Phase 63): who answers for it, what it is built on, where it runs.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    technology: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    hosting: Mapped[str] = mapped_column(String(20), nullable=False, default="on_premise")
    vendor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # The generator run that made it ("estate-v1:<seed>"), or None for one registered by hand.
    generated_from: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ApplicationDependency(UUIDPrimaryKey, Base):
    """One application relying on another (Phase 63): when the second stops, the first is
    affected."""

    __tablename__ = "application_dependencies"
    __table_args__ = (
        CheckConstraint("application_id <> depends_on_id", name="not_self"),
        CheckConstraint("kind IN ('data', 'api', 'batch', 'auth')", name="kind_valid"),
        UniqueConstraint("application_id", "depends_on_id", name="uq_application_dependency"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    depends_on_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Incident(UUIDPrimaryKey, Base):
    """Something wrong with an application."""

    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved', 'closed')", name="status_valid"
        ),  # fmt: skip
        CheckConstraint("priority BETWEEN 1 AND 4", name="priority_valid"),
        CheckConstraint("impact IN ('high', 'medium', 'low')", name="impact_valid"),
        CheckConstraint("urgency IN ('high', 'medium', 'low')", name="urgency_valid"),
    )

    incident_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    impact: Mapped[str] = mapped_column(String(10), nullable=False)
    urgency: Mapped[str] = mapped_column(String(10), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    respond_by: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolve_by: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_breached: Mapped[bool] = mapped_column(nullable=False, default=False)
    resolution_breached: Mapped[bool] = mapped_column(nullable=False, default=False)
    resolution: Mapped[str | None] = mapped_column(Text)
    review: Mapped[str | None] = mapped_column(Text)  # post-incident review (P1)
    # The change that caused it, when one did.
    change_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("change_requests.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    reported_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ChangeRequest(UUIDPrimaryKey, Base):
    """A planned change to an application."""

    __tablename__ = "change_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requested', 'approved', 'rejected', 'implemented', 'failed')",
            name="status_valid",
        ),
        CheckConstraint("kind IN ('standard', 'normal', 'emergency')", name="kind_valid"),
        CheckConstraint("risk IN ('low', 'medium', 'high')", name="risk_valid"),
        CheckConstraint("planned_end > planned_start", name="window_valid"),
        CheckConstraint("approved_by IS NULL OR approved_by <> requested_by", name="four_eyes"),
    )

    change_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    risk: Mapped[str] = mapped_column(String(10), nullable=False)
    backout_plan: Mapped[str] = mapped_column(Text, nullable=False, default="")
    planned_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    planned_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # The incident an emergency change answers.
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="RESTRICT", use_alter=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    implemented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ApplicationOutage(UUIDPrimaryKey, Base):
    """A window in which an application is down or degraded (Phase 64); open-ended while it
    has no end."""

    __tablename__ = "application_outages"
    __table_args__ = (
        CheckConstraint("kind IN ('down', 'degraded')", name="kind_valid"),
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="window_valid"),
    )

    outage_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                index=True)  # fmt: skip
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("incidents.id", ondelete="SET NULL")
    )
    declared_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    # A scenario's outage (Phase 67) applies only to its own simulation run's executions.
    simulation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("simulation_runs.id", ondelete="CASCADE"), index=True
    )
    ended_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
