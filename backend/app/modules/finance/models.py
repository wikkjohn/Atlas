"""Finance (Phase 49, roadmap Milestone D step 21): the month-end close of the general ledger,
regulatory reporting extracts and cost allocation.

A period close checks the ledger as of the month's end and, once a second person approves it,
posts the closing entry: each currency's income and expense accounts are brought to zero
against retained earnings. Regulatory reports are extracted for a closed period and submitted
to a (synthetic) regulator by someone other than their preparer. Shared operating costs are
allocated to departments by headcount, posted after a second person's approval.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Sequence,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey

CLOSE_SEQUENCE = Sequence("period_close_number_seq", start=1)
REPORT_SEQUENCE = Sequence("regulatory_report_number_seq", start=1)
ALLOCATION_SEQUENCE = Sequence("cost_allocation_number_seq", start=1)


class CloseStatus(StrEnum):
    PREPARED = "prepared"  # checks run; awaiting a second person's approval
    CLOSED = "closed"
    REJECTED = "rejected"


class PeriodClose(UUIDPrimaryKey, Base):
    """The close of one calendar month."""

    __tablename__ = "period_closes"
    __table_args__ = (
        CheckConstraint("status IN ('prepared', 'closed', 'rejected')", name="status_valid"),
        CheckConstraint("approved_by IS NULL OR approved_by <> prepared_by", name="four_eyes"),
        CheckConstraint("period_end >= period_start", name="period_valid"),
        # A month is prepared or closed once.
        Index(
            "uq_period_closes_period",
            "period",
            unique=True,
            postgresql_where=text("status <> 'rejected'"),
        ),  # fmt: skip
    )

    close_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # YYYY-MM
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # [{check, passed, blocking, detail}]
    checks: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    # By currency: {income, expense, net_income, accounts: [{code, type, balance}]}
    results: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    prepared_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReportType(StrEnum):
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    LARGE_EXPOSURES = "large_exposures"
    CREDIT_QUALITY = "credit_quality"


class ReportStatus(StrEnum):
    PREPARED = "prepared"
    SUBMITTED = "submitted"
    REJECTED = "rejected"


class RegulatoryReport(UUIDPrimaryKey, Base):
    """A regulatory reporting extract for a closed period."""

    __tablename__ = "regulatory_reports"
    __table_args__ = (
        CheckConstraint(
            "report_type IN ('balance_sheet', 'income_statement', 'large_exposures', "
            "'credit_quality')",
            name="report_type_valid",
        ),
        CheckConstraint("status IN ('prepared', 'submitted', 'rejected')", name="status_valid"),
        CheckConstraint("submitted_by IS NULL OR submitted_by <> prepared_by", name="four_eyes"),
        # One report of a type submitted per period.
        Index(
            "uq_regulatory_reports_submitted",
            "report_type",
            "period",
            unique=True,
            postgresql_where=text("status = 'submitted'"),
        ),  # fmt: skip
    )

    report_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    report_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    rows: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    prepared_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    reference: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AllocationStatus(StrEnum):
    CALCULATED = "calculated"
    POSTED = "posted"
    REJECTED = "rejected"


class CostAllocation(UUIDPrimaryKey, Base):
    """Shared operating costs of one currency and month, split across departments."""

    __tablename__ = "cost_allocations"
    __table_args__ = (
        CheckConstraint("status IN ('calculated', 'posted', 'rejected')", name="status_valid"),
        CheckConstraint("approved_by IS NULL OR approved_by <> calculated_by", name="four_eyes"),
        CheckConstraint("pool > 0", name="pool_positive"),
        # One allocation awaiting approval per month and currency.
        Index(
            "uq_cost_allocations_calculated",
            "period",
            "currency",
            unique=True,
            postgresql_where=text("status = 'calculated'"),
        ),  # fmt: skip
    )

    allocation_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    pool: Mapped[int] = mapped_column(BigInteger, nullable=False)  # minor units
    driver: Mapped[str] = mapped_column(String(20), nullable=False)
    # [{department_id, department, headcount, amount, account_code}]
    lines: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    calculated_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
