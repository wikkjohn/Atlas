"""Mortgages and secured lending (Phase 33, roadmap Milestone D step 5): mortgage
products, the properties that secure them, valuations, and mortgage offers.

A completed offer becomes an ordinary loan (purpose `mortgage`) charged on its property:
the lending module's schedules, servicing, arrears and collections apply unchanged. A
property secures at most one live loan and has at most one live offer. Addresses and
values are synthetic.
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

PROPERTY_SEQUENCE = Sequence("property_number_seq", start=1)
VALUATION_SEQUENCE = Sequence("valuation_number_seq", start=1)
OFFER_SEQUENCE = Sequence("mortgage_offer_number_seq", start=1)


class MortgageProduct(Base):
    """A mortgage product. Loan sizes are set in US dollars and converted to each
    property's currency at the FX anchor rates."""

    __tablename__ = "mortgage_products"
    __table_args__ = (
        CheckConstraint("max_ltv_bps BETWEEN 1000 AND 10000", name="ltv_range"),
        CheckConstraint("annual_rate_bps BETWEEN 0 AND 3000", name="rate_range"),
        CheckConstraint("max_term_years BETWEEN 5 AND 35", name="term_range"),
        CheckConstraint("min_loan_usd > 0 AND max_loan_usd >= min_loan_usd", name="loan_range"),
    )

    product_code: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    max_ltv_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    annual_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    max_term_years: Mapped[int] = mapped_column(Integer, nullable=False)
    min_loan_usd: Mapped[int] = mapped_column(Integer, nullable=False)
    max_loan_usd: Mapped[int] = mapped_column(Integer, nullable=False)


class PropertyType(StrEnum):
    HOUSE = "house"
    FLAT = "flat"


class Property(UUIDPrimaryKey, Base):
    __tablename__ = "properties"
    __table_args__ = (
        CheckConstraint("property_type IN ('house', 'flat')", name="type_valid"),
        CheckConstraint("purchase_price > 0", name="price_positive"),
    )

    property_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    property_type: Mapped[str] = mapped_column(String(10), nullable=False)
    address: Mapped[str] = mapped_column(String(200), nullable=False)
    purchase_price: Mapped[int] = mapped_column(BigInteger, nullable=False)  # minor units
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ValuationMethod(StrEnum):
    DESKTOP = "desktop"  # the synthetic automated valuation model
    SURVEYOR = "surveyor"  # a person inspected the property


class PropertyValuation(UUIDPrimaryKey, Base):
    __tablename__ = "property_valuations"
    __table_args__ = (
        CheckConstraint("method IN ('desktop', 'surveyor')", name="method_valid"),
        CheckConstraint("value > 0", name="value_positive"),
        CheckConstraint("(method = 'desktop') = (valued_by IS NULL)", name="surveyor_named"),
    )

    valuation_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    valued_on: Mapped[date] = mapped_column(Date, nullable=False)
    valued_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OfferStatus(StrEnum):
    PENDING = "pending"  # requested; an underwriter decides
    OFFERED = "offered"  # approved; valid until expires_on
    DECLINED = "declined"
    ACCEPTED = "accepted"  # by the customer; awaiting completion
    COMPLETED = "completed"  # the loan is drawn down
    WITHDRAWN = "withdrawn"


LIVE_OFFER_STATUSES = ("pending", "offered", "accepted")


class MortgageOffer(UUIDPrimaryKey, Base):
    __tablename__ = "mortgage_offers"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'offered', 'declined', 'accepted', 'completed', 'withdrawn')",
            name="status_valid",
        ),
        CheckConstraint("loan_amount > 0", name="amount_positive"),
        CheckConstraint("term_months BETWEEN 60 AND 420", name="term_valid"),
        CheckConstraint("decided_by IS NULL OR decided_by <> requested_by", name="four_eyes"),
        CheckConstraint(
            "completed_by IS NULL OR completed_by <> requested_by", name="completion_four_eyes"
        ),
        CheckConstraint("(status = 'completed') = (loan_id IS NOT NULL)", name="completed_loan"),
        # A property has at most one live offer.
        Index(
            "uq_mortgage_offers_live_property",
            "property_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'offered', 'accepted')"),
        ),
    )

    offer_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    valuation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("property_valuations.id", ondelete="RESTRICT"), nullable=False
    )
    product_code: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("mortgage_products.product_code", ondelete="RESTRICT"),
        nullable=False,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    loan_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    term_months: Mapped[int] = mapped_column(Integer, nullable=False)
    annual_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_payment: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ltv_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    declared_monthly_income: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    loan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("loans.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
