import uuid
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Sequence, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.models import Timestamps, UUIDPrimaryKey
from app.modules.countries.models import Country
from app.modules.identity.models import Role
from app.modules.organizations.models import Organization

EMPLOYEE_NUMBER_SEQUENCE = Sequence("employee_number_seq", start=1)
# Synthetic employees only ever receive addresses in this reserved (RFC 2606) domain.
SYNTHETIC_EMAIL_DOMAIN = "atlasbank.example"


class EmploymentStatus(StrEnum):
    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    TERMINATED = "terminated"


class Employee(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint(
            "employment_status IN ('active', 'on_leave', 'terminated')",
            name="employment_status_valid",
        ),
        CheckConstraint("annual_compensation >= 0", name="compensation_non_negative"),
        CheckConstraint("manager_id IS NULL OR manager_id <> id", name="not_own_manager"),
        CheckConstraint("compensation_currency ~ '^[A-Z]{3}$'", name="currency_format"),
    )

    employee_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    # The unit the employee works in (a department or a team) ...
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # ... and the department that unit belongs to (equal to organization_id for departments).
    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    job_title: Mapped[str] = mapped_column(String(150), nullable=False)
    # Platform role a user account for this employee receives by default.
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    country_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("countries.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    employment_status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # Integer minor units (e.g. cents) of compensation_currency. Never floating point.
    annual_compensation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    compensation_currency: Mapped[str] = mapped_column(String(3), nullable=False)

    organization: Mapped[Organization] = relationship(foreign_keys=[organization_id], lazy="joined")
    department: Mapped[Organization] = relationship(foreign_keys=[department_id], lazy="joined")
    manager: Mapped["Employee | None"] = relationship(remote_side="Employee.id", lazy="joined")
    country: Mapped[Country] = relationship(lazy="joined")
    role: Mapped[Role] = relationship(lazy="joined")
