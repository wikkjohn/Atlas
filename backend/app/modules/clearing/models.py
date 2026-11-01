"""Payments operations (Phase 41, roadmap Milestone D step 13): payments to accounts at other
(synthetic) banks through a simulated external clearing system, bulk payment files, and
recalls.

An outgoing payment waits for an approval when it is high value, then for the next
clearing cycle. A cycle puts a currency's pending payments into a batch and debits each
payer into the clearing suspense account; settlement pays the accepted ones out of the
bank's cash account and returns the rest to the payer. A recall cancels a payment not yet
cleared, or asks the beneficiary's bank to send a settled one back.
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

OUTGOING_SEQUENCE = Sequence("outgoing_payment_number_seq", start=1)
BATCH_SEQUENCE = Sequence("clearing_batch_number_seq", start=1)
BULK_SEQUENCE = Sequence("bulk_file_number_seq", start=1)
RECALL_SEQUENCE = Sequence("payment_recall_number_seq", start=1)


class OutgoingStatus(StrEnum):
    AWAITING_APPROVAL = "awaiting_approval"  # high value: a second person must approve
    PENDING = "pending"  # waiting for the next clearing cycle
    IN_CLEARING = "in_clearing"  # in a submitted batch, payer debited
    SETTLED = "settled"  # paid out to the beneficiary's bank
    RETURNED = "returned"  # the beneficiary's bank sent it back; payer refunded
    REJECTED = "rejected"  # refused before clearing (approval, funds)
    RECALLED = "recalled"  # cancelled before clearing, or sent back after a recall


class OutgoingPayment(UUIDPrimaryKey, Base):
    __tablename__ = "outgoing_payments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('awaiting_approval', 'pending', 'in_clearing', 'settled', 'returned', "
            "'rejected', 'recalled')",
            name="status_valid",
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("approved_by IS NULL OR approved_by <> initiated_by", name="four_eyes"),
    )

    payment_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    debtor_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    beneficiary_name: Mapped[str] = mapped_column(String(140), nullable=False)
    beneficiary_bank: Mapped[str] = mapped_column(String(11), nullable=False)
    beneficiary_account: Mapped[str] = mapped_column(String(34), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # minor units
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reference: Mapped[str] = mapped_column(String(140), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    high_value: Mapped[bool] = mapped_column(nullable=False, default=False)
    bulk_file_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("bulk_payment_files.id", ondelete="RESTRICT"), nullable=True,
        index=True,
    )  # fmt: skip
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("clearing_batches.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    return_code: Mapped[str | None] = mapped_column(String(4), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    initiated_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    settled_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BatchStatus(StrEnum):
    SUBMITTED = "submitted"  # payers debited into clearing suspense
    SETTLED = "settled"


class ClearingBatch(UUIDPrimaryKey, Base):
    """One clearing cycle for one currency."""

    __tablename__ = "clearing_batches"
    __table_args__ = (
        CheckConstraint("status IN ('submitted', 'settled')", name="status_valid"),
        CheckConstraint("payments >= 0 AND total >= 0", name="totals"),
    )

    batch_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    payments: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    settled_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    returned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    run_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BulkStatus(StrEnum):
    RECEIVED = "received"  # validated, awaiting approval
    RELEASED = "released"  # approved: its valid lines are outgoing payments
    REJECTED = "rejected"


class BulkPaymentFile(UUIDPrimaryKey, Base):
    """A bulk payment file from a business account: many payments, one approval."""

    __tablename__ = "bulk_payment_files"
    __table_args__ = (
        CheckConstraint("status IN ('received', 'released', 'rejected')", name="status_valid"),
        CheckConstraint("approved_by IS NULL OR approved_by <> received_by", name="four_eyes"),
    )

    file_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    file_name: Mapped[str] = mapped_column(String(140), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # Each line as uploaded, with `error` set when it failed validation.
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    valid_count: Mapped[int] = mapped_column(Integer, nullable=False)
    invalid_count: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    received_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    decision_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RecallStatus(StrEnum):
    REQUESTED = "requested"  # awaiting a second person's approval
    SENT = "sent"  # asked of the beneficiary's bank (the payment was settled)
    ACCEPTED = "accepted"  # the money came back, or the payment was cancelled
    REFUSED = "refused"  # the beneficiary's bank declined
    WITHDRAWN = "withdrawn"  # not approved


RECALL_REASONS = {"DUPL": "duplicate payment", "FRAD": "fraud", "TECH": "technical error",
                  "CUST": "customer request"}  # fmt: skip


class PaymentRecall(UUIDPrimaryKey, Base):
    __tablename__ = "payment_recalls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requested', 'sent', 'accepted', 'refused', 'withdrawn')",
            name="status_valid",
        ),
        CheckConstraint("reason_code IN ('DUPL', 'FRAD', 'TECH', 'CUST')", name="reason_valid"),
        CheckConstraint("approved_by IS NULL OR approved_by <> requested_by", name="four_eyes"),
        # One open recall per payment.
        Index(
            "uq_payment_recalls_open",
            "payment_id",
            unique=True,
            postgresql_where=text("status IN ('requested', 'sent')"),
        ),
    )

    recall_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("outgoing_payments.id", ondelete="RESTRICT"), nullable=False,
        index=True,
    )  # fmt: skip
    reason_code: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    outcome_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
