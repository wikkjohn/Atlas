"""HR's subscriptions: access granted by Information Security closes the joiner's
"Systems access granted" onboarding task."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.events.models import DomainEvent
from app.modules.events.outbox import subscribe
from app.modules.hr.models import OnboardingTask


@subscribe("access.granted", "hr.complete_it_access", department="hr")
def complete_it_access(db: Session, event: DomainEvent) -> None:
    task = db.execute(
        select(OnboardingTask).where(
            OnboardingTask.employee_id == uuid.UUID(event.payload["employee_id"]),
            OnboardingTask.code == "it_access",
        )
    ).scalar_one_or_none()
    if task is None or task.completed_at is not None:
        return  # no onboarding (an employee hired before HR's checklist), or already done
    task.completed_at, task.completed_by = event.occurred_at, event.actor_id
    db.flush()
