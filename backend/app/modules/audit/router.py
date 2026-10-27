import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.core.audit import AuditEvent
from app.core.dependencies import DbSession
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
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
