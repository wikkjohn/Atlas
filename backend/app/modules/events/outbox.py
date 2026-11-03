"""The durable event pipeline (Phase 74, roadmap Milestone F step 6).

Departments integrate through events, not imports. A department *publishes* an event in
the same transaction as the change it reports, so the event exists exactly when the change
does. Every department that *subscribes* to the event's topic gets its own delivery row,
also written in that transaction: the outbox.

Delivery is at least once and, for a subscriber that commits its own changes with the
delivery row, effectively once:

- **inline:** right after publishing, each delivery runs in its own savepoint. Success marks
  it delivered; a failure rolls back only the subscriber's work, records the error and
  schedules a retry. The publisher's own change always stands.
- **by the dispatcher:** `dispatch` (the `events.dispatch` job, every minute) claims due
  deliveries with `FOR UPDATE SKIP LOCKED`, so several workers share them, and retries each
  with exponential back-off. After `MAX_ATTEMPTS` a delivery is *dead* and waits for
  someone to retry it.

Subscribers are plain functions `(db, event) -> None`, registered with `@subscribe(topic,
name)` in the subscribing department. They must be idempotent: a delivery can repeat when
a worker dies after the work but before the commit.
"""

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.logging import correlation_id_var
from app.modules.events.models import DeliveryStatus, DomainEvent, EventDelivery

logger = logging.getLogger("atlas.events")

MAX_ATTEMPTS = 8
BACKOFF_SECONDS = 30  # doubled after each failed attempt: 30 s, 1 min, 2 min ... about 1 h
MAX_ERROR = 2_000

Handler = Callable[[Session, DomainEvent], None]


@dataclass(frozen=True)
class Subscriber:
    topic: str
    name: str
    handler: Handler
    department: str


_SUBSCRIBERS: dict[str, list[Subscriber]] = {}
_LOADED = False


def subscribe(topic: str, name: str, *, department: str) -> Callable[[Handler], Handler]:
    """Register `handler` for `topic` under a stable `name` (deliveries are keyed by it)."""

    def register(handler: Handler) -> Handler:
        subscribers = _SUBSCRIBERS.setdefault(topic, [])
        if any(s.name == name for s in subscribers):
            raise ValueError(f"Subscriber '{name}' is already registered for '{topic}'.")
        subscribers.append(Subscriber(topic, name, handler, department))
        return handler

    return register


def _load() -> None:
    """Import the subscribing modules once, so their registrations exist."""
    global _LOADED
    if not _LOADED:
        _LOADED = True
        from app.modules.events import subscriptions  # noqa: F401


def subscribers(topic: str | None = None) -> list[Subscriber]:
    _load()
    if topic is not None:
        return list(_SUBSCRIBERS.get(topic, []))
    return [s for subs in _SUBSCRIBERS.values() for s in subs]


def _now() -> datetime:
    return datetime.now(UTC)


def publish(
    db: Session,
    topic: str,
    key: str,
    payload: dict[str, Any],
    *,
    publisher: str,
    actor_id: uuid.UUID | None = None,
    deliver: bool = True,
) -> DomainEvent:
    """Record an event and a delivery to each subscriber, in the caller's transaction; then,
    unless `deliver` is False, deliver it inline (each subscriber in a savepoint)."""
    now = _now()
    event = DomainEvent(
        topic=topic,
        key=key,
        publisher=publisher,
        payload=payload,
        actor_id=actor_id,
        correlation_id=correlation_id_var.get(),
        occurred_at=now,
    )
    db.add(event)
    db.flush()
    deliveries = [
        EventDelivery(
            event_id=event.id,
            subscriber=s.name,
            status=DeliveryStatus.PENDING.value,
            attempts=0,
            next_attempt_at=now,
            created_at=now,
        )
        for s in subscribers(topic)
    ]
    db.add_all(deliveries)
    db.flush()
    if deliver:
        for delivery in deliveries:
            _attempt(db, delivery, event, now)
    return event


def last_event(db: Session, topic: str, key: str) -> DomainEvent | None:
    """The latest event on `topic` about `key`, e.g. to publish only changes."""
    return db.execute(
        select(DomainEvent)
        .where(DomainEvent.topic == topic, DomainEvent.key == key)
        .order_by(DomainEvent.seq.desc())
        .limit(1)
    ).scalar_one_or_none()


def _handler(topic: str, name: str) -> Handler | None:
    return next((s.handler for s in subscribers(topic) if s.name == name), None)


