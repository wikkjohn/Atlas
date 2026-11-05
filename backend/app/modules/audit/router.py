import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.audit import AuditEvent
from app.core.dependencies import DbSession
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
from app.modules.audit import archive
from app.modules.identity.dependencies import Authorized
from app.modules.identity.models import User

router = APIRouter(prefix="/audit-events", tags=["audit"])


class AuditEventOut(BaseModel):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_username: str | None
    action: str
    entity_type: str
    entity_id: str | None
    timestamp: datetime
    correlation_id: str | None
    metadata: dict[str, Any]


@router.get(
    "",
    response_model=Page[AuditEventOut],
    summary="Search the audit log (newest first). There are no write endpoints.",
)
def list_audit_events(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.AUDIT_READ),
    action: Annotated[str | None, Query(max_length=100, description="Exact or prefix*")] = None,
    entity_type: Annotated[str | None, Query(max_length=50)] = None,
    entity_id: Annotated[str | None, Query(max_length=64)] = None,
    actor_id: uuid.UUID | None = None,
    correlation_id: Annotated[str | None, Query(max_length=128)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Page[AuditEventOut]:
    query = select(AuditEvent).order_by(AuditEvent.timestamp.desc(), AuditEvent.id)
    if action:
        if action.endswith("*"):
            query = query.where(AuditEvent.action.startswith(action[:-1], autoescape=True))
        else:
            query = query.where(AuditEvent.action == action)
    if entity_type:
        query = query.where(AuditEvent.entity_type == entity_type)
    if entity_id:
        query = query.where(AuditEvent.entity_id == entity_id)
    if actor_id:
        query = query.where(AuditEvent.actor_id == actor_id)
    if correlation_id:
        query = query.where(AuditEvent.correlation_id == correlation_id)
    if since:
        query = query.where(AuditEvent.timestamp >= since)
    if until:
        query = query.where(AuditEvent.timestamp < until)

    events, total = paginate(db, query, page)
    actor_ids = {e.actor_id for e in events if e.actor_id}
    usernames = (
        dict(db.execute(select(User.id, User.username).where(User.id.in_(actor_ids))).all())
        if actor_ids
        else {}
    )
    return Page(
        items=[
            AuditEventOut(
                id=e.id,
                actor_id=e.actor_id,
                actor_username=usernames.get(e.actor_id) if e.actor_id else None,
                action=e.action,
                entity_type=e.entity_type,
                entity_id=e.entity_id,
                timestamp=e.timestamp,
                correlation_id=e.correlation_id,
                metadata=e.event_metadata,
            )
            for e in events
        ],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


# --- The audit-log archive (Phase 85) ---------------------------------------------------------

archives_router = APIRouter(prefix="/audit-archives", tags=["audit"])


class AuditArchiveOut(BaseModel):
    id: uuid.UUID
    archive_number: int
    before: datetime
    first_event_at: datetime | None
    last_event_at: datetime | None
    events: int
    location: str
    bytes: int
    sha256: str
    previous_sha256: str | None
    created_by: uuid.UUID | None
    created_at: datetime
    verified_at: datetime | None
    verification: dict[str, Any] | None

    model_config = {"from_attributes": True}


class ArchiveRequest(BaseModel):
    older_than_days: int = Field(ge=0, le=36_500)


class ArchivedEventsPage(BaseModel):
    items: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


@archives_router.get("", response_model=list[AuditArchiveOut], summary="Audit-log archives")
def list_archives(db: DbSession, _: Authorized(Permission.AUDIT_READ)) -> list[AuditArchiveOut]:
    rows = db.execute(
        select(archive.AuditArchive).order_by(archive.AuditArchive.archive_number.desc())
    ).scalars()
    return [AuditArchiveOut.model_validate(a) for a in rows]


@archives_router.post("", response_model=AuditArchiveOut | None, summary="Archive old audit events")
def create_archive(
    body: ArchiveRequest, db: DbSession, actor: Authorized(Permission.AUDIT_ARCHIVE)
) -> AuditArchiveOut | None:
    """Move every event older than `older_than_days` to a new archive file (null when none
    is that old). Events stay online for at least ATLAS_AUDIT_MIN_ONLINE_DAYS."""
    made = archive.archive_older_than(db, body.older_than_days, actor.id)
    return AuditArchiveOut.model_validate(made) if made else None


@archives_router.get("/{archive_id}", response_model=AuditArchiveOut, summary="An archive")
def get_archive(
    archive_id: uuid.UUID, db: DbSession, _: Authorized(Permission.AUDIT_READ)
) -> AuditArchiveOut:
    return AuditArchiveOut.model_validate(archive.get(db, archive_id))


@archives_router.post(
    "/{archive_id}/verify", summary="Check an archive's file and its place in the chain"
)
def verify_archive(
    archive_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.AUDIT_READ)
) -> dict[str, Any]:
    return archive.verify(db, archive.get(db, archive_id), actor.id)


@archives_router.get(
    "/{archive_id}/events", response_model=ArchivedEventsPage, summary="Search an archive"
)
def archived_events(
    archive_id: uuid.UUID,
    db: DbSession,
    _: Authorized(Permission.AUDIT_READ),
    action: Annotated[str | None, Query(max_length=100, description="Exact or prefix*")] = None,
    entity_type: Annotated[str | None, Query(max_length=50)] = None,
    entity_id: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ArchivedEventsPage:
    items, total = archive.read(
        archive.get(db, archive_id), action=action, entity_type=entity_type,
        entity_id=entity_id, limit=limit, offset=offset,
    )  # fmt: skip
    return ArchivedEventsPage(items=items, total=total, limit=limit, offset=offset)
