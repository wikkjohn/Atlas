import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.modules.ledger.models import MAX_LINE_AMOUNT, Direction, LedgerAccountType


class JournalLineIn(BaseModel):
    ledger_account_id: uuid.UUID
    direction: Direction
    amount: int = Field(gt=0, le=MAX_LINE_AMOUNT, description="Minor units")
    memo: str | None = Field(default=None, max_length=200)


class JournalEntryCreate(BaseModel):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    description: str = Field(min_length=3, max_length=500)
    effective_date: date | None = None
    lines: list[JournalLineIn] = Field(min_length=2, max_length=100)


class ReversalCreate(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class LedgerAccountCreate(BaseModel):
    code: str = Field(pattern=r"^[0-9]{4}-[A-Z0-9-]{1,50}$")
    name: str = Field(min_length=3, max_length=200)
    account_type: LedgerAccountType
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class LedgerAccountOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    account_type: str
    currency: str
    normal_balance: Direction
    balance: int = Field(description="Minor units on the account's normal side")
    created_at: datetime


class JournalLineOut(BaseModel):
    line_number: int
    ledger_account_id: uuid.UUID
    ledger_account_code: str
    ledger_account_name: str
    direction: str
    amount: int
    memo: str | None


class JournalEntryOut(BaseModel):
    id: uuid.UUID
    entry_number: str
    currency: str
    description: str
    source: str
    status: str
    effective_date: date
    posted_at: datetime
    posted_by: uuid.UUID | None
    correlation_id: str | None
    reversal_of_id: uuid.UUID | None
    reversed_by_id: uuid.UUID | None
    total: int
    lines: list[JournalLineOut]


class StatementLineOut(BaseModel):
    entry_id: uuid.UUID
    entry_number: str
    posted_at: datetime
    description: str
    source: str
    direction: str
    amount: int
    memo: str | None


class ReconciliationCheck(BaseModel):
    name: str
    passed: bool
    detail: str
    failures: list[dict] = []


class ReconciliationReport(BaseModel):
    ok: bool
    checked_at: datetime
    entries_checked: int
    lines_checked: int
    checks: list[ReconciliationCheck]
    # Phase 12: every run is recorded.
    id: uuid.UUID | None = None
    run_number: int | None = None
    mode: str = "full"
    window_start: datetime | None = Field(
        default=None, description="Incremental runs: entries posted from here were checked"
    )
    window_end: datetime | None = None
    duration_ms: int | None = None


class ReconciliationRunOut(BaseModel):
    id: uuid.UUID
    run_number: int
    mode: str
    ok: bool
    window_start: datetime | None
    window_end: datetime
    entries_checked: int
    lines_checked: int
    duration_ms: int
    failed_checks: list[str]
    run_by_username: str | None
    created_at: datetime
