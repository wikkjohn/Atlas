import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PaymentOut(BaseModel):
    id: uuid.UUID
    payment_number: str
    debtor_account_number: str
    debtor_name: str
    creditor_account_number: str
    creditor_name: str
    amount: int = Field(description="Minor units")
    currency: str
    # Cross-currency payments (Phase 24).
    creditor_currency: str | None = None
    creditor_amount: int | None = None
    fx_deal_number: str | None = None
    fx_rate: str | None = None  # the customer rate applied
    reference: str
    status: str
    high_value: bool
    initiated_by_username: str | None
    approved_by_username: str | None
    journal_entry_id: uuid.UUID | None
    rejection_reason: str | None
    workflow_execution_id: uuid.UUID | None
    created_at: datetime
    decided_at: datetime | None
