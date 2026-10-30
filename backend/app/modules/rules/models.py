import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import UUIDPrimaryKey


class CountryRuleSet(UUIDPrimaryKey, Base):
    """One version of a country's rules. The version in force on a day is the highest one
    whose `effective_from` is on or before it; versions are never edited."""

    __tablename__ = "country_rules"
    __table_args__ = (
        UniqueConstraint("country_id", "version", name="uq_country_rules_country_version"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    country_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("countries.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    note: Mapped[str] = mapped_column(String(300), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
