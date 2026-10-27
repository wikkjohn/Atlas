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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.models import UUIDPrimaryKey

JOURNAL_ENTRY_NUMBER_SEQUENCE = Sequence("journal_entry_number_seq", start=1)
# Upper bound for one line, far below bigint so sums of many lines cannot overflow.
MAX_LINE_AMOUNT = 10**15


class LedgerAccountType(StrEnum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    INCOME = "income"
    EXPENSE = "expense"


# Accounts whose balance increases with debits; the rest increase with credits.
DEBIT_NORMAL = frozenset({LedgerAccountType.ASSET, LedgerAccountType.EXPENSE})


class Direction(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class EntryStatus(StrEnum):
    POSTED = "posted"
    REVERSED = "reversed"  # a separate reversing entry offsets it


class LedgerAccount(UUIDPrimaryKey, Base):
    __tablename__ = "ledger_accounts"
    __table_args__ = (
        CheckConstraint(
            "account_type IN ('asset', 'liability', 'equity', 'income', 'expense')",
            name="account_type_valid",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
    )

    code: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class JournalEntry(UUIDPrimaryKey, Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        CheckConstraint("status IN ('posted', 'reversed')", name="status_valid"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
    )

    entry_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    # Every posting carries a key; replays return the original entry.
    idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    posted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=True, unique=True
    )

    lines: Mapped[list["JournalLine"]] = relationship(
        back_populates="entry", order_by="JournalLine.line_number", lazy="selectin"
    )


class JournalLine(UUIDPrimaryKey, Base):
    __tablename__ = "journal_lines"
    __table_args__ = (
        UniqueConstraint("journal_entry_id", "line_number", name="uq_journal_lines_entry_line"),
        CheckConstraint("direction IN ('debit', 'credit')", name="direction_valid"),
        CheckConstraint(
            f"amount > 0 AND amount <= {MAX_LINE_AMOUNT}", name="amount_positive_bounded"
        ),
    )

    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    ledger_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    # Integer minor units of the entry's currency.
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    memo: Mapped[str | None] = mapped_column(String(200), nullable=True)

    entry: Mapped[JournalEntry] = relationship(back_populates="lines")
    ledger_account: Mapped[LedgerAccount] = relationship(lazy="joined")
