import re
import uuid
import zoneinfo
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.countries.models import OperationalStatus, Region

LANGUAGE_PATTERN = r"^[a-z]{2,3}(-[A-Z]{2})?$"


def _valid_timezone(value: str) -> str:
    try:
        zoneinfo.ZoneInfo(value)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"'{value}' is not an IANA time zone (e.g. 'Europe/London').") from exc
    return value


def _valid_languages(value: list[str]) -> list[str]:
    for code in value:
        if not re.fullmatch(LANGUAGE_PATTERN, code):
            raise ValueError(f"'{code}' is not a language tag such as 'en' or 'en-GB'.")
    if len(set(value)) != len(value):
        raise ValueError("Languages must not repeat.")
    return value


class CountryBase(BaseModel):
    country_name: str = Field(min_length=2, max_length=100)
    default_timezone: str = Field(max_length=64)
    supported_languages: list[str] = Field(min_length=1, max_length=20)
    operational_status: OperationalStatus = OperationalStatus.PLANNED

    @field_validator("default_timezone")
    @classmethod
    def _timezone(cls, value: str) -> str:
        return _valid_timezone(value)

    @field_validator("supported_languages")
    @classmethod
    def _languages(cls, value: list[str]) -> list[str]:
        return _valid_languages(value)


class CountryCreate(CountryBase):
    iso_country_code: str = Field(pattern=r"^[A-Z]{2}$", description="ISO 3166-1 alpha-2")
    region: Region
    default_currency: str = Field(pattern=r"^[A-Z]{3}$", description="ISO 4217 code")

    @field_validator("iso_country_code", "default_currency", mode="before")
    @classmethod
    def _upper(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class CountryUpdate(BaseModel):
    """Code, region and currency are fixed once created; records elsewhere depend on them."""

    country_name: str | None = Field(default=None, min_length=2, max_length=100)
    default_timezone: str | None = Field(default=None, max_length=64)
    supported_languages: list[str] | None = Field(default=None, min_length=1, max_length=20)
    operational_status: OperationalStatus | None = None

    @field_validator("default_timezone")
    @classmethod
    def _timezone(cls, value: str | None) -> str | None:
        return None if value is None else _valid_timezone(value)

    @field_validator("supported_languages")
    @classmethod
    def _languages(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _valid_languages(value)


class CountryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    iso_country_code: str
    country_name: str
    region: str
    default_currency: str
    default_timezone: str
    supported_languages: list[str]
    operational_status: str
    created_at: datetime
    updated_at: datetime
