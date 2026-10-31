"""Treasury and markets (Phase 39, roadmap Milestone D step 11): interbank money-market
deals with synthetic counterparty banks, the FX desk's interbank spot trades and position
limits, and the bank's liquidity.

A dealer books a deal; back office (someone else) confirms it, which settles it through the
ledger against the bank's cash account in that currency. A placement lends cash to a
counterparty within its credit limit; a borrowing takes cash in. At maturity back office
settles principal and interest. The FX desk squares open currency positions with
interbank spot trades at the day's mid rate.
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
    Integer,
    Sequence,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey

DEAL_SEQUENCE = Sequence("treasury_deal_number_seq", start=1)
FX_TRADE_SEQUENCE = Sequence("treasury_fx_trade_number_seq", start=1)


class TreasuryCounterparty(UUIDPrimaryKey, Base):
    """A synthetic counterparty bank and the credit limit for placements with it."""

    __tablename__ = "treasury_counterparties"
    __table_args__ = (CheckConstraint("limit_usd >= 0", name="limit_non_negative"),)

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    rating: Mapped[str] = mapped_column(String(4), nullable=False)
    limit_usd: Mapped[int] = mapped_column(BigInteger, nullable=False)  # whole US dollars
    limit_changed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DealKind(StrEnum):
    PLACEMENT = "placement"  # the bank lends cash to the counterparty
    BORROWING = "borrowing"  # the bank takes cash from the counterparty


class DealStatus(StrEnum):
    BOOKED = "booked"  # awaiting back-office confirmation
    SETTLED = "settled"  # confirmed: cash moved at the start
    MATURED = "matured"  # principal and interest settled
    CANCELLED = "cancelled"


class TreasuryDeal(UUIDPrimaryKey, Base):
    """An interbank money-market deal: a placement or a borrowing at a fixed rate."""

    __tablename__ = "treasury_deals"
    __table_args__ = (
        CheckConstraint("kind IN ('placement', 'borrowing')", name="kind_valid"),
        CheckConstraint(
            "status IN ('booked', 'settled', 'matured', 'cancelled')", name="status_valid"
        ),
        CheckConstraint("principal > 0 AND interest >= 0", name="amounts"),
        CheckConstraint("rate_bps >= 0 AND rate_bps <= 5000", name="rate_valid"),
        CheckConstraint("maturity_date > value_date", name="dates_valid"),
        CheckConstraint("day_basis IN (360, 365)", name="day_basis_valid"),
        CheckConstraint("confirmed_by IS NULL OR confirmed_by <> booked_by", name="four_eyes"),
        CheckConstraint("matured_by IS NULL OR matured_by <> booked_by", name="maturity_four_eyes"),
    )

    deal_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("treasury_counterparties.id", ondelete="RESTRICT"), nullable=False,
        index=True,
    )  # fmt: skip
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    principal: Mapped[int] = mapped_column(BigInteger, nullable=False)  # minor units
    rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)  # a year
    day_basis: Mapped[int] = mapped_column(Integer, nullable=False)  # ACT/360 or ACT/365
    value_date: Mapped[date] = mapped_column(Date, nullable=False)
    maturity_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    interest: Mapped[int] = mapped_column(BigInteger, nullable=False)  # at maturity
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    booked_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    matured_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FxTradeStatus(StrEnum):
    BOOKED = "booked"
    SETTLED = "settled"
    CANCELLED = "cancelled"


class TreasuryFxTrade(UUIDPrimaryKey, Base):
    """An interbank spot trade by the FX desk at the day's mid rate, to square a position."""

    __tablename__ = "treasury_fx_trades"
    __table_args__ = (
        CheckConstraint("status IN ('booked', 'settled', 'cancelled')", name="status_valid"),
        CheckConstraint("sell_amount > 0 AND buy_amount > 0", name="amounts"),
        CheckConstraint("sell_currency <> buy_currency", name="currencies_differ"),
        CheckConstraint("confirmed_by IS NULL OR confirmed_by <> booked_by", name="four_eyes"),
    )

    trade_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("treasury_counterparties.id", ondelete="RESTRICT"), nullable=False,
        index=True,
    )  # fmt: skip
    sell_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    sell_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    buy_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    buy_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mid_rate: Mapped[str] = mapped_column(String(40), nullable=False)  # buy units per sold
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    booked_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TreasuryFxLimit(Base):
    """The FX desk's net open position limit for a currency, in whole US dollars."""

    __tablename__ = "treasury_fx_limits"
    __table_args__ = (CheckConstraint("limit_usd >= 0", name="limit_non_negative"),)

    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    limit_usd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
