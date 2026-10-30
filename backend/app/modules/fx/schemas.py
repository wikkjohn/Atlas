import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RateOut(BaseModel):
    currency: str
    rate_date: date
    units_per_usd: Decimal


class RatePoint(BaseModel):
    rate_date: date
    units_per_usd: Decimal


class QuoteIn(BaseModel):
    sell_currency: str = Field(pattern=r"^[A-Z]{3}$")
    buy_currency: str = Field(pattern=r"^[A-Z]{3}$")
    sell_amount: int = Field(ge=1, le=10**15, description="Minor units of the sold currency")
    rate_date: date | None = None  # default today


class QuoteOut(BaseModel):
    sell_currency: str
    sell_amount: int
    buy_currency: str
    buy_amount: int
    mid_rate: Decimal
    customer_rate: Decimal
    margin_bps: int
    rate_date: date
    base_amount: int  # the sold amount in US cents at the mid rate


class DealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    deal_number: str
    purpose: str
    reference: str
    rate_date: date
    sell_currency: str
    sell_amount: int
    buy_currency: str
    buy_amount: int
    mid_rate: Decimal
    customer_rate: Decimal
    margin_bps: int
    base_amount: int
    sell_entry_id: uuid.UUID
    buy_entry_id: uuid.UUID
    created_at: datetime


class PositionsOut(BaseModel):
    as_of: date
    positions: list[dict[str, Any]]  # {currency, position, units_per_usd, value_usd}
    total_value_usd: int
    booked_usd: int
    unbooked_usd: int


class RevaluationIn(BaseModel):
    as_of: date | None = None  # default today


class RevaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_number: int
    as_of: date
    positions: list[dict[str, Any]]
    total_value: int
    previously_booked: int
    posted: int
    journal_entry_id: uuid.UUID | None
    created_at: datetime
