"""The outbox over the API (Phase 74): what was published, who it reached, what is stuck."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.permissions import Permission
from app.modules.events import outbox
from app.modules.events.models import DomainEvent, EventDelivery
from app.modules.identity.dependencies import Authorized

router = APIRouter(prefix="/events", tags=["events"])


class DeliveryOut(BaseModel):
    id: uuid.UUID
    subscriber: str
    status: str
    attempts: int
    next_attempt_at: datetime
    last_error: str | None
    delivered_at: datetime | None


class EventOut(BaseModel):
    id: uuid.UUID
    seq: int
    topic: str
    key: str
    publisher: str
    payload: dict[str, Any]
    occurred_at: datetime
    deliveries: list[DeliveryOut]


def _out(event: DomainEvent, deliveries: list[EventDelivery]) -> EventOut:
    return EventOut(
        id=event.id,
        seq=event.seq,
        topic=event.topic,
        key=event.key,
        publisher=event.publisher,
        payload=event.payload,
        occurred_at=event.occurred_at,
        deliveries=[
            DeliveryOut(
                id=d.id,
                subscriber=d.subscriber,
                status=d.status,
                attempts=d.attempts,
                next_attempt_at=d.next_attempt_at,
                last_error=d.last_error,
                delivered_at=d.delivered_at,
            )
            for d in deliveries
        ],
    )


@router.get("", response_model=list[EventOut], summary="Recent events and their deliveries")
def list_events(
    db: DbSession,
    _: Authorized(Permission.JOBS_READ),
    topic: Annotated[str | None, Query(max_length=80)] = None,
    status: Annotated[str | None, Query(description="Only events with a delivery in it")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[EventOut]:
    query = select(DomainEvent).order_by(DomainEvent.seq.desc()).limit(limit)
    if topic:
        query = query.where(DomainEvent.topic == topic)
    if status:
        query = query.where(
            DomainEvent.id.in_(select(EventDelivery.event_id).where(EventDelivery.status == status))
        )
    events = list(db.execute(query).scalars())
    deliveries: dict[uuid.UUID, list[EventDelivery]] = {}
    if events:
        for d in db.execute(
            select(EventDelivery)
            .where(EventDelivery.event_id.in_([e.id for e in events]))
            .order_by(EventDelivery.subscriber)
        ).scalars():
            deliveries.setdefault(d.event_id, []).append(d)
    return [_out(e, deliveries.get(e.id, [])) for e in events]


@router.get("/summary", summary="Deliveries by subscriber and status; how far behind")
def events_summary(db: DbSession, _: Authorized(Permission.JOBS_READ)) -> dict[str, Any]:
    return outbox.summary(db)


@router.post(
    "/deliveries/{delivery_id}/retry",
    response_model=DeliveryOut,
    summary="Make a failed or dead delivery due now",
)
def retry_delivery(
    delivery_id: uuid.UUID, db: DbSession, _: Authorized(Permission.JOBS_MANAGE)
) -> DeliveryOut:
    d = outbox.retry(db, delivery_id)
    return DeliveryOut(
        id=d.id,
        subscriber=d.subscriber,
        status=d.status,
        attempts=d.attempts,
        next_attempt_at=d.next_attempt_at,
        last_error=d.last_error,
        delivered_at=d.delivered_at,
    )
