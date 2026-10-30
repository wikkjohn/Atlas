"""Foreign exchange (Phase 24): published rates, conversions (deals) and revaluation runs.

A conversion never mixes currencies in one journal entry. It posts two balanced entries
through the bank's currency position accounts (`FX-POSITION-<CCY>`, equity, credit-normal):
in the currency sold, the customer's account is debited and the position credited; in the
currency bought, the position is debited and the customer's account credited. The positions'
balances are the bank's open currency positions; their value in US dollars (at the day's
rates) is the bank's FX result, which revaluation books to income.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Numeric,
    Sequence,
    SmallInteger,
    String,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey

FX_DEAL_NUMBER_SEQUENCE = Sequence("fx_deal_number_seq", start=1)


class FxRate(Base):
    """A published daily rate: units of `currency` per US dollar."""

    __tablename__ = "fx_rates"
    __table_args__ = (CheckConstraint("units_per_usd > 0", name="rate_positive"),)

    currency: Mapped[str] = mapped_column(
        String(3), ForeignKey("currencies.code"), primary_key=True
    )
    rate_date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    units_per_usd: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="synthetic")
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FxDeal(UUIDPrimaryKey, Base):
    """One conversion: what was sold and bought, at which rates, and its two entries."""

    __tablename__ = "fx_deals"
    __table_args__ = (
        CheckConstraint("sell_currency <> buy_currency", name="distinct_currencies"),
        CheckConstraint("sell_amount > 0 AND buy_amount > 0", name="amounts_positive"),
        CheckConstraint("margin_bps BETWEEN 0 AND 1000", name="margin_range"),
    )

    deal_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    purpose: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reference: Mapped[str] = mapped_column(String(140), nullable=False)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False)
    sell_currency: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    sell_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # minor units
    buy_currency: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    buy_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # minor units
    # Units of the bought currency per unit of the sold one (major units).
    mid_rate: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    customer_rate: Mapped[Decimal] = mapped_column(Numeric(30, 12), nullable=False)
    margin_bps: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # The sold amount in US cents at the mid rate (positions are valued in US dollars).
    base_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sell_entry_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    buy_entry_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


class FxRevaluation(UUIDPrimaryKey, Base):
    """One revaluation of the open positions: their US-dollar value at the day's rates,
    what earlier runs had booked, and the difference posted to FX income."""

    __tablename__ = "fx_revaluations"

    run_number: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), nullable=False, unique=True
    )
    as_of: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    positions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    total_value: Mapped[int] = mapped_column(BigInteger, nullable=False)  # US cents
    previously_booked: Mapped[int] = mapped_column(BigInteger, nullable=False)
    posted: Mapped[int] = mapped_column(BigInteger, nullable=False)  # signed, US cents
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=True, unique=True
    )
    run_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
