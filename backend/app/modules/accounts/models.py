import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Sequence, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.models import Timestamps, UUIDPrimaryKey
from app.modules.customers.models import Customer

ACCOUNT_NUMBER_SEQUENCE = Sequence("account_number_seq", start=1)


class AccountType(StrEnum):
    CURRENT = "current"
    SAVINGS = "savings"
    BUSINESS_CURRENT = "business_current"


class AccountStatus(StrEnum):
    OPEN = "open"
    FROZEN = "frozen"
    CLOSED = "closed"


class RequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"  # the account has been opened
    REJECTED = "rejected"


class AccountRequest(UUIDPrimaryKey, Timestamps, Base):
    """A request to open an account. Approval is the only way an account is created."""

    __tablename__ = "account_requests"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="status_valid"),
        CheckConstraint(
            "account_type IN ('current', 'savings', 'business_current')",
            name="account_type_valid",
        ),
        # Four-eyes principle, enforced by the database as well as the service.
        CheckConstraint("decided_by IS NULL OR decided_by <> requested_by", name="four_eyes"),
        CheckConstraint(
            "(status = 'approved') = (account_id IS NOT NULL)", name="approved_has_account"
        ),
        # At most one open request per customer, type and currency.
        Index(
            "uq_account_requests_one_pending",
            "customer_id",
            "account_type",
            "currency",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    account_type: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True, unique=True
    )

    customer: Mapped[Customer] = relationship(lazy="joined")


class Account(UUIDPrimaryKey, Base):
    """Account metadata. The balance lives in the ledger, never here."""

    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            "account_type IN ('current', 'savings', 'business_current')",
            name="account_type_valid",
        ),
        CheckConstraint("status IN ('open', 'frozen', 'closed')", name="status_valid"),
        CheckConstraint("(status = 'closed') = (closed_at IS NOT NULL)", name="closed_has_date"),
        # No duplicate live accounts of the same type and currency for a customer.
        Index(
            "uq_accounts_one_live_per_type_currency",
            "customer_id",
            "account_type",
            "currency",
            unique=True,
            postgresql_where=text("status <> 'closed'"),
        ),
    )

    account_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    account_type: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    ledger_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    customer: Mapped[Customer] = relationship(lazy="joined")
