"""The record of every backup, verification, restore and drill (Phase 87)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BackupKind:
    BACKUP = "backup"
    VERIFY = "verify"
    RESTORE = "restore"
    DRILL = "drill"


class BackupRun(Base):
    __tablename__ = "backup_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_number: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), nullable=False, unique=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    ok: Mapped[bool] = mapped_column(nullable=False)
    location: Mapped[str] = mapped_column(String(500), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
