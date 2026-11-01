"""Wealth and investments (Phase 43, roadmap Milestone D step 15): synthetic securities,
investment suitability, portfolios held in custody, orders and income.

A customer's investment profile (a suitability questionnaire) gives a risk profile from 1
to 7. A portfolio is a custody account linked to one of the customer's bank accounts, which
pays for purchases and receives sales and income. A buy order is checked against the
profile; a suitable order is executed at once at the day's price, an unsuitable one waits
for a second person's approval (an insistent client) or is rejected. Holdings are kept in
custody, off the bank's balance sheet: only the cash moves through the ledger.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
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

PORTFOLIO_SEQUENCE = Sequence("investment_portfolio_number_seq", start=1)
ORDER_SEQUENCE = Sequence("investment_order_number_seq", start=1)
DISTRIBUTION_SEQUENCE = Sequence("income_distribution_number_seq", start=1)


class AssetClass(StrEnum):
    MONEY_MARKET = "money_market"
    BOND = "bond"
    FUND = "fund"
    EQUITY = "equity"
    STRUCTURED = "structured"


class Security(UUIDPrimaryKey, Base):
    """A synthetic security. Its price on a day follows a deterministic model (a drift and a
    seasonal swing from `base_price`), so every run sees the same prices."""

    __tablename__ = "wealth_securities"
    __table_args__ = (
        CheckConstraint(
            "asset_class IN ('money_market', 'bond', 'fund', 'equity', 'structured')",
            name="asset_class_valid",
        ),
        CheckConstraint("risk_level BETWEEN 1 AND 7", name="risk_level_range"),
        CheckConstraint("base_price > 0", name="base_price_positive"),
        CheckConstraint("income_bps >= 0 AND volatility_bps >= 0", name="rates_valid"),
    )

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    risk_level: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 (lowest) to 7
    complex: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    base_price: Mapped[int] = mapped_column(BigInteger, nullable=False)  # minor units per unit
    drift_bps: Mapped[int] = mapped_column(Integer, nullable=False)  # a year
    volatility_bps: Mapped[int] = mapped_column(Integer, nullable=False)  # seasonal swing
    income_bps: Mapped[int] = mapped_column(Integer, nullable=False)  # a year, paid twice
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Objective(StrEnum):
    PRESERVATION = "preservation"
    INCOME = "income"
    BALANCED = "balanced"
    GROWTH = "growth"


class Knowledge(StrEnum):
    NONE = "none"
    BASIC = "basic"
    INFORMED = "informed"
    EXPERT = "expert"


class LossCapacity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class InvestmentProfile(UUIDPrimaryKey, Base):
    """A suitability assessment. The latest unexpired one is the customer's profile."""

    __tablename__ = "investment_profiles"
    __table_args__ = (
        CheckConstraint(
            "objective IN ('preservation', 'income', 'balanced', 'growth')",
            name="objective_valid",
        ),
        CheckConstraint(
            "knowledge IN ('none', 'basic', 'informed', 'expert')", name="knowledge_valid"
        ),
        CheckConstraint("loss_capacity IN ('low', 'medium', 'high')", name="loss_capacity_valid"),
        CheckConstraint("horizon_years BETWEEN 0 AND 50", name="horizon_range"),
        CheckConstraint("risk_profile BETWEEN 1 AND 7", name="risk_profile_range"),
        CheckConstraint("expires_on > assessed_on", name="expiry_after_assessment"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    objective: Mapped[str] = mapped_column(String(20), nullable=False)
    horizon_years: Mapped[int] = mapped_column(Integer, nullable=False)
    knowledge: Mapped[str] = mapped_column(String(20), nullable=False)
    loss_capacity: Mapped[str] = mapped_column(String(20), nullable=False)
    risk_profile: Mapped[int] = mapped_column(Integer, nullable=False)
    assessed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    assessed_on: Mapped[date] = mapped_column(Date, nullable=False)
    expires_on: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PortfolioStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class Portfolio(UUIDPrimaryKey, Base):
    """A custody account. Its currency is its cash account's."""

    __tablename__ = "investment_portfolios"
    __table_args__ = (CheckConstraint("status IN ('open', 'closed')", name="status_valid"),)

    portfolio_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    cash_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    opened_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Holding(UUIDPrimaryKey, Base):
    """Units of one security held in custody for a portfolio, at their average cost."""

    __tablename__ = "portfolio_holdings"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "security_id", name="uq_portfolio_holdings_security"),
        CheckConstraint("units >= 0 AND cost >= 0", name="units_and_cost"),
    )

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("investment_portfolios.id", ondelete="RESTRICT"), nullable=False,
        index=True,
    )  # fmt: skip
    security_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("wealth_securities.id", ondelete="RESTRICT"), nullable=False,
        index=True,
    )  # fmt: skip
    units: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cost: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)  # portfolio ccy


class OrderStatus(StrEnum):
    PLACED = "placed"  # suitable, waiting for the dealing desk to release it (workflows)
    AWAITING_APPROVAL = "awaiting_approval"  # unsuitable: a second person must approve
    EXECUTED = "executed"
    REJECTED = "rejected"


class InvestmentOrder(UUIDPrimaryKey, Base):
    __tablename__ = "investment_orders"
    __table_args__ = (
        CheckConstraint("side IN ('buy', 'sell')", name="side_valid"),
        CheckConstraint(
            "status IN ('placed', 'awaiting_approval', 'executed', 'rejected')",
            name="status_valid",
        ),
        CheckConstraint("units > 0 AND amount >= 0 AND fee >= 0", name="amounts_valid"),
        CheckConstraint("approved_by IS NULL OR approved_by <> placed_by", name="four_eyes"),
    )

    order_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("investment_portfolios.id", ondelete="RESTRICT"), nullable=False,
        index=True,
    )  # fmt: skip
    security_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("wealth_securities.id", ondelete="RESTRICT"), nullable=False,
        index=True,
    )  # fmt: skip
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    units: Mapped[int] = mapped_column(BigInteger, nullable=False)
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)  # the security's currency
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # the portfolio's currency
    fee: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    suitable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Why the order is unsuitable: [{code, message}], empty when suitable.
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    placed_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    executed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IncomeDistribution(UUIDPrimaryKey, Base):
    """A coupon, dividend or fund distribution paid to every holder of a security on a
    record date: at most one per security and date."""

    __tablename__ = "income_distributions"
    __table_args__ = (
        UniqueConstraint("security_id", "record_date", name="uq_income_distributions_date"),
        CheckConstraint("holders >= 0", name="holders_valid"),
    )

    distribution_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    security_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("wealth_securities.id", ondelete="RESTRICT"), nullable=False,
        index=True,
    )  # fmt: skip
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    income_per_unit: Mapped[int] = mapped_column(BigInteger, nullable=False)  # security ccy
    holders: Mapped[int] = mapped_column(Integer, nullable=False)
    paid_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
