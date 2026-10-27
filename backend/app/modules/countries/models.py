from enum import StrEnum

from sqlalchemy import ARRAY, CheckConstraint, String
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
    )

    iso_country_code: Mapped[str] = mapped_column(String(2), nullable=False, unique=True)
    country_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    region: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    default_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    default_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    supported_languages: Mapped[list[str]] = mapped_column(ARRAY(String(16)), nullable=False)
    operational_status: Mapped[str] = mapped_column(String(20), nullable=False)
