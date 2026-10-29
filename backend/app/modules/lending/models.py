"""Personal loans to synthetic customers.

A loan exists only once it has been approved and disbursed: the principal is posted from a
loan receivable (an asset of the bank) to the customer's deposit account in one balanced
entry. Who applied, who underwrote and who approved for the credit committee are kept, and
the database refuses a loan decided by the person who applied for it.

Phase 10 adds servicing: a repayment schedule of level monthly instalments, the servicing
runs that accrue interest and collect instalments on the lending business date, and the
loan's end as repaid or written off.
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
    Identity,
    Index,
    Integer,
    Sequence,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey, trigram_index

LOAN_NUMBER_SEQUENCE = Sequence("loan_number_seq", start=1)


class LoanStatus(StrEnum):
    ACTIVE = "active"
    REPAID = "repaid"
    WRITTEN_OFF = "written_off"


class InstalmentStatus(StrEnum):
    SCHEDULED = "scheduled"  # not yet due
    DUE = "due"  # interest accrued on the due date, not yet collected: in arrears
    PAID = "paid"
    PREPAID = "prepaid"  # settled early by a payoff
    WRITTEN_OFF = "written_off"


class LoanPurpose(StrEnum):
    HOME_IMPROVEMENT = "home_improvement"
    VEHICLE = "vehicle"
    EDUCATION = "education"
    DEBT_CONSOLIDATION = "debt_consolidation"
    OTHER = "other"


class Loan(UUIDPrimaryKey, Base):
    __tablename__ = "loans"
    __table_args__ = (
        trigram_index("loans", "loan_number"),
        Index("ix_loans_disbursed_at_number", "disbursed_at", "loan_number"),
        CheckConstraint("status IN ('active', 'repaid', 'written_off')", name="status_valid"),
        CheckConstraint("(status = 'active') = (closed_at IS NULL)", name="closed_has_date"),
        CheckConstraint("principal > 0", name="principal_positive"),
        CheckConstraint("term_months BETWEEN 6 AND 84", name="term_valid"),
        CheckConstraint("annual_rate_bps BETWEEN 0 AND 5000", name="rate_valid"),
        CheckConstraint("underwritten_by <> requested_by", name="four_eyes"),
        CheckConstraint(
            "committee_approved_by IS NULL OR (committee_approved_by <> requested_by "
            "AND committee_approved_by <> underwritten_by)",
            name="committee_four_eyes",
        ),
    )

    loan_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    disbursement_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ledger_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    principal: Mapped[int] = mapped_column(BigInteger, nullable=False)  # minor units
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    annual_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    term_months: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_payment: Mapped[int] = mapped_column(BigInteger, nullable=False)
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    underwritten_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    committee_approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    disbursement_entry_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    # Set when a workflow originated it (no FK: lending does not depend on workflows).
    workflow_execution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    disbursed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Phase 10: servicing.
    interest_receivable_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=True, unique=True
    )
    closed_on: Mapped[date | None] = mapped_column(Date, nullable=True)  # business date
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    written_off_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    write_off_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=True, unique=True
    )


class LoanInstalment(UUIDPrimaryKey, Base):
    """One monthly instalment of a loan's repayment schedule."""

    __tablename__ = "loan_instalments"
    __table_args__ = (
        UniqueConstraint("loan_id", "number", name="uq_loan_instalments_number"),
        CheckConstraint(
            "status IN ('scheduled', 'due', 'paid', 'prepaid', 'written_off')",
            name="status_valid",
        ),
        CheckConstraint("principal >= 0 AND interest >= 0", name="amounts_valid"),
        # Each status has exactly the postings it implies.
        CheckConstraint(
            "(status = 'scheduled' AND accrual_entry_id IS NULL AND payment_entry_id IS NULL)"
            " OR (status = 'due' AND accrual_entry_id IS NOT NULL AND payment_entry_id IS NULL)"
            " OR (status = 'paid' AND accrual_entry_id IS NOT NULL"
            " AND payment_entry_id IS NOT NULL)"
            " OR (status = 'prepaid' AND accrual_entry_id IS NULL"
            " AND payment_entry_id IS NOT NULL)"
            " OR (status = 'written_off' AND payment_entry_id IS NULL)",
            name="entries_match_status",
        ),
    )

    loan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("loans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    principal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    interest: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    accrual_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=True
    )
    payment_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=True
    )
    paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    @property
    def amount(self) -> int:
        return self.principal + self.interest


class LoanServicingRun(UUIDPrimaryKey, Base):
    """One servicing run: everything due up to `as_of` (the lending business date) was
    accrued and collection attempted. Business dates never go backwards."""

    __tablename__ = "loan_servicing_runs"

    run_number: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), nullable=False, unique=True
    )
    as_of: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    started_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
