"""Payments between synthetic customer accounts: domestic, or (Phase 24) to an account in
another currency, converted at release through an FX deal.

A payment record follows its workflow: `pending` while it is screened and approved, then
`released` (posted to the ledger) or `rejected`. Money only moves through the ledger; the
record keeps who started and who approved it so the controls can be re-checked later.
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
    Index,
    Sequence,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey, trigram_index

PAYMENT_NUMBER_SEQUENCE = Sequence("payment_number_seq", start=1)


class PaymentStatus(StrEnum):
    PENDING = "pending"
    RELEASED = "released"
    REJECTED = "rejected"


class Payment(UUIDPrimaryKey, Base):
    __tablename__ = "payments"
    __table_args__ = (
        trigram_index("payments", "payment_number"),
        trigram_index("payments", "reference"),
        Index("ix_payments_created_at_number", "created_at", "payment_number"),
        CheckConstraint("status IN ('pending', 'released', 'rejected')", name="status_valid"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("debtor_account_id <> creditor_account_id", name="distinct_accounts"),
        CheckConstraint(
            "(status = 'released') = (journal_entry_id IS NOT NULL)", name="released_has_entry"
        ),
        # Four-eyes, enforced by the database as well as the service.
        CheckConstraint("approved_by IS NULL OR approved_by <> initiated_by", name="four_eyes"),
        CheckConstraint(
            "status <> 'released' OR creditor_currency IS NULL OR fx_deal_id IS NOT NULL",
            name="released_fx_has_deal",
        ),
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
    # Cross-currency payments (Phase 24): the payee's currency, the amount it received (set
    # at release; an estimate before) and the conversion.
    # From the payer's country rules when the payment is created (Phase 25): the amount from
    # which it needs a second approver, and the business day it settles on (cut-off).
    high_value_threshold: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    creditor_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    creditor_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fx_deal_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("fx_deals.id", ondelete="RESTRICT"), nullable=True, unique=True
    )
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
