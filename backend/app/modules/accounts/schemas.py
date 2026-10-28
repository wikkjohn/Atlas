import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.accounts.models import AccountType
from app.modules.ledger.models import MAX_LINE_AMOUNT


class AccountRequestCreate(BaseModel):
    customer_id: uuid.UUID
    account_type: AccountType
    currency: str | None = Field(
        default=None, pattern=r"^[A-Z]{3}$", description="Defaults to the customer's currency."
    )


class Decision(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class Rejection(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class AccountRequestOut(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    customer_number: str
    customer_name: str
    customer_risk_rating: str
    account_type: str
    currency: str
    status: str
    requested_by: uuid.UUID
    requested_by_username: str | None
    decided_by: uuid.UUID | None
    decided_by_username: str | None
    decided_at: datetime | None
    decision_note: str | None
    account_id: uuid.UUID | None
    created_at: datetime


class AccountOut(BaseModel):
    id: uuid.UUID
    account_number: str
    customer_id: uuid.UUID
    customer_number: str
    customer_name: str
    account_type: str
    currency: str
    status: str
    ledger_account_id: uuid.UUID
    ledger_account_code: str
    balance: int = Field(description="Minor units, derived from posted ledger entries")
    opened_at: datetime
    closed_at: datetime | None


class Eligibility(BaseModel):
    eligible: bool
    reasons: list[str]


class Movement(BaseModel):
    amount: int = Field(gt=0, le=MAX_LINE_AMOUNT, description="Minor units")
    memo: str | None = Field(default=None, max_length=200)


class MovementOut(BaseModel):
    account: AccountOut
    journal_entry_id: uuid.UUID
    entry_number: str
    replayed: bool
