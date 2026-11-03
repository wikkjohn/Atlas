"""Systems access (Phase 74): requested when HR hires someone, granted by Information
Security, revoked when the employee leaves. HR and Information Security never call each
other: they meet in the outbox (`app.modules.events`)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import ConflictError, NotFoundError
from app.modules.access.models import GRANT_NUMBER_SEQUENCE, AccessGrant, GrantStatus
from app.modules.employees.models import Employee
from app.modules.events import outbox

DEPARTMENT = "information_security"


def _now() -> datetime:
    return datetime.now(UTC)


def profile_for(employee: Employee) -> str:
    """The access profile an employee needs: their role's."""
    return f"role:{employee.role.code}"


def request_access(
    db: Session,
    employee: Employee,
    *,
    event_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> AccessGrant:
    """Ask for the employee's access: idempotent per event, and per live profile."""
    if event_id is not None:
        existing = db.execute(
            select(AccessGrant).where(AccessGrant.source_event_id == event_id)
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    profile = profile_for(employee)
    live = db.execute(
        select(AccessGrant).where(
            AccessGrant.employee_id == employee.id,
            AccessGrant.profile == profile,
            AccessGrant.status != GrantStatus.REVOKED,
        )
    ).scalar_one_or_none()
    if live is not None:
        return live
    number = db.execute(GRANT_NUMBER_SEQUENCE.next_value()).scalar_one()
    grant = AccessGrant(
        grant_number=f"AG-{number:07d}",
        employee_id=employee.id,
        profile=profile,
        status=GrantStatus.REQUESTED.value,
        requested_at=now or _now(),
        source_event_id=event_id,
    )
    db.add(grant)
    db.flush()
    record_audit_event(
        db,
        actor_id=None,
        action="access.requested",
        entity_type="access_grant",
        entity_id=grant.id,
        metadata={"grant_number": grant.grant_number, "profile": profile},
    )
    return grant


def get_grant(db: Session, grant_id: uuid.UUID) -> AccessGrant:
    grant = db.get(AccessGrant, grant_id)
    if grant is None:
        raise NotFoundError("No such access grant.")
    return grant


def grant_access(db: Session, grant: AccessGrant, actor_id: uuid.UUID) -> AccessGrant:
    """Information Security grants the access, and says so: `access.granted`."""
    if grant.status != GrantStatus.REQUESTED:
        raise ConflictError(f"{grant.grant_number} is {grant.status}.")
    grant.status, grant.granted_at, grant.granted_by = GrantStatus.GRANTED.value, _now(), actor_id
    db.flush()
    record_audit_event(
        db,
        actor_id=actor_id,
        action="access.granted",
        entity_type="access_grant",
        entity_id=grant.id,
        metadata={"grant_number": grant.grant_number},
    )
    outbox.publish(
        db,
        "access.granted",
        str(grant.employee_id),
        {
            "grant_id": str(grant.id),
            "grant_number": grant.grant_number,
            "employee_id": str(grant.employee_id),
            "profile": grant.profile,
        },
        publisher=DEPARTMENT,
        actor_id=actor_id,
    )
    return grant


def revoke_all(db: Session, employee_id: uuid.UUID, reason: str, actor_id: uuid.UUID | None) -> int:
    """Revoke every live grant of a leaver. Idempotent: nothing left to revoke is fine."""
    live = list(
        db.execute(
            select(AccessGrant).where(
                AccessGrant.employee_id == employee_id, AccessGrant.status != GrantStatus.REVOKED
            )
        ).scalars()
    )
    now = _now()
    for grant in live:
        grant.status, grant.revoked_at = GrantStatus.REVOKED.value, now
        grant.revoke_reason = reason[:200]
        record_audit_event(
            db,
            actor_id=actor_id,
            action="access.revoked",
            entity_type="access_grant",
            entity_id=grant.id,
            metadata={"grant_number": grant.grant_number, "reason": reason},
        )
    db.flush()
    return len(live)


def list_grants(db: Session, status: str | None = None, limit: int = 100) -> list[AccessGrant]:
    query = select(AccessGrant).order_by(AccessGrant.requested_at.desc()).limit(limit)
    if status:
        query = query.where(AccessGrant.status == status)
    return list(db.execute(query).scalars())


def counts(db: Session) -> dict[str, Any]:
    return dict(
        db.execute(select(AccessGrant.status, func.count()).group_by(AccessGrant.status)).all()
    )
