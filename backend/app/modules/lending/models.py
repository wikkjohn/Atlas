"""Personal loans to synthetic customers.

A loan exists only once it has been approved and disbursed: the principal is posted from a
loan receivable (an asset of the bank) to the customer's deposit account in one balanced
entry. Who applied, who underwrote and who approved for the credit committee are kept, and
the database refuses a loan decided by the person who applied for it.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Sequence,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey

LOAN_NUMBER_SEQUENCE = Sequence("loan_number_seq", start=1)


class LoanStatus(StrEnum):
    ACTIVE = "active"
    REPAID = "repaid"


class LoanPurpose(StrEnum):
    HOME_IMPROVEMENT = "home_improvement"
    VEHICLE = "vehicle"
    EDUCATION = "education"
    DEBT_CONSOLIDATION = "debt_consolidation"
    OTHER = "other"


class Loan(UUIDPrimaryKey, Base):
    __tablename__ = "loans"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'repaid')", name="status_valid"),
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
