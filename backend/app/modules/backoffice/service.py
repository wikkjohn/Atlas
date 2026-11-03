"""Thin departments (Phase 61): one request lifecycle for every department's processes."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.modules.backoffice import registry
from app.modules.backoffice.models import REQUEST_SEQUENCE, DepartmentRequest, RequestStatus
from app.modules.backoffice.registry import Department, Process


def _now() -> datetime:
    return datetime.now(UTC)


def _rule(message: str, rule: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, {"rule": rule})


def _audit(db, actor_id, action: str, request: DepartmentRequest, **metadata) -> None:
    record_audit_event(db, actor_id=actor_id, action=action, entity_type="department_request",
                       entity_id=request.id, metadata={"request_number": request.request_number,
                                                      **metadata})  # fmt: skip


def spec(request: DepartmentRequest) -> tuple[Department, Process]:
    found = registry.find(request.department, request.process)
    if found is None:  # the registry dropped it; the record stays readable
        raise NotFoundError(f"No process {request.department}/{request.process}.")
    return found


def lookup(department: str, process: str) -> tuple[Department, Process]:
    found = registry.find(department, process)
    if found is None:
        raise NotFoundError(f"No process {department}/{process}.")
    return found


def submit(db: Session, department: str, process: str, *, title: str, details: str = "",
           amount: int | None, requested_by: uuid.UUID,
           now: datetime | None = None) -> DepartmentRequest:  # fmt: skip
    """Submit a request: it waits for approval by someone else, or, when the process needs
    none, is ready to complete. A process with an amount needs one; one without, none."""
    dept, proc = lookup(department, process)
    if len(title.strip()) < 5:
        raise _rule("Say what the request is for.", "title_required")
    if proc.amount_label and (amount is None or amount <= 0):
        raise _rule(f"{proc.name} needs the {proc.amount_label.lower()}.", "amount_required")
    if not proc.amount_label and amount is not None:
        raise _rule(f"{proc.name} carries no amount.", "amount_not_expected")
    now = now or _now()
    number = db.execute(REQUEST_SEQUENCE.next_value()).scalar_one()
    request = DepartmentRequest(
        request_number=f"DR-{number:07d}", department=dept.code, process=proc.code,
        title=title.strip(), details=details.strip(), amount=amount,
        status=(RequestStatus.SUBMITTED if proc.approval else RequestStatus.APPROVED).value,
        due_at=now + timedelta(hours=proc.sla_hours), requested_by=requested_by,
        created_at=now,
    )  # fmt: skip
    db.add(request)
    db.flush()
    _audit(db, requested_by, "backoffice.request_submitted", request, department=dept.code,
           process=proc.code)  # fmt: skip
    return request


def get(db: Session, request_id: uuid.UUID) -> DepartmentRequest:
    request = db.get(DepartmentRequest, request_id)
    if request is None:
        raise NotFoundError("No such request.")
    return request


def needs_executive(request: DepartmentRequest) -> bool:
    _, proc = spec(request)
    return (proc.major_above_usd is not None and request.amount is not None
            and request.amount > proc.major_above_usd * 100)  # fmt: skip


def over_budget(request: DepartmentRequest) -> bool:
    _, proc = spec(request)
    return (proc.budget_usd is not None and request.amount is not None
            and request.amount > proc.budget_usd * 100)  # fmt: skip


def decide(db: Session, request: DepartmentRequest, actor_id: uuid.UUID, approve: bool,
           executive: bool = False, note: str | None = None,
           now: datetime | None = None) -> DepartmentRequest:  # fmt: skip
    """Approve or reject a submitted request: never by the requester; above the process's
    executive threshold only by an executive."""
    if request.status != RequestStatus.SUBMITTED:
        raise ConflictError(f"{request.request_number} is {request.status}.")
    if actor_id == request.requested_by:
        raise _rule("Four-eyes rule: the requester does not decide the request.", "four_eyes")
    if approve and needs_executive(request) and not executive:
        raise _rule("An executive approves an amount this large.", "needs_executive")
    request.status = (RequestStatus.APPROVED if approve else RequestStatus.REJECTED).value
    request.decided_by, request.decided_at = actor_id, now or _now()
    request.note = (note or "").strip()[:300] or None
    db.flush()
    _audit(db, actor_id, f"backoffice.request_{request.status}", request)
    return request


def complete(db: Session, request: DepartmentRequest, actor_id: uuid.UUID,
             now: datetime | None = None) -> DepartmentRequest:  # fmt: skip
    """Complete an approved request (or one that needed no approval); late, it is marked as
    a breach of the process's target."""
    if request.status != RequestStatus.APPROVED:
        raise ConflictError(f"{request.request_number} is {request.status}.")
    now = now or _now()
    request.status, request.completed_by, request.completed_at = (
        RequestStatus.COMPLETED.value, actor_id, now)  # fmt: skip
    request.breached = now > request.due_at
    db.flush()
    _audit(db, actor_id, "backoffice.request_completed", request, breached=request.breached)
    return request


def departments(db: Session, now: datetime | None = None) -> list[dict[str, Any]]:
    """Every thin department with its processes and its requests' counts (the dashboard)."""
    now = now or _now()
    rows = db.execute(
        select(DepartmentRequest.department, DepartmentRequest.status, func.count(),
               func.count().filter(DepartmentRequest.status.in_(
                   [RequestStatus.SUBMITTED, RequestStatus.APPROVED]),
                   DepartmentRequest.due_at < now),
               func.count().filter(DepartmentRequest.breached.is_(True)))
        .group_by(DepartmentRequest.department, DepartmentRequest.status)
    ).all()  # fmt: skip
    counts: dict[str, dict[str, int]] = {}
    for dept, status, n, overdue, breached in rows:
        c = counts.setdefault(dept, {"submitted": 0, "approved": 0, "rejected": 0,
                                     "completed": 0, "overdue": 0, "breached": 0})  # fmt: skip
        c[status] = n
        c["overdue"] += overdue
        c["breached"] += breached
    return [{
        "code": d.code, "name": d.name, "description": d.description,
        "processes": [{
            "code": p.code, "name": p.name, "description": p.description,
            "approval": p.approval, "sla_hours": p.sla_hours, "amount_label": p.amount_label,
            "budget_usd": p.budget_usd, "major_above_usd": p.major_above_usd,
            "workflow_id": registry.workflow_id(d, p)} for p in d.processes],
        "counts": counts.get(d.code, {"submitted": 0, "approved": 0, "rejected": 0,
                                      "completed": 0, "overdue": 0, "breached": 0}),
    } for d in registry.DEPARTMENTS]  # fmt: skip
