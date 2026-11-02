"""Human resources (Phase 55, roadmap Milestone D step 27): hiring, onboarding, leave and
shifts.

A department opens a job requisition with a salary band; someone other than the requester
approves it; candidates are offered a salary inside the band, and an accepted offer hires
them as employees, each with an onboarding checklist. Leave is counted in business days by
the employee's country calendar, against an annual entitlement, and decided by someone
other than the requester. Shifts staff a department's day: nobody on leave, double-booked,
over 48 hours a week or without 11 hours' rest. A department's capacity on a day (rostered
staff not on leave) can size a simulation's staff.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Sequence,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey

REQUISITION_SEQUENCE = Sequence("job_requisition_number_seq", start=1)
CANDIDATE_SEQUENCE = Sequence("candidate_number_seq", start=1)
LEAVE_SEQUENCE = Sequence("leave_request_number_seq", start=1)
SHIFT_SEQUENCE = Sequence("shift_number_seq", start=1)


class RequisitionStatus(StrEnum):
    OPEN = "open"  # awaiting approval
    APPROVED = "approved"  # recruiting
    FILLED = "filled"
    CANCELLED = "cancelled"


class CandidateStatus(StrEnum):
    APPLIED = "applied"
    OFFERED = "offered"
    HIRED = "hired"
    DECLINED = "declined"
    REJECTED = "rejected"


class LeaveKind(StrEnum):
    ANNUAL = "annual"
    SICK = "sick"
    UNPAID = "unpaid"


class LeaveStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class JobRequisition(UUIDPrimaryKey, Base):
    """Permission to hire: a role, a number of openings and a salary band."""

    __tablename__ = "job_requisitions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'approved', 'filled', 'cancelled')", name="status_valid"
        ),  # fmt: skip
        CheckConstraint("openings BETWEEN 1 AND 50", name="openings_range"),
        CheckConstraint("filled BETWEEN 0 AND openings", name="filled_range"),
        CheckConstraint("salary_min > 0 AND salary_max >= salary_min", name="band_valid"),
        CheckConstraint("approved_by IS NULL OR approved_by <> requested_by", name="four_eyes"),
    )

    requisition_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    job_title: Mapped[str] = mapped_column(String(150), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    openings: Mapped[int] = mapped_column(Integer, nullable=False)
    filled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    salary_min: Mapped[int] = mapped_column(BigInteger, nullable=False)  # minor units, yearly
    salary_max: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Candidate(UUIDPrimaryKey, Base):
    """A synthetic applicant for a requisition, and any offer made to them."""

    __tablename__ = "candidates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('applied', 'offered', 'hired', 'declined', 'rejected')",
            name="status_valid",
        ),
        CheckConstraint("offered_salary IS NULL OR offered_salary > 0", name="salary_positive"),
    )

    candidate_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    requisition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("job_requisitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    offered_salary: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    offered_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OnboardingTask(UUIDPrimaryKey, Base):
    """One item of a new hire's onboarding checklist."""

    __tablename__ = "onboarding_tasks"
    __table_args__ = (UniqueConstraint("employee_id", "code", name="uq_onboarding_task"),)

    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    due: Mapped[date] = mapped_column(Date, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )


class LeaveRequest(UUIDPrimaryKey, Base):
    """Time off, counted in the employee's country's business days."""

    __tablename__ = "leave_requests"
    __table_args__ = (
        CheckConstraint("kind IN ('annual', 'sick', 'unpaid')", name="kind_valid"),
        CheckConstraint(
            "status IN ('requested', 'approved', 'rejected', 'cancelled')", name="status_valid"
        ),  # fmt: skip
        CheckConstraint("end_date >= start_date", name="dates_ordered"),
        CheckConstraint("days > 0", name="days_positive"),
        CheckConstraint("decided_by IS NULL OR decided_by <> requested_by", name="four_eyes"),
    )

    leave_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Shift(UUIDPrimaryKey, Base):
    """A department's shift on a day: when it starts, how long, and how many it needs."""

    __tablename__ = "shifts"
    __table_args__ = (
        CheckConstraint("start_hour BETWEEN 0 AND 23", name="start_hour_range"),
        CheckConstraint("hours BETWEEN 1 AND 12", name="hours_range"),
        CheckConstraint("required BETWEEN 1 AND 100", name="required_range"),
    )

    shift_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_hour: Mapped[int] = mapped_column(Integer, nullable=False)
    hours: Mapped[int] = mapped_column(Integer, nullable=False)
    required: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ShiftAssignment(UUIDPrimaryKey, Base):
    """An employee rostered onto a shift."""

    __tablename__ = "shift_assignments"
    __table_args__ = (UniqueConstraint("shift_id", "employee_id", name="uq_shift_assignment"),)

    shift_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("shifts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
