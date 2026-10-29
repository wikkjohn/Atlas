import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Sequence,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.models import Timestamps, UUIDPrimaryKey, trigram_index
from app.modules.countries.models import Country

CUSTOMER_NUMBER_SEQUENCE = Sequence("customer_number_seq", start=1)


class CustomerType(StrEnum):
    INDIVIDUAL = "individual"
    BUSINESS = "business"


class RiskRating(StrEnum):
    UNRATED = "unrated"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class KycStatus(StrEnum):
    NOT_STARTED = "not_started"
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


# Allowed KYC status changes. Decisions can be re-opened for review, never skipped.
KYC_TRANSITIONS: dict[KycStatus, frozenset[KycStatus]] = {
    KycStatus.NOT_STARTED: frozenset({KycStatus.PENDING}),
    KycStatus.PENDING: frozenset({KycStatus.VERIFIED, KycStatus.REJECTED}),
    KycStatus.VERIFIED: frozenset({KycStatus.PENDING}),
    KycStatus.REJECTED: frozenset({KycStatus.PENDING}),
}


class Customer(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "customers"
    __table_args__ = (
        trigram_index("customers", "name"),
        trigram_index("customers", "customer_number"),
        CheckConstraint("customer_type IN ('individual', 'business')", name="customer_type_valid"),
        CheckConstraint(
            "risk_rating IN ('unrated', 'low', 'medium', 'high')", name="risk_rating_valid"
        ),
        CheckConstraint(
            "kyc_status IN ('not_started', 'pending', 'verified', 'rejected')",
            name="kyc_status_valid",
        ),
    )

    customer_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    customer_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    # Date of birth for individuals; date of incorporation for businesses.
    date_of_birth_or_incorporation: Mapped[date] = mapped_column(Date, nullable=False)
    country_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("countries.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    risk_rating: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    kyc_status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    country: Mapped[Country] = relationship(lazy="joined")


class CustomerNotification(UUIDPrimaryKey, Base):
    """A simulated message to a customer. Nothing is ever sent anywhere."""

    __tablename__ = "customer_notifications"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(30), nullable=False, default="simulated_email")
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Set when a workflow sent it (no FK: the customers module does not depend on workflows).
    workflow_execution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
