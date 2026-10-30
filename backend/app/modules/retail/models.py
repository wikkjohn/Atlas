"""Retail banking (Phase 29, roadmap Milestone D step 1): products, overdrafts, standing
orders, month-end interest and fees, and statements.

Balances stay in the ledger. These tables hold the terms (products, an account's arranged
overdraft on `accounts.overdraft_limit`), the instructions (standing orders) and the
records of what month end did (runs and statements).
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
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey

STATEMENT_NUMBER_SEQUENCE = Sequence("statement_number_seq", start=1)
STANDING_ORDER_NUMBER_SEQUENCE = Sequence("standing_order_number_seq", start=1)


class RetailProduct(Base):
    """The terms of one account type. Money amounts are in US dollars and converted to each
    account's currency at the FX anchor rates, rounded to two significant figures."""

    __tablename__ = "retail_products"
    __table_args__ = (
        CheckConstraint("credit_rate_bps BETWEEN 0 AND 2000", name="credit_rate_range"),
        CheckConstraint("overdraft_rate_bps BETWEEN 0 AND 5000", name="overdraft_rate_range"),
        CheckConstraint("monthly_fee_usd_cents BETWEEN 0 AND 100000", name="fee_range"),
        CheckConstraint("max_overdraft_usd BETWEEN 0 AND 1000000", name="overdraft_range"),
    )

    account_type: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Interest a year in basis points: paid on credit balances, charged on overdrawn ones.
    credit_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    overdraft_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_fee_usd_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    # The largest arranged overdraft; 0: the product has none.
    max_overdraft_usd: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )


class StandingOrderFrequency(StrEnum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class StandingOrderStatus(StrEnum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    ENDED = "ended"  # past its end date
    FAILED = "failed"  # stopped after repeated failures


class StandingOrder(UUIDPrimaryKey, Base):
    __tablename__ = "standing_orders"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("debtor_account_id <> creditor_account_id", name="distinct_accounts"),
        CheckConstraint("frequency IN ('weekly', 'monthly')", name="frequency_valid"),
        CheckConstraint(
            "status IN ('active', 'cancelled', 'ended', 'failed')", name="status_valid"
        ),
        CheckConstraint("failures >= 0", name="failures_non_negative"),
    )

    order_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    debtor_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    creditor_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # minor units
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    frequency: Mapped[str] = mapped_column(String(10), nullable=False)
    # The day of the month (monthly) the order was set up for; a shorter month pays on its
    # last day.
    day_of_month: Mapped[int] = mapped_column(Integer, nullable=False)
    next_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reference: Mapped[str] = mapped_column(String(140), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    payments_made: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("payments.id", ondelete="RESTRICT"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MonthEndRun(UUIDPrimaryKey, Base):
    """One month end: interest, fees and statements for every open retail account."""

    __tablename__ = "retail_month_ends"
    __table_args__ = (UniqueConstraint("period_start", name="uq_retail_month_ends_period"),)

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    accounts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    statements: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    entries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Per currency, minor units: {"GBP": {"interest_paid": …, "interest_charged": …, "fees": …}}
    totals: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AccountStatement(UUIDPrimaryKey, Base):
    __tablename__ = "account_statements"
    __table_args__ = (
        UniqueConstraint("account_id", "period_start", name="uq_account_statements_period"),
        CheckConstraint("period_end >= period_start", name="period_ordered"),
    )

    statement_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # Minor units; balances can be negative (overdrawn).
    opening_balance: Mapped[int] = mapped_column(BigInteger, nullable=False)
    closing_balance: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_credits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_debits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lines: Mapped[int] = mapped_column(Integer, nullable=False)
    overdraft_limit: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    issued_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
