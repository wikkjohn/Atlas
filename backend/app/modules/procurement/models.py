"""Procurement and vendor management (Phase 57, roadmap Milestone D step 29).

A vendor is screened against the sanctions lists, tiered by risk and approved by someone
other than whoever registered it (high-risk vendors by an executive). A change to a
vendor's bank details must be verified by a second person, and nothing is paid to the
vendor while one waits. A purchase order for an approved vendor is approved by someone
other than the requester (an executive above US$50,000), received, and invoiced; an invoice
is paid only when it matches the order and what was received, within 2 %, and only by
someone other than whoever recorded it. The payment debits the department's purchases and
credits the bank's cash.
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
    Sequence,
    String,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey

VENDOR_SEQUENCE = Sequence("vendor_number_seq", start=1)
ORDER_SEQUENCE = Sequence("purchase_order_number_seq", start=1)
INVOICE_SEQUENCE = Sequence("vendor_invoice_number_seq", start=1)


class VendorStatus(StrEnum):
    PENDING = "pending"  # awaiting approval
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class OrderStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    RECEIVED = "received"
    REJECTED = "rejected"
    CLOSED = "closed"  # fully invoiced and paid


class InvoiceStatus(StrEnum):
    RECORDED = "recorded"  # matched, awaiting payment approval
    HELD = "held"  # does not match the order or the receipt
    PAID = "paid"
    REJECTED = "rejected"


class Vendor(UUIDPrimaryKey, Base):
    """A supplier the bank buys from."""

    __tablename__ = "vendors"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'suspended')", name="status_valid"
        ),  # fmt: skip
        CheckConstraint("risk_tier IN ('low', 'medium', 'high')", name="risk_tier_valid"),
        CheckConstraint("approved_by IS NULL OR approved_by <> registered_by", name="four_eyes"),
        CheckConstraint(
            "bank_change_verified_by IS NULL OR bank_change_verified_by <> bank_change_by",
            name="bank_change_four_eyes",
        ),
    )

    vendor_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    country_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("countries.id", ondelete="RESTRICT"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    bank_account: Mapped[str] = mapped_column(String(40), nullable=False)
    # A requested change of bank account, waiting for a second person to verify it.
    pending_bank_account: Mapped[str | None] = mapped_column(String(40), nullable=True)
    bank_change_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    bank_change_verified_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    bank_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    risk_tier: Mapped[str] = mapped_column(String(10), nullable=False)
    screening: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    registered_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PurchaseOrder(UUIDPrimaryKey, Base):
    """An order to an approved vendor, charged to a department."""

    __tablename__ = "purchase_orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requested', 'approved', 'received', 'rejected', 'closed')",
            name="status_valid",
        ),
        CheckConstraint("total > 0", name="total_positive"),
        CheckConstraint("received_amount >= 0", name="received_non_negative"),
        CheckConstraint("approved_by IS NULL OR approved_by <> requested_by", name="four_eyes"),
    )

    order_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    # [{description, quantity, unit_price}] in minor units of the vendor's currency.
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    received_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    received_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class VendorInvoice(UUIDPrimaryKey, Base):
    """A vendor's invoice against a purchase order."""

    __tablename__ = "vendor_invoices"
    __table_args__ = (
        CheckConstraint(
            "status IN ('recorded', 'held', 'paid', 'rejected')", name="status_valid"
        ),  # fmt: skip
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("paid_by IS NULL OR paid_by <> recorded_by", name="four_eyes"),
    )

    invoice_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    vendor_reference: Mapped[str] = mapped_column(String(40), nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("purchase_orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    hold_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # The bank account the payment went to, as it was on the day.
    paid_to: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entry_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    recorded_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    paid_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
