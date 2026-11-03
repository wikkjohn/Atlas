"""Information Security's subscriptions: joiners get access requested, leavers lose it."""

import uuid

from sqlalchemy.orm import Session

from app.modules.access import service
from app.modules.employees.models import Employee
from app.modules.events.models import DomainEvent
from app.modules.events.outbox import subscribe


@subscribe(
    "hr.employee_hired", "information_security.request_access", department="information_security"
)
def request_joiner_access(db: Session, event: DomainEvent) -> None:
    employee = db.get(Employee, uuid.UUID(event.payload["employee_id"]))
    if employee is None:
        raise LookupError(f"Employee {event.payload['employee_id']} does not exist.")
    service.request_access(db, employee, event_id=event.id)


@subscribe(
    "hr.employee_left", "information_security.revoke_access", department="information_security"
)
def revoke_leaver_access(db: Session, event: DomainEvent) -> None:
    service.revoke_all(db, uuid.UUID(event.payload["employee_id"]), "Left the bank", event.actor_id)
