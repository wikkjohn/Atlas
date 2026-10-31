"""Trade finance (Phase 37, roadmap Milestone D step 9): letters of credit and bank
guarantees for business customers, documents presented under letters of credit, and
claims under guarantees.

The bank holds a cash margin from the applicant while an instrument is live: issuing moves
it from the applicant's business account to the trade margin account; payment or expiry
releases it. A payment to the beneficiary debits the applicant's account and credits trade
settlement. Beneficiaries are screened against the synthetic sanctions lists.
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

INSTRUMENT_SEQUENCE = Sequence("trade_instrument_number_seq", start=1)
DEMAND_SEQUENCE = Sequence("trade_demand_number_seq", start=1)


class InstrumentKind(StrEnum):
    LETTER_OF_CREDIT = "letter_of_credit"  # pays against compliant documents
    GUARANTEE = "guarantee"  # pays a complying demand


class InstrumentStatus(StrEnum):
    REQUESTED = "requested"  # awaiting credit approval
    ISSUED = "issued"
    DECLINED = "declined"
    PAID = "paid"  # drawn in full
    EXPIRED = "expired"  # expired undrawn; margin released


class TradeInstrument(UUIDPrimaryKey, Base):
    __tablename__ = "trade_instruments"
    __table_args__ = (
        CheckConstraint("kind IN ('letter_of_credit', 'guarantee')", name="kind_valid"),
        CheckConstraint(
            "status IN ('requested', 'issued', 'declined', 'paid', 'expired')",
            name="status_valid",
        ),
        CheckConstraint("amount > 0 AND margin >= 0 AND margin <= amount", name="amounts"),
        CheckConstraint("drawn >= 0 AND drawn <= amount", name="drawn_valid"),
        CheckConstraint("approved_by IS NULL OR approved_by <> requested_by", name="four_eyes"),
        CheckConstraint(
            "committee_approved_by IS NULL OR (committee_approved_by <> requested_by "
            "AND committee_approved_by <> approved_by)",
            name="committee_four_eyes",
        ),
    )

    instrument_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    beneficiary_name: Mapped[str] = mapped_column(String(140), nullable=False)
    beneficiary_country: Mapped[str] = mapped_column(String(2), nullable=False)
    purpose: Mapped[str] = mapped_column(String(140), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # minor units
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    margin_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    margin: Mapped[int] = mapped_column(BigInteger, nullable=False)  # held while live
    drawn: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    expires_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # The screening result at request: {hit, matched, list, lists}.
    screening: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    committee_approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DemandStatus(StrEnum):
    PENDING = "pending"  # being checked
    PAID = "paid"
    REJECTED = "rejected"


DISCREPANCIES = frozenset(
    {
        "late_shipment",
        "late_presentation",
        "inconsistent_documents",
        "missing_document",
        "description_mismatch",
    }  # fmt: skip
)


class TradeDemand(UUIDPrimaryKey, Base):
    """A presentation of documents under a letter of credit, or a claim under a guarantee."""

    __tablename__ = "trade_demands"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'paid', 'rejected')", name="status_valid"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("decided_by IS NULL OR decided_by <> received_by", name="four_eyes"),
        # One demand at a time is being checked per instrument.
        Index(
            "uq_trade_demands_pending",
            "instrument_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    demand_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("trade_instruments.id", ondelete="RESTRICT"), nullable=False,
        index=True,
    )  # fmt: skip
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    presented_on: Mapped[date] = mapped_column(Date, nullable=False)
    # Letters of credit: the discrepancies found in the documents (empty: compliant).
    discrepancies: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    received_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    decision_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
