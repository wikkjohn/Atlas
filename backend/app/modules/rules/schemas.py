import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.compliance.screening import SANCTIONS_LISTS


class KycRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_age: int = Field(ge=14, le=25, description="Minimum age for a retail account")
    identity_documents: list[Literal["passport", "national_id"]] = Field(min_length=1)
    proof_of_address: bool = True

    @field_validator("identity_documents")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Documents must not repeat.")
        return value


class ScreeningRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lists: list[str] = Field(min_length=1, max_length=10)

    @field_validator("lists")
    @classmethod
    def _known(cls, value: list[str]) -> list[str]:
        unknown = [v for v in value if v not in SANCTIONS_LISTS]
        if unknown:
            raise ValueError(f"Unknown sanctions lists: {', '.join(unknown)}.")
        if len(set(value)) != len(value):
            raise ValueError("Lists must not repeat.")
        return value


class PaymentRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cutoff: str = Field(
        pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$",
        description="Local time after which a payment's value date is the next business day",
    )
    high_value_major: int = Field(ge=1, le=10**12, description="Whole units of the currency")
    max_payment_major: int = Field(ge=1, le=10**13, description="Whole units of the currency")

    @model_validator(mode="after")
    def _ordered(self) -> "PaymentRules":
        if self.max_payment_major < self.high_value_major:
            raise ValueError("The payment limit must not be below the high-value threshold.")
        return self


class CountryRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kyc: KycRules
    screening: ScreeningRules
    payments: PaymentRules


class RuleVersionIn(BaseModel):
    rules: CountryRules
    effective_from: date
    note: str = Field(min_length=1, max_length=300)


class RuleVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    effective_from: date
    rules: CountryRules
    note: str
    created_by_username: str | None = None
    created_at: datetime


class CountryRulesOut(BaseModel):
    iso_country_code: str
    on: date
    current: RuleVersionOut | None  # None: no version yet; `effective` shows the defaults
    effective: CountryRules
    versions: list[RuleVersionOut]


class SanctionsListOut(BaseModel):
    list_id: str
    description: str
    entries: int