def _attempt(db: Session, delivery: EventDelivery, event: DomainEvent, now: datetime) -> bool:
    """Run one delivery in a savepoint; record the outcome. Returns whether it succeeded."""
    handler = _handler(event.topic, delivery.subscriber)
    delivery.attempts += 1
    error: str | None = None
    if handler is None:
        error = f"No subscriber '{delivery.subscriber}' is registered for '{event.topic}'."
    else:
        savepoint = db.begin_nested()
        try:
            handler(db, event)
            savepoint.commit()
        except Exception as exc:  # noqa: BLE001 - a subscriber's failure is recorded, not raised
            savepoint.rollback()
            error = f"{type(exc).__name__}: {getattr(exc, 'message', None) or exc}"
    if error is None:
        delivery.status = DeliveryStatus.DELIVERED.value
        delivery.delivered_at = now
        delivery.last_error = None
    else:
        dead = delivery.attempts >= MAX_ATTEMPTS
        delivery.status = (DeliveryStatus.DEAD if dead else DeliveryStatus.FAILED).value
        delivery.next_attempt_at = now + timedelta(
            seconds=BACKOFF_SECONDS * 2 ** (delivery.attempts - 1)
        )
        delivery.last_error = error[:MAX_ERROR]
        logger.warning(
            "event delivery failed",
            extra={
                "topic": event.topic,
                "subscriber": delivery.subscriber,
                "attempts": delivery.attempts,
                "dead": dead,
                "error": delivery.last_error,
            },
        )
    db.flush()
    return error is None


@dataclass
class DispatchReport:
    claimed: int = 0
    delivered: int = 0
    failed: int = 0
    dead: int = 0
    seconds: float = 0.0
    by_subscriber: dict[str, int] = field(default_factory=dict)


def dispatch(
    factory: sessionmaker[Session],
    *,
    limit: int = 500,
    batch: int = 100,
    now: datetime | None = None,
) -> DispatchReport:
    """Deliver what is due: pending deliveries that were not delivered inline, and failed
    ones whose back-off has passed. Deliveries are claimed `batch` at a time with
    `FOR UPDATE SKIP LOCKED`, so workers running at once take different rows; each runs in
    its own savepoint, and a batch commits together."""
    started = time.perf_counter()
    report = DispatchReport()
    while report.claimed < limit:
        with factory() as db, db.begin():
            at = now or _now()
            claimed = list(
                db.execute(
                    select(EventDelivery)
                    .where(
                        EventDelivery.status.in_([DeliveryStatus.PENDING, DeliveryStatus.FAILED]),
                        EventDelivery.next_attempt_at <= at,
                    )
                    .order_by(EventDelivery.next_attempt_at)
                    .limit(min(batch, limit - report.claimed))
                    .with_for_update(skip_locked=True)
                ).scalars()
            )
            if not claimed:
                break
            events = {
                e.id: e
                for e in db.execute(
                    select(DomainEvent).where(DomainEvent.id.in_({d.event_id for d in claimed}))
                ).scalars()
            }
            for delivery in claimed:
                report.claimed += 1
                ok = _attempt(db, delivery, events[delivery.event_id], at)
                if ok:
                    report.delivered += 1
                    report.by_subscriber[delivery.subscriber] = (
                        report.by_subscriber.get(delivery.subscriber, 0) + 1
                    )
                elif delivery.status == DeliveryStatus.DEAD:
                    report.dead += 1
                else:
                    report.failed += 1
    report.seconds = round(time.perf_counter() - started, 3)
    return report


def retry(db: Session, delivery_id: uuid.UUID) -> EventDelivery:
    """Make a failed or dead delivery due now, with its attempts reset."""
    from app.core.errors import ConflictError, NotFoundError

    delivery = db.get(EventDelivery, delivery_id)
    if delivery is None:
        raise NotFoundError("No such delivery.")
    if delivery.status == DeliveryStatus.DELIVERED:
        raise ConflictError("The delivery was already delivered.")
    delivery.status = DeliveryStatus.PENDING.value
    delivery.attempts = 0
    delivery.next_attempt_at = _now()
    db.flush()
    return delivery


def summary(db: Session) -> dict[str, Any]:
    """Deliveries by subscriber and status, events by topic, and the oldest delivery still
    waiting (how far behind the pipeline is)."""
    by_subscriber: dict[str, dict[str, int]] = {}
    for subscriber, status, n in db.execute(
        select(EventDelivery.subscriber, EventDelivery.status, func.count()).group_by(
            EventDelivery.subscriber, EventDelivery.status
        )
    ).all():
        by_subscriber.setdefault(subscriber, {})[status] = n
    topics = dict(
        db.execute(select(DomainEvent.topic, func.count()).group_by(DomainEvent.topic)).all()
    )
    oldest = db.execute(
        select(func.min(EventDelivery.created_at)).where(
            EventDelivery.status.in_(
                [DeliveryStatus.PENDING, DeliveryStatus.FAILED, DeliveryStatus.DEAD]
            )
        )
    ).scalar_one()
    return {
        "events": sum(topics.values()),
        "topics": topics,
        "subscribers": [
            {
                "topic": s.topic,
                "name": s.name,
                "department": s.department,
                "deliveries": by_subscriber.get(s.name, {}),
            }
            for s in subscribers()
        ],
        "waiting": sum(
            n
            for counts in by_subscriber.values()
            for st, n in counts.items()
            if st != DeliveryStatus.DELIVERED
        ),
        "dead": sum(c.get(DeliveryStatus.DEAD.value, 0) for c in by_subscriber.values()),
        "oldest_waiting_seconds": round((_now() - oldest).total_seconds()) if oldest else None,
    }
