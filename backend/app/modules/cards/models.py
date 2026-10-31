"""Cards (Phase 31, roadmap Milestone D step 3): debit card products, issued cards, card
authorisations from a synthetic merchant terminal, disputes and chargebacks.

Card numbers are synthetic: the 9999 prefix is used by no real card scheme, and the last
digit is a Luhn check digit. Money moves only through the ledger: an approved authorisation
debits the card's account and credits the card settlement account; a chargeback reverses
the disputed amount.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
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
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey

CARD_SEQUENCE = Sequence("card_number_seq", start=1)
AUTHORIZATION_SEQUENCE = Sequence("card_authorization_seq", start=1)
DISPUTE_SEQUENCE = Sequence("card_dispute_seq", start=1)


class CardProduct(Base):
    """A card product. The daily spending limit is set in US dollars and converted to each
    card's currency at the FX anchor rates."""

    __tablename__ = "card_products"
    __table_args__ = (
        CheckConstraint("daily_limit_usd BETWEEN 1 AND 100000", name="daily_limit_range"),
        CheckConstraint("validity_years BETWEEN 1 AND 10", name="validity_range"),
    )

    product_code: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    daily_limit_usd: Mapped[int] = mapped_column(Integer, nullable=False)
    validity_years: Mapped[int] = mapped_column(Integer, nullable=False)


class CardStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"  # by fraud rules or a person; can be released
    CANCELLED = "cancelled"  # permanently


class Card(UUIDPrimaryKey, Base):
    __tablename__ = "cards"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'blocked', 'cancelled')", name="status_valid"),
        CheckConstraint("daily_limit > 0", name="daily_limit_positive"),
        CheckConstraint("(status = 'blocked') = (blocked_reason IS NOT NULL)", name="block_reason"),
    )

    card_number: Mapped[str] = mapped_column(String(19), nullable=False, unique=True)
    product_code: Mapped[str] = mapped_column(
        String(40), ForeignKey("card_products.product_code", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    daily_limit: Mapped[int] = mapped_column(BigInteger, nullable=False)  # minor units
    expires_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    blocked_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuthorizationStatus(StrEnum):
    APPROVED = "approved"
    DECLINED = "declined"


class CardAuthorization(UUIDPrimaryKey, Base):
    __tablename__ = "card_authorizations"
    __table_args__ = (
        CheckConstraint("status IN ('approved', 'declined')", name="status_valid"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "(status = 'approved') = (journal_entry_id IS NOT NULL)", name="approved_has_entry"
        ),
        Index("ix_card_authorizations_card_created", "card_id", "created_at"),
    )

    auth_code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    card_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cards.id", ondelete="RESTRICT"), nullable=False
    )
    merchant_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # A synthetic merchant category code (four digits, ISO 18245 style).
    merchant_category: Mapped[str] = mapped_column(String(4), nullable=False)
    merchant_country: Mapped[str] = mapped_column(String(2), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # minor units
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    decline_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fraud_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fraud_signals: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DisputeStatus(StrEnum):
    OPEN = "open"
    REFUNDED = "refunded"  # charged back: the amount returned to the customer
    REJECTED = "rejected"


class CardDispute(UUIDPrimaryKey, Base):
    __tablename__ = "card_disputes"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'refunded', 'rejected')", name="status_valid"),
        CheckConstraint(
            "reason IN ('not_recognised', 'not_received', 'duplicate', 'wrong_amount')",
            name="reason_valid",
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("decided_by IS NULL OR decided_by <> opened_by", name="four_eyes"),
        CheckConstraint(
            "(status = 'refunded') = (refund_entry_id IS NOT NULL)", name="refund_has_entry"
        ),
        # One open or refunded dispute per authorisation.
        Index(
            "uq_card_disputes_live_authorization",
            "authorization_id",
            unique=True,
            postgresql_where=text("status <> 'rejected'"),
        ),
    )

    dispute_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    authorization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("card_authorizations.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    opened_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refund_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=True
    )
