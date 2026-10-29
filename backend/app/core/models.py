"""Column helpers shared by all module models."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPrimaryKey:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


def trigram_index(table: str, column: str) -> Index:
    """A GIN trigram index, so `ILIKE '%text%'` searches use an index instead of reading
    the whole table (needs the pg_trgm extension, created by migration 0011)."""
    return Index(
        f"ix_{table}_{column}_trgm",
        column,
        postgresql_using="gin",
        postgresql_ops={column: "gin_trgm_ops"},
    )
