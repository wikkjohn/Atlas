"""SME and commercial lending (Phase 35, roadmap Milestone D step 7): credit facilities
for business customers, their covenants, covenant tests and annual reviews.

A facility is a term loan (drawn up to its limit once over its life) or a revolving
credit (repaid amounts can be drawn again). Drawn money is a receivable in the ledger:
a drawdown debits the facility's receivable and credits the business account; a repayment
reverses it. A breached covenant freezes the facility until the credit committee waives
the breach; an annual review renews or terminates it, and an overdue review stops
drawdowns.
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

FACILITY_SEQUENCE = Sequence("facility_number_seq", start=1)
REVIEW_SEQUENCE = Sequence("facility_review_number_seq", start=1)


class FacilityType(StrEnum):
    TERM_LOAN = "term_loan"
    REVOLVING = "revolving"


class FacilityStatus(StrEnum):
    PROPOSED = "proposed"  # awaiting credit approval
    ACTIVE = "active"
    FROZEN = "frozen"  # a covenant is breached: no drawdowns until waived
    DECLINED = "declined"
    TERMINATED = "terminated"  # by review: no drawdowns, repayments only


class CommercialFacility(UUIDPrimaryKey, Base):
    __tablename__ = "commercial_facilities"
    __table_args__ = (
        CheckConstraint("facility_type IN ('term_loan', 'revolving')", name="type_valid"),
        CheckConstraint(
            "status IN ('proposed', 'active', 'frozen', 'declined', 'terminated')",
            name="status_valid",
        ),
        CheckConstraint("credit_limit > 0", name="limit_positive"),
        CheckConstraint("drawn >= 0 AND drawn <= drawn_total", name="drawn_valid"),
        CheckConstraint("term_months BETWEEN 12 AND 120", name="term_valid"),
        CheckConstraint("approved_by IS NULL OR approved_by <> requested_by", name="four_eyes"),
        CheckConstraint(
            "committee_approved_by IS NULL OR (committee_approved_by <> requested_by "
            "AND committee_approved_by <> approved_by)",
            name="committee_four_eyes",
        ),
    )

    facility_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    facility_type: Mapped[str] = mapped_column(String(20), nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    credit_limit: Mapped[int] = mapped_column(BigInteger, nullable=False)  # minor units
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    annual_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    term_months: Mapped[int] = mapped_column(Integer, nullable=False)
    drawn: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)  # outstanding
    drawn_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)  # ever
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    ledger_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=True, unique=True
    )
    review_due_on: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    matures_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    committee_approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    frozen_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CovenantKind(StrEnum):
    MIN_DSCR = "min_dscr"  # EBITDA / debt service, at least the threshold
    MAX_LEVERAGE = "max_leverage"  # total debt / EBITDA, at most the threshold


class FacilityCovenant(UUIDPrimaryKey, Base):
    """A financial covenant; thresholds are ratios in hundredths (125 = 1.25×)."""

    __tablename__ = "facility_covenants"
    __table_args__ = (
        CheckConstraint("kind IN ('min_dscr', 'max_leverage')", name="kind_valid"),
        CheckConstraint("threshold_centi BETWEEN 1 AND 10000", name="threshold_range"),
        Index("uq_facility_covenants_kind", "facility_id", "kind", unique=True),
    )

    facility_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("commercial_facilities.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    threshold_centi: Mapped[int] = mapped_column(Integer, nullable=False)


class CovenantTest(UUIDPrimaryKey, Base):
    """A compliance test on the borrower's figures for a period."""

    __tablename__ = "covenant_tests"
    __table_args__ = (
        CheckConstraint("ebitda >= 0 AND debt_service > 0 AND total_debt >= 0", name="figures"),
        Index("uq_covenant_tests_period", "facility_id", "period_end", unique=True),
    )

    facility_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("commercial_facilities.id", ondelete="RESTRICT"), nullable=False
    )
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    ebitda: Mapped[int] = mapped_column(BigInteger, nullable=False)  # minor units, the year
    debt_service: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_debt: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # [{kind, threshold_centi, actual_centi, passed}]
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    breached: Mapped[bool] = mapped_column(nullable=False)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    waived_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    waived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReviewOutcome(StrEnum):
    RENEWED = "renewed"
    TERMINATED = "terminated"


class FacilityReview(UUIDPrimaryKey, Base):
    __tablename__ = "facility_reviews"
    __table_args__ = (
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('renewed', 'terminated')", name="outcome_valid"
        ),
        CheckConstraint("decided_by IS NULL OR decided_by <> opened_by", name="four_eyes"),
        # A facility has at most one open review.
        Index(
            "uq_facility_reviews_open",
            "facility_id",
            unique=True,
            postgresql_where=text("outcome IS NULL"),
        ),
    )

    review_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("commercial_facilities.id", ondelete="RESTRICT"), nullable=False
    )
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    opened_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    new_limit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
