import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.modules.customers.models import CustomerType, KycStatus, RiskRating


class CustomerCreate(BaseModel):
    customer_type: CustomerType
    name: str = Field(min_length=2, max_length=200)
    date_of_birth_or_incorporation: date
    country_id: uuid.UUID


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)


class CustomerReview(BaseModel):
    """A KYC decision and/or risk rating, made by a reviewer."""

    kyc_status: KycStatus | None = None
    risk_rating: RiskRating | None = None
    note: str | None = Field(default=None, max_length=500)


class CustomerOut(BaseModel):
    id: uuid.UUID
    customer_number: str
    customer_type: str
    name: str
    date_of_birth_or_incorporation: date
    country_id: uuid.UUID
    country_code: str
    currency: str
    risk_rating: str
    kyc_status: str
    created_at: datetime
    updated_at: datetime
    segment: str | None = None  # the customer generator's segment (Phase 72)


class PopulationGenerate(BaseModel):
    """A customer-generator run through the API (Phase 72); larger runs use the CLI."""

    count: int = Field(ge=1, le=50_000)
    seed: int = 2030
    history_months: int = Field(default=3, ge=0, le=24)
