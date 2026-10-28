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
