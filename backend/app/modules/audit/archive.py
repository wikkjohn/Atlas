"""The audit-log archive (Phase 85).

Audit events older than a cut-off move from `audit_events` to a compressed JSON-lines
file, one per archive, so the live table stays small while nothing is lost:

1. The events before the cut-off are written to `<audit_archive_dir>/audit-NNNNNN.jsonl.gz`
   in timestamp order, each line one event with every column.
2. The file is read back and checked: its line count and SHA-256 digest.
3. Only then, in the same transaction, are the events deleted. The append-only trigger
   permits DELETE solely while `atlas.audit_archiving = 'on'`, set here with SET LOCAL.
   UPDATE and TRUNCATE stay impossible.
4. `audit_archives` records the archive: period, events, size, digest, and the digest of
   the archive before it. The archives form a chain, so a removed, replaced or edited file
   shows when verified.

Verifying an archive re-reads its file: the digest and event count must match the record,
and its `previous_sha256` must be the digest of the archive before it. Archived events stay
searchable: each archive can be read back with the same filters as the live log.
"""

import gzip
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Uuid,
    delete,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.config import get_settings
from app.core.audit import AuditEvent, record_audit_event
from app.core.database import Base
from app.core.errors import BusinessRuleViolation, NotFoundError


class AuditArchive(Base):
    __tablename__ = "audit_archives"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    archive_number: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), nullable=False, unique=True
    )
    before: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    events: Mapped[int] = mapped_column(Integer, nullable=False)
    location: Mapped[str] = mapped_column(String(300), nullable=False)
    bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_sha256: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification: Mapped[dict | None] = mapped_column(JSONB)


def _directory() -> Path:
    path = get_settings().audit_archive_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def _line(event: AuditEvent) -> str:
    return json.dumps(
        {
            "id": str(event.id),
            "actor_id": str(event.actor_id) if event.actor_id else None,
            "action": event.action,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "timestamp": event.timestamp.isoformat(),
            "correlation_id": event.correlation_id,
            "metadata": event.event_metadata,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _digest(path: Path) -> tuple[str, int]:
    """SHA-256 of the file and its number of lines (events)."""
    sha = hashlib.sha256()
    with path.open("rb") as raw:
        for chunk in iter(lambda: raw.read(1 << 20), b""):
            sha.update(chunk)
    with gzip.open(path, "rt", encoding="utf-8") as lines:
        count = sum(1 for _ in lines)
    return sha.hexdigest(), count


def latest(db: Session) -> AuditArchive | None:
    return db.execute(
        select(AuditArchive).order_by(AuditArchive.archive_number.desc()).limit(1)
    ).scalar_one_or_none()


def archive_before(
    db: Session, before: datetime, actor_id: uuid.UUID | None, *, now: datetime | None = None
) -> AuditArchive | None:
    """Move every audit event older than `before` into a new archive; None if there is
    nothing to move. Refused for events younger than the minimum online period."""
    now = now or datetime.now(UTC)
    minimum = get_settings().audit_min_online_days
    if before > now - timedelta(days=minimum):
        raise BusinessRuleViolation(
            f"Audit events stay online for at least {minimum} days; choose a cut-off before "
            f"{(now - timedelta(days=minimum)).date().isoformat()}."
        )
    # One archive at a time: the chain must stay a chain.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('atlas.audit_archive'))"))
    events = list(
        db.execute(
            select(AuditEvent)
            .where(AuditEvent.timestamp < before)
            .order_by(AuditEvent.timestamp, AuditEvent.id)
        ).scalars()
    )
    if not events:
        return None
    previous = latest(db)
    number = (previous.archive_number + 1) if previous else 1
    path = _directory() / f"audit-{number:06d}-{uuid.uuid4().hex[:8]}.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as out:
        for event in events:
            out.write(_line(event) + "\n")
    sha, lines = _digest(path)
    if lines != len(events):
        path.unlink(missing_ok=True)
        raise RuntimeError(f"The archive holds {lines} events, not {len(events)}; nothing moved.")
    archive = AuditArchive(
        before=before, first_event_at=events[0].timestamp, last_event_at=events[-1].timestamp,
        events=len(events), location=path.name, bytes=path.stat().st_size, sha256=sha,
        previous_sha256=previous.sha256 if previous else None, created_by=actor_id,
    )  # fmt: skip
    db.add(archive)
    db.flush()
    db.execute(text("SET LOCAL atlas.audit_archiving = 'on'"))
    removed = db.execute(
        delete(AuditEvent).where(AuditEvent.id.in_([e.id for e in events]))
    ).rowcount
    db.execute(text("SET LOCAL atlas.audit_archiving = 'off'"))
    if removed != len(events):
        raise RuntimeError(f"Deleted {removed} events, archived {len(events)}; rolled back.")
    record_audit_event(
        db, actor_id=actor_id, action="audit.archived", entity_type="audit_archive",
        entity_id=archive.id,
        metadata={"archive_number": archive.archive_number, "events": len(events),
                  "before": before.isoformat(), "sha256": sha},
    )  # fmt: skip
    return archive


def archive_older_than(db: Session, days: int, actor_id: uuid.UUID | None) -> AuditArchive | None:
    now = datetime.now(UTC)
    return archive_before(db, now - timedelta(days=days), actor_id, now=now)


def get(db: Session, archive_id: uuid.UUID) -> AuditArchive:
    archive = db.get(AuditArchive, archive_id)
    if archive is None:
        raise NotFoundError("Audit archive not found.")
    return archive


def verify(db: Session, archive: AuditArchive, actor_id: uuid.UUID | None) -> dict[str, Any]:
    """Re-read the archive's file: digest, event count and its link to the archive before."""
    path = _directory() / archive.location
    problems: list[str] = []
    if not path.exists():
        problems.append("the file is missing")
        sha, lines = None, None
    else:
        sha, lines = _digest(path)
        if sha != archive.sha256:
            problems.append("the file's digest does not match the record")
        if lines != archive.events:
            problems.append(f"the file holds {lines} events, the record says {archive.events}")
    before = db.execute(
        select(AuditArchive).where(AuditArchive.archive_number < archive.archive_number)
        .order_by(AuditArchive.archive_number.desc()).limit(1)
    ).scalar_one_or_none()  # fmt: skip
    expected_previous = before.sha256 if before else None
    if archive.previous_sha256 != expected_previous:
        problems.append("the chain is broken: the previous archive's digest differs")
    result = {"ok": not problems, "problems": problems, "sha256": sha, "events": lines}
    archive.verified_at = datetime.now(UTC)
    archive.verification = result
    record_audit_event(
        db, actor_id=actor_id, action="audit.archive_verified", entity_type="audit_archive",
        entity_id=archive.id, metadata=result,
    )  # fmt: skip
    return result


def read(
    archive: AuditArchive, *, action: str | None = None, entity_type: str | None = None,
    entity_id: str | None = None, limit: int = 100, offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:  # fmt: skip
    """The archive's events (oldest first) with the live log's filters."""
    path = _directory() / archive.location
    if not path.exists():
        raise NotFoundError("The archive's file is missing.")
    matches: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as lines:
        for line in lines:
            event = json.loads(line)
            if action and not (
                event["action"].startswith(action[:-1]) if action.endswith("*")
                else event["action"] == action
            ):  # fmt: skip
                continue
            if entity_type and event["entity_type"] != entity_type:
                continue
            if entity_id and event["entity_id"] != entity_id:
                continue
            matches.append(event)
    return matches[offset : offset + limit], len(matches)
