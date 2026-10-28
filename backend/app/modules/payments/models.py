"""Domestic payments between synthetic customer accounts.

A payment record follows its workflow: `pending` while it is screened and approved, then
`released` (posted to the ledger) or `rejected`. Money only moves through the ledger; the
record keeps who started and who approved it so the controls can be re-checked later.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Sequence,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey

PAYMENT_NUMBER_SEQUENCE = Sequence("payment_number_seq", start=1)


class PaymentStatus(StrEnum):
    PENDING = "pending"
    RELEASED = "released"
    REJECTED = "rejected"


class Payment(UUIDPrimaryKey, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'released', 'rejected')", name="status_valid"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("debtor_account_id <> creditor_account_id", name="distinct_accounts"),
        CheckConstraint(
            "(status = 'released') = (journal_entry_id IS NOT NULL)", name="released_has_entry"
        ),
        # Four-eyes, enforced by the database as well as the service.
        CheckConstraint("approved_by IS NULL OR approved_by <> initiated_by", name="four_eyes"),
    )

    payment_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    debtor_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    creditor_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # minor units
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reference: Mapped[str] = mapped_column(String(140), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    initiated_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # The person (or policy engine) that approved a held or high-value payment.
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=True, unique=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Set when a workflow created it (no FK: payments do not depend on workflows).
    workflow_execution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
