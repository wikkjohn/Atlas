import uuid
from datetime import date, datetime
from typing import Any

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
    # Servicing (Phase 10), measured on the lending business date.
    instalments_paid: int
    instalments_total: int
    next_due_date: date | None
    next_due_amount: int | None
    days_past_due: int
    arrears_amount: int = Field(description="Minor units due and unpaid")
    arrears_bucket: str
    closed_on: date | None
    written_off_by_username: str | None


class InstalmentOut(BaseModel):
    number: int
    due_date: date
    principal: int
    interest: int
    amount: int
    status: str
    paid_on: date | None


class PayoffQuote(BaseModel):
    principal: int
    accrued_interest: int
    total: int
    as_of: date


class RepaymentIn(BaseModel):
    instalments: int | None = Field(
        default=None, ge=1, description="Oldest overdue instalments to settle (default: all)"
    )


class PayoffIn(BaseModel):
    """Empty: the amount is the payoff quote at the time of the request."""


class ServicingRunIn(BaseModel):
    as_of: date = Field(description="Service everything due up to this business date")


class ServicingRunOut(BaseModel):
    id: uuid.UUID
    run_number: int
    as_of: date
    started_by_username: str | None
    summary: dict[str, Any]
    created_at: datetime
