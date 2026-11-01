"""Risk (Phase 47, roadmap Milestone D step 19): internal credit ratings, obligor limits and
expected-credit-loss (ECL) provisioning.

Every customer can be rated on a ten-grade internal scale with a one-year probability of
default per grade; a model suggests the grade, and a rating that departs from it needs a
second person's approval. Each obligor has a credit limit (by grade, unless set), against
which their credit exposure is measured. A provisioning run measures the loan book's
expected credit loss by IFRS 9 stage, and a second person posts it to the ledger.
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

RATING_SEQUENCE = Sequence("credit_rating_number_seq", start=1)
PROVISION_SEQUENCE = Sequence("provision_run_number_seq", start=1)


class RatingStatus(StrEnum):
    PENDING = "pending"  # departs from the model: a second person must approve
    APPROVED = "approved"
    REJECTED = "rejected"


class CreditRating(UUIDPrimaryKey, Base):
    """An obligor rating. The latest approved, unexpired one is the customer's grade."""

    __tablename__ = "credit_ratings"
    __table_args__ = (
        CheckConstraint("grade BETWEEN 1 AND 10", name="grade_range"),
        CheckConstraint("suggested_grade BETWEEN 1 AND 10", name="suggested_grade_range"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="status_valid"),
        CheckConstraint("approved_by IS NULL OR approved_by <> rated_by", name="four_eyes"),
        CheckConstraint("expires_on > rated_on", name="expiry_after_rating"),
        # One rating awaiting approval per customer.
        Index(
            "uq_credit_ratings_pending",
            "customer_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),  # fmt: skip
    )

    rating_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    suggested_grade: Mapped[int] = mapped_column(Integer, nullable=False)
    pd_bps: Mapped[int] = mapped_column(Integer, nullable=False)  # one-year PD of the grade
    # What the model saw: the KYC rating, worst days past due, frozen facilities.
    factors: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rationale: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    rated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    rated_on: Mapped[date] = mapped_column(Date, nullable=False)
    expires_on: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ObligorLimit(UUIDPrimaryKey, Base):
    """A credit limit set for one customer, in US dollars; without one, the grade's applies."""

    __tablename__ = "obligor_limits"
    __table_args__ = (CheckConstraint("limit_usd >= 0", name="limit_valid"),)

    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    limit_usd: Mapped[int] = mapped_column(BigInteger, nullable=False)  # whole dollars
    set_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProvisionStatus(StrEnum):
    CALCULATED = "calculated"  # awaiting a second person's approval
    POSTED = "posted"
    REJECTED = "rejected"


class ProvisionRun(UUIDPrimaryKey, Base):
    """An ECL calculation over the loan book as of a date, and its posting."""

    __tablename__ = "provision_runs"
    __table_args__ = (
        CheckConstraint("status IN ('calculated', 'posted', 'rejected')", name="status_valid"),
        CheckConstraint("approved_by IS NULL OR approved_by <> calculated_by", name="four_eyes"),
    )

    run_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    as_of: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    exposures: Mapped[int] = mapped_column(Integer, nullable=False)
    # By currency: {stage_1, stage_2, stage_3, ecl, ead, previous, change}, minor units.
    totals: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
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


class ProvisionLine(UUIDPrimaryKey, Base):
    """One exposure's ECL in a run."""

    __tablename__ = "provision_lines"
    __table_args__ = (
        CheckConstraint("stage BETWEEN 1 AND 3", name="stage_range"),
        CheckConstraint(
            "exposure_type IN ('loan', 'mortgage', 'facility', 'overdraft')",
            name="exposure_type_valid",
        ),
        CheckConstraint("ead >= 0 AND ecl >= 0", name="amounts_valid"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("provision_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    exposure_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reference: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    ead: Mapped[int] = mapped_column(BigInteger, nullable=False)  # exposure at default
    days_past_due: Mapped[int] = mapped_column(Integer, nullable=False)
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[int] = mapped_column(Integer, nullable=False)
    pd_bps: Mapped[int] = mapped_column(Integer, nullable=False)  # applied (12m or lifetime)
    lgd_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    ecl: Mapped[int] = mapped_column(BigInteger, nullable=False)
