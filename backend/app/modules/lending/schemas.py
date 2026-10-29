import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LoanOut(BaseModel):
    id: uuid.UUID
    loan_number: str
    customer_id: uuid.UUID
    customer_number: str
    customer_name: str
    disbursement_account_number: str
    principal: int = Field(description="Minor units")
    currency: str
    annual_rate_bps: int
    term_months: int
    monthly_payment: int = Field(description="Minor units")
    purpose: str
    status: str
    outstanding: int = Field(description="Minor units, derived from the loan's ledger account")
    requested_by_username: str | None
    underwritten_by_username: str | None
    committee_approved_by_username: str | None
    workflow_execution_id: uuid.UUID | None
    disbursed_at: datetime
