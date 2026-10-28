"""Append-only audit log shared by every module.

Services call `record_audit_event` inside the same transaction as the change it describes,
so a change and its audit record are committed (or rolled back) together.

Append-only is enforced twice: the application exposes no update/delete path, and a
database trigger (migration 0002) rejects UPDATE, DELETE and TRUNCATE on `audit_events`.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.database import Base
from app.core.logging import correlation_id_var

# Values of these fields are never copied into audit metadata; only the fact they changed.
SENSITIVE_FIELDS = frozenset({"password", "password_hash", "annual_compensation"})


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
        Index("ix_audit_events_timestamp", "timestamp"),
        Index("ix_audit_events_actor_id", "actor_id"),
        Index("ix_audit_events_action", "action"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # "metadata" is reserved on declarative classes, so the attribute name differs.
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )


def record_audit_event(
    db: Session,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | str | None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        correlation_id=correlation_id_var.get(),
        event_metadata=redact(metadata or {}),
    )
    db.add(event)
    db.flush()
    return event


def redact(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: ("[redacted]" if key in SENSITIVE_FIELDS else value) for key, value in values.items()
    }


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Field-level changes, with sensitive values redacted."""
    changes: dict[str, dict[str, Any]] = {}
    for key, new in after.items():
        old = before.get(key)
        if old != new:
            if key in SENSITIVE_FIELDS:
                changes[key] = {"changed": True}
            else:
                changes[key] = {"from": old, "to": new}
    return changes
