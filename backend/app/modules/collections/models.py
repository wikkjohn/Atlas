"""Collections and recoveries (Phase 53, roadmap Milestone D step 25).

A payment plan spreads a loan's arrears into scheduled catch-up payments, each settling one
overdue instalment from the borrower's account; a second person approves it, and two missed
payments break it. While a plan is active the loan cannot be written off. After a write-off,
recoveries (the borrower's payments, a collection agency's remittances, a debt sale) are
booked to loan loss recoveries, never more than was written off; a debt sale needs the credit
committee.
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
    Integer,
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

PLAN_SEQUENCE = Sequence("payment_plan_number_seq", start=1)
RECOVERY_SEQUENCE = Sequence("loan_recovery_number_seq", start=1)


class PlanStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    COMPLETED = "completed"
    BROKEN = "broken"  # two payments missed
    REJECTED = "rejected"


class PaymentPlan(UUIDPrimaryKey, Base):
    """Catch-up payments for a loan in arrears."""

    __tablename__ = "payment_plans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'active', 'completed', 'broken', 'rejected')",
            name="status_valid",
        ),
        CheckConstraint("approved_by IS NULL OR approved_by <> proposed_by", name="four_eyes"),
        CheckConstraint("payments BETWEEN 1 AND 24", name="payments_range"),
        CheckConstraint("interval_days BETWEEN 7 AND 31", name="interval_range"),
        # One plan proposed or active per loan.
        Index(
            "uq_payment_plans_open",
            "loan_id",
            unique=True,
            postgresql_where=text("status IN ('proposed', 'active')"),
        ),
    )

    plan_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    loan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("loans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    arrears_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # at proposal
    days_past_due: Mapped[int] = mapped_column(Integer, nullable=False)  # at proposal
    payments: Mapped[int] = mapped_column(Integer, nullable=False)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False)
    # [{n, due, amount, status: due | paid | missed | settled, on}]
    schedule: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    missed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    proposed_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RecoveryKind(StrEnum):
    PAYMENT = "payment"  # the borrower pays after the write-off
    AGENCY = "agency"  # a collection agency remits what it collected
    DEBT_SALE = "debt_sale"  # the debt is sold; needs the credit committee


class RecoveryStatus(StrEnum):
    RECORDED = "recorded"  # a debt sale awaiting approval
    POSTED = "posted"
    REJECTED = "rejected"


class LoanRecovery(UUIDPrimaryKey, Base):
    """Money recovered on a written-off loan."""

    __tablename__ = "loan_recoveries"
    __table_args__ = (
        CheckConstraint("kind IN ('payment', 'agency', 'debt_sale')", name="kind_valid"),
        CheckConstraint("status IN ('recorded', 'posted', 'rejected')", name="status_valid"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("approved_by IS NULL OR approved_by <> recorded_by", name="four_eyes"),
    )

    recovery_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    loan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("loans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # minor units
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    recorded_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    entry_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
