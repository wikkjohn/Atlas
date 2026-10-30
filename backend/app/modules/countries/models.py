from enum import StrEnum
from typing import Any

from sqlalchemy import ARRAY, CheckConstraint, ForeignKey, SmallInteger, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import Timestamps, UUIDPrimaryKey


class Region(StrEnum):
    AMERICAS = "americas"
    EUROPE = "europe"
    MIDDLE_EAST_AFRICA = "middle_east_africa"
    ASIA_PACIFIC = "asia_pacific"


class OperationalStatus(StrEnum):
    ACTIVE = "active"  # the bank operates here; organizations may be created
    PLANNED = "planned"  # configured but not yet operating
    SUSPENDED = "suspended"  # operations paused; no new organizations or staff


class Currency(Timestamps, Base):
    """ISO 4217 currencies (Phase 23): every amount is stored in its currency's minor unit."""

    __tablename__ = "currencies"
    __table_args__ = (
        CheckConstraint("code ~ '^[A-Z]{3}$'", name="code_format"),
        CheckConstraint("minor_units BETWEEN 0 AND 4", name="minor_units_range"),
    )

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    minor_units: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class Country(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "countries"
    __table_args__ = (
        CheckConstraint("iso_country_code ~ '^[A-Z]{2}$'", name="iso_country_code_format"),
        CheckConstraint("default_currency ~ '^[A-Z]{3}$'", name="default_currency_format"),
        CheckConstraint(
            "region IN ('americas', 'europe', 'middle_east_africa', 'asia_pacific')",
            name="region_valid",
        ),
        CheckConstraint(
            "operational_status IN ('active', 'planned', 'suspended')",
            name="operational_status_valid",
        ),
        CheckConstraint("iso_alpha3 ~ '^[A-Z]{3}$'", name="iso_alpha3_format"),
        CheckConstraint("calling_code ~ '^\\+[0-9]{1,4}$'", name="calling_code_format"),
        CheckConstraint("weekend_days <@ ARRAY[1,2,3,4,5,6,7]::smallint[]", name="weekend_days"),
        CheckConstraint("easter IN ('western', 'orthodox')", name="easter_valid"),
        CheckConstraint(
            "holiday_observance IN ('none', 'next_weekday', 'nearest_weekday', 'sunday_to_next')",
            name="holiday_observance_valid",
        ),
    )

    iso_country_code: Mapped[str] = mapped_column(String(2), nullable=False, unique=True)
    country_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    region: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    default_currency: Mapped[str] = mapped_column(
        String(3), ForeignKey("currencies.code"), nullable=False
    )
    default_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    supported_languages: Mapped[list[str]] = mapped_column(ARRAY(String(16)), nullable=False)
    operational_status: Mapped[str] = mapped_column(String(20), nullable=False)
    # Reference data (Phase 23), loaded from `app.modules.reference.data`.
    iso_alpha3: Mapped[str | None] = mapped_column(String(3), unique=True)
    calling_code: Mapped[str | None] = mapped_column(String(8))
    weekend_days: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger), nullable=False, server_default=text("'{6,7}'")
    )
    easter: Mapped[str] = mapped_column(String(10), nullable=False, server_default="western")
    holiday_observance: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="none"
    )
    holiday_rules: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    regulator: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # {name, abbreviation}
    # [{type: national_id | passport, name, mask, example}]
    identity_documents: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    # {style, lines, postal_code_masks, postal_code_example, requires_region}
    address_format: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reference_notes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    reference_version: Mapped[str | None] = mapped_column(String(20))

    def calendar_profile(self) -> dict[str, Any]:
        return {
            "weekend": list(self.weekend_days),
            "easter": self.easter,
            "observance": self.holiday_observance,
            "holidays": self.holiday_rules,
        }
