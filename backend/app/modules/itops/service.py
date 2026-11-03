"""IT operations (Phase 59): the application catalogue, incidents with response and
resolution targets, and change management."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.modules.countries.models import Country
from app.modules.itops.models import (
    APPLICATION_SEQUENCE,
    CHANGE_SEQUENCE,
    INCIDENT_SEQUENCE,
    Application,
    ChangeRequest,
    ChangeStatus,
    Incident,
    IncidentStatus,
)
from app.modules.organizations.models import Organization, OrganizationType

LEVELS = ("high", "medium", "low")
RISKS = ("low", "medium", "high")
# Hours to respond and to resolve, by priority.
TARGETS = {1: (0.25, 4), 2: (0.5, 8), 3: (4, 72), 4: (24, 120)}
FREEZE_FROM_DAY = 28  # tier-1 applications are frozen from the 28th to the 1st (month end)
KIND_RISK = {"standard": "low", "normal": "medium", "emergency": "high"}

# The default catalogue: (name, description, owning department, tier).
CATALOGUE = (
    ("Core Banking Ledger", "Accounts, balances and the general ledger", "Customer Onboarding", 1),
    ("Payments Gateway", "Domestic and cross-border payments and clearing",
     "Customer Onboarding", 1),
    ("Card Authorisation", "Real-time card authorisation and fraud blocks", "Branch Network", 1),
    ("Online Banking", "Customers' web banking", "Branch Network", 1),
    ("Loan Origination", "Applications, underwriting and offers", "Customer Onboarding", 2),
    ("AML Monitoring", "Transaction monitoring, alerts and cases",
     "Financial Crime Compliance", 2),
    ("Sanctions Screening", "Name and payment screening against the lists",
     "Financial Crime Compliance", 1),
    ("Branch Teller", "Counter services in the branches", "Branch Network", 2),
    ("Workflow Factory", "Stored workflows and their generated tests", "AI Innovation Lab", 2),
    ("AI Innovation Lab Console", "AI tool registry and test console", "AI Innovation Lab", 3),
    ("Document Archive", "Statements, letters and scanned documents", "Customer Onboarding", 3),
    ("Staff Intranet", "News, policies and the staff directory", "Branch Network", 3),
)  # fmt: skip


def _now() -> datetime:
    return datetime.now(UTC)


def _audit(db, actor_id, action: str, entity_type: str, entity_id, **metadata) -> None:
    record_audit_event(db, actor_id=actor_id, action=action, entity_type=entity_type,
                       entity_id=entity_id, metadata=metadata)  # fmt: skip


def _rule(message: str, rule: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, {"rule": rule})


# --- Applications ------------------------------------------------------------------------------


def _us_department(db: Session, name: str) -> Organization | None:
    query = (select(Organization).outerjoin(Country, Country.id == Organization.country_id)
             .where(Organization.organization_type == OrganizationType.DEPARTMENT,
                    Organization.status == "active"))  # fmt: skip
    named = db.execute(
        query.where(Organization.name == name).order_by(Country.iso_country_code != "US")
        .limit(1)
    ).scalar_one_or_none()  # fmt: skip
    return named or db.execute(query.order_by(Organization.name).limit(1)).scalar_one_or_none()


# What the core systems run on and where (Phase 63), and what they rely on.
CORE_PROFILES = {
    "Core Banking Ledger": ("cobol-mainframe", "on_premise"),
    "Payments Gateway": ("java-spring", "private_cloud"),
    "Card Authorisation": ("java-spring", "on_premise"),
    "Online Banking": ("node", "public_cloud"),
    "Loan Origination": ("java-spring", "private_cloud"),
    "AML Monitoring": ("python", "private_cloud"),
    "Sanctions Screening": ("java-spring", "private_cloud"),
    "Branch Teller": ("dotnet", "on_premise"),
    "Workflow Factory": ("python", "private_cloud"),
    "AI Innovation Lab Console": ("python", "public_cloud"),
    "Document Archive": ("oracle-plsql", "on_premise"),
    "Staff Intranet": ("saas", "saas"),
}
CORE_DEPENDENCIES = (
    ("Payments Gateway", "Core Banking Ledger", "api"),
    ("Payments Gateway", "Sanctions Screening", "api"),
    ("Card Authorisation", "Core Banking Ledger", "api"),
    ("Online Banking", "Payments Gateway", "api"),
    ("Online Banking", "Core Banking Ledger", "api"),
    ("Loan Origination", "Core Banking Ledger", "api"),
    ("Branch Teller", "Core Banking Ledger", "api"),
    ("AML Monitoring", "Payments Gateway", "data"),
    ("Workflow Factory", "Core Banking Ledger", "api"),
    ("Document Archive", "Core Banking Ledger", "batch"),
)


def ensure_applications(db: Session) -> int:
    """Create the default catalogue's missing applications (none without departments), give
    the core systems their technology and hosting where still unknown, and record their
    dependencies; returns how many applications were added."""
    from app.modules.itops.models import ApplicationDependency

    existing = {a.name: a for a in db.execute(select(Application)).scalars()}
    added = 0
    for name, description, department, tier in CATALOGUE:
        if name in existing:
            continue
        dept = _us_department(db, department)
        if dept is None:
            return added
        existing[name] = register_application(db, name=name, description=description,
                                              department_id=dept.id, tier=tier,
                                              actor_id=None)  # fmt: skip
        added += 1
    for name, (technology, hosting) in CORE_PROFILES.items():
        app = existing.get(name)
        if app is not None and app.technology == "unknown":
            app.technology, app.hosting = technology, hosting
    edges = set(db.execute(select(ApplicationDependency.application_id,
                                  ApplicationDependency.depends_on_id)).tuples())  # fmt: skip
    for name, target, kind in CORE_DEPENDENCIES:
        app, depends_on = existing.get(name), existing.get(target)
        if app and depends_on and (app.id, depends_on.id) not in edges:
            db.add(ApplicationDependency(application_id=app.id, depends_on_id=depends_on.id,
                                         kind=kind))  # fmt: skip
    db.flush()
    return added


def register_application(db: Session, *, name: str, description: str,
                         department_id: uuid.UUID, tier: int,
                         actor_id: uuid.UUID | None) -> Application:  # fmt: skip
    if tier not in (1, 2, 3):
        raise _rule("The tier is 1, 2 or 3.", "tier_invalid")
    dept = db.get(Organization, department_id)
    if dept is None or dept.organization_type != OrganizationType.DEPARTMENT:
        raise NotFoundError("No such department.")
    if db.execute(select(Application.id).where(Application.name == name.strip())).first():
        raise ConflictError(f"An application is already called {name.strip()}.")
    number = db.execute(APPLICATION_SEQUENCE.next_value()).scalar_one()
    app = Application(application_number=f"APP-{number:05d}", name=name.strip(),
                      description=description.strip(), department_id=dept.id, tier=tier,
                      status="active")  # fmt: skip
    db.add(app)
    db.flush()
    _audit(db, actor_id, "itops.application_registered", "application", app.id,
           application_number=app.application_number, tier=tier)  # fmt: skip
    return app


def find_application(db: Session, number: str) -> Application:
    app = db.execute(
        select(Application).where(Application.application_number == number.strip().upper())
    ).scalar_one_or_none()  # fmt: skip
    if app is None:
        raise NotFoundError(f"No application {number}.")
    return app


def get_application(db: Session, application_id: uuid.UUID) -> Application:
    app = db.get(Application, application_id)
    if app is None:
        raise NotFoundError("No such application.")
    return app


# --- Incidents ---------------------------------------------------------------------------------


def priority(impact: str, urgency: str) -> int:
    """P1 (high impact, high urgency) to P4 (low and low, or low and medium)."""
    if impact not in LEVELS or urgency not in LEVELS:
        raise _rule("Impact and urgency are high, medium or low.", "level_invalid")
    score = LEVELS.index(impact) + LEVELS.index(urgency)  # 0 (high, high) to 4 (low, low)
    return min(score + 1, 4)


def open_incident(db: Session, application: Application, title: str, impact: str,
                  urgency: str, reported_by: uuid.UUID | None, *, now: datetime | None = None,
                  change: ChangeRequest | None = None) -> Incident:  # fmt: skip
    """Report an incident: prioritised from its impact and urgency, with targets to respond
    and to resolve."""
    if application.status != "active":
        raise _rule(f"{application.name} is retired.", "application_retired")
    if len(title.strip()) < 5:
        raise _rule("Say what is wrong.", "title_required")
    now = now or _now()
    level = priority(impact, urgency)
    respond, resolve = TARGETS[level]
    number = db.execute(INCIDENT_SEQUENCE.next_value()).scalar_one()
    incident = Incident(
        incident_number=f"INC-{number:07d}", application_id=application.id,
        title=title.strip(), impact=impact, urgency=urgency, priority=level,
        status=IncidentStatus.OPEN.value, respond_by=now + timedelta(hours=respond),
        resolve_by=now + timedelta(hours=resolve), reported_by=reported_by,
        change_id=change.id if change else None, created_at=now,
    )  # fmt: skip
    db.add(incident)
    db.flush()
    _audit(db, reported_by, "itops.incident_opened", "incident", incident.id,
           incident_number=incident.incident_number, priority=level)  # fmt: skip
    return incident


def find_incident(db: Session, number: str) -> Incident:
    incident = db.execute(
        select(Incident).where(Incident.incident_number == number.strip().upper())
    ).scalar_one_or_none()  # fmt: skip
    if incident is None:
        raise NotFoundError(f"No incident {number}.")
    return incident


def get_incident(db: Session, incident_id: uuid.UUID) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise NotFoundError("No such incident.")
    return incident


def acknowledge(db: Session, incident: Incident, actor_id: uuid.UUID,
                now: datetime | None = None) -> Incident:  # fmt: skip
    if incident.status != IncidentStatus.OPEN:
        raise ConflictError(f"{incident.incident_number} is {incident.status}.")
    now = now or _now()
    incident.status, incident.acknowledged_at = IncidentStatus.ACKNOWLEDGED.value, now
    incident.response_breached = incident.response_breached or now > incident.respond_by
    db.flush()
    _audit(db, actor_id, "itops.incident_acknowledged", "incident", incident.id,
           incident_number=incident.incident_number)  # fmt: skip
    return incident


def resolve(db: Session, incident: Incident, resolution: str, actor_id: uuid.UUID, *,
            change: ChangeRequest | None = None,
            now: datetime | None = None) -> Incident:  # fmt: skip
    """Resolve an acknowledged incident, saying how; optionally attribute it to the change
    that caused it."""
    if incident.status != IncidentStatus.ACKNOWLEDGED:
        raise ConflictError(f"{incident.incident_number} is {incident.status}; acknowledge it "
                            "first.")  # fmt: skip
    if len(resolution.strip()) < 10:
        raise _rule("Say how it was resolved.", "resolution_required")
    if change is not None and change.application_id != incident.application_id:
        raise _rule(f"{change.change_number} changed another application.", "other_application")
    now = now or _now()
    incident.status, incident.resolved_at = IncidentStatus.RESOLVED.value, now
    incident.resolution, incident.resolved_by = resolution.strip(), actor_id
    incident.resolution_breached = incident.resolution_breached or now > incident.resolve_by
    if change is not None:
        incident.change_id = change.id
    db.flush()
    _audit(db, actor_id, "itops.incident_resolved", "incident", incident.id,
           incident_number=incident.incident_number,
           breached=incident.resolution_breached)  # fmt: skip
    return incident


def close(db: Session, incident: Incident, actor_id: uuid.UUID, review: str | None = None,
          now: datetime | None = None) -> Incident:  # fmt: skip
    """Close a resolved incident. A P1 needs a post-incident review, written by someone
    other than whoever resolved it."""
    if incident.status != IncidentStatus.RESOLVED:
        raise ConflictError(f"{incident.incident_number} is {incident.status}.")
    if incident.priority == 1:
        if not review or len(review.strip()) < 20:
            raise _rule("A P1 is closed with a post-incident review.", "review_required")
        if actor_id == incident.resolved_by:
            raise _rule("Four-eyes rule: whoever resolved a P1 does not review it.",
                        "four_eyes")  # fmt: skip
        incident.review = review.strip()
    incident.status, incident.closed_at = IncidentStatus.CLOSED.value, now or _now()
    db.flush()
    _audit(db, actor_id, "itops.incident_closed", "incident", incident.id,
           incident_number=incident.incident_number)  # fmt: skip
    return incident


def sla_sweep(db: Session, now: datetime | None = None) -> dict[str, Any]:
    """Mark incidents past their targets: not acknowledged in time, not resolved in time."""
    now = now or _now()
    response = list(db.execute(
        select(Incident).where(Incident.status == IncidentStatus.OPEN,
                               Incident.respond_by < now, Incident.response_breached.is_(False))
    ).scalars())  # fmt: skip
    resolution = list(db.execute(
        select(Incident).where(
            Incident.status.in_([IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED]),
            Incident.resolve_by < now, Incident.resolution_breached.is_(False))
    ).scalars())  # fmt: skip
    for incident in response:
        incident.response_breached = True
    for incident in resolution:
        incident.resolution_breached = True
    db.flush()
    return {"swept_at": now.isoformat(), "response_breaches": len(response),
            "resolution_breaches": len(resolution)}  # fmt: skip


# --- Changes -----------------------------------------------------------------------------------


def change_risk(kind: str, tier: int, backout_plan: str) -> str:
    """Low for a standard change, medium for a normal one, high for an emergency; a tier higher
    on a tier-1 application or without a backout plan, a tier lower on a tier-3 one."""
    level = RISKS.index(KIND_RISK[kind])
    if tier == 1:
        level += 1
    elif tier == 3:
        level -= 1
    if len(backout_plan.strip()) < 10:
        level += 1
    return RISKS[max(0, min(level, 2))]


def frozen(start: datetime, end: datetime) -> bool:
    """Whether the window touches the month-end freeze (the 28th to the 1st)."""
    day = start.date()
    while day <= end.date():
        if day.day >= FREEZE_FROM_DAY or day.day == 1:
            return True
        day += timedelta(days=1)
    return False


def _conflict(db: Session, change: ChangeRequest) -> ChangeRequest | None:
    return db.execute(
        select(ChangeRequest).where(
            ChangeRequest.application_id == change.application_id,
            ChangeRequest.id != change.id, ChangeRequest.status == ChangeStatus.APPROVED,
            ChangeRequest.planned_start < change.planned_end,
            ChangeRequest.planned_end > change.planned_start).limit(1)
    ).scalar_one_or_none()  # fmt: skip


def raise_change(db: Session, application: Application, *, title: str, kind: str,
                 backout_plan: str, planned_start: datetime, planned_end: datetime,
                 requested_by: uuid.UUID, incident: Incident | None = None,
                 now: datetime | None = None) -> ChangeRequest:  # fmt: skip
    """Raise a change. A standard change is pre-approved but must be low risk and clash with
    no approved change; others wait for approval. An emergency change answers an open P1 or
    P2 incident on the application; nothing else goes into a tier-1 application during the
    month-end freeze."""
    if kind not in KIND_RISK:
        raise _rule("The kind is standard, normal or emergency.", "kind_invalid")
    if application.status != "active":
        raise _rule(f"{application.name} is retired.", "application_retired")
    if len(title.strip()) < 5:
        raise _rule("Say what changes.", "title_required")
    now = now or _now()
    if planned_end <= planned_start:
        raise _rule("The window ends after it starts.", "window_invalid")
    if kind != "emergency" and planned_start < now:
        raise _rule("Only an emergency change is planned in the past.", "window_invalid")
    if kind == "emergency":
        if (
            incident is None
            or incident.application_id != application.id
            or incident.priority > 2
            or incident.status not in (IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED)
        ):
            raise _rule("An emergency change answers an open P1 or P2 incident on the "
                        "application.", "emergency_needs_incident")  # fmt: skip
    elif application.tier == 1 and frozen(planned_start, planned_end):
        raise _rule(f"{application.name} is frozen from the {FREEZE_FROM_DAY}th to the 1st; "
                    "only emergency changes go in.", "change_freeze")  # fmt: skip
    risk = change_risk(kind, application.tier, backout_plan)
    if kind == "standard" and risk != "low":
        raise _rule("A standard change must be low risk; raise a normal change.",
                    "not_standard")  # fmt: skip
    number = db.execute(CHANGE_SEQUENCE.next_value()).scalar_one()
    change = ChangeRequest(
        change_number=f"CHG-{number:07d}", application_id=application.id,
        title=title.strip(), kind=kind, risk=risk, backout_plan=backout_plan.strip(),
        planned_start=planned_start, planned_end=planned_end,
        incident_id=incident.id if incident else None,
        status=(ChangeStatus.APPROVED if kind == "standard" else ChangeStatus.REQUESTED).value,
        requested_by=requested_by, created_at=now,
    )  # fmt: skip
    db.add(change)
    db.flush()
    if kind == "standard" and (clash := _conflict(db, change)) is not None:
        raise _rule(f"{clash.change_number} is already approved for that window.",
                    "window_conflict")  # fmt: skip
    _audit(db, requested_by, "itops.change_raised", "change_request", change.id,
           change_number=change.change_number, risk=risk, kind=kind)  # fmt: skip
    return change


def find_change(db: Session, number: str) -> ChangeRequest:
    change = db.execute(
        select(ChangeRequest).where(ChangeRequest.change_number == number.strip().upper())
    ).scalar_one_or_none()  # fmt: skip
    if change is None:
        raise NotFoundError(f"No change {number}.")
    return change


def get_change(db: Session, change_id: uuid.UUID) -> ChangeRequest:
    change = db.get(ChangeRequest, change_id)
    if change is None:
        raise NotFoundError("No such change.")
    return change


def needs_cab(db: Session, change: ChangeRequest) -> bool:
    """A high-risk change, or any change to a tier-1 application, goes to an executive."""
    return change.risk == "high" or get_application(db, change.application_id).tier == 1


def decide_change(db: Session, change: ChangeRequest, actor_id: uuid.UUID, approve: bool,
                  executive: bool = False) -> ChangeRequest:  # fmt: skip
    """Approve or reject a change: never by whoever raised it; an executive for a high-risk
    change or a tier-1 application; never into a window another approved change holds."""
    if change.status != ChangeStatus.REQUESTED:
        raise ConflictError(f"{change.change_number} is {change.status}.")
    if actor_id == change.requested_by:
        raise _rule("Four-eyes rule: whoever raised a change does not approve it.", "four_eyes")
    if approve:
        if needs_cab(db, change) and not executive:
            raise _rule("A high-risk change, or a change to a tier-1 application, is approved "
                        "by an executive.", "needs_cab")  # fmt: skip
        if (clash := _conflict(db, change)) is not None:
            raise _rule(f"{clash.change_number} is already approved for that window.",
                        "window_conflict")  # fmt: skip
    change.status = (ChangeStatus.APPROVED if approve else ChangeStatus.REJECTED).value
    change.approved_by = actor_id if approve else None
    db.flush()
    _audit(db, actor_id, f"itops.change_{change.status}", "change_request", change.id,
           change_number=change.change_number)  # fmt: skip
    return change


def implement(db: Session, change: ChangeRequest, actor_id: uuid.UUID, success: bool,
              now: datetime | None = None) -> tuple[ChangeRequest, Incident | None]:  # fmt: skip
    """Record the change as implemented, or as failed: a failed change opens an incident
    against its application, attributed to it, more urgent the more critical the
    application."""
    if change.status != ChangeStatus.APPROVED:
        raise ConflictError(f"{change.change_number} is {change.status}.")
    now = now or _now()
    change.status = (ChangeStatus.IMPLEMENTED if success else ChangeStatus.FAILED).value
    change.implemented_at = now
    incident = None
    if not success:
        app = get_application(db, change.application_id)
        incident = open_incident(db, app, f"Failed change {change.change_number}: {change.title}"[
            :200], ("high", "medium", "low")[app.tier - 1], "high", actor_id, now=now,
            change=change)  # fmt: skip
    db.flush()
    _audit(db, actor_id, f"itops.change_{change.status}", "change_request", change.id,
           change_number=change.change_number)  # fmt: skip
    return change, incident


BUSINESS_HOURS = range(8, 18)  # UTC hours a window should avoid on tier-1 and tier-2 systems


def change_profile(db: Session, change: ChangeRequest) -> dict[str, Any]:
    """What an approver weighs before approving a change (Phase 60), as of the day it was
    raised: its kind, risk, the application's tier, the backout plan, the window's length,
    start hour and lead time, whether it falls in business hours or the freeze, the
    application's open P1 and P2 incidents, and the failed changes in the 90 days before,
    to the application and by the requester."""
    app = get_application(db, change.application_id)
    asked = change.created_at
    since = asked - timedelta(days=90)
    failed = ChangeRequest.status == ChangeStatus.FAILED

    def count(*where) -> int:
        return db.execute(
            select(func.count()).select_from(ChangeRequest)
            .where(ChangeRequest.id != change.id, ChangeRequest.created_at < asked, *where)
        ).scalar_one()  # fmt: skip

    open_major = db.execute(
        select(func.count()).select_from(Incident).where(
            Incident.application_id == app.id, Incident.priority <= 2,
            Incident.status.in_([IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED]))
    ).scalar_one()  # fmt: skip
    start, end = change.planned_start, change.planned_end
    return {
        "kind": change.kind, "risk": change.risk, "tier": app.tier,
        "has_backout_plan": len(change.backout_plan.strip()) >= 10,
        "window_hours": round((end - start).total_seconds() / 3600, 2),
        "start_hour_utc": start.hour,
        "business_hours": start.weekday() < 5 and start.hour in BUSINESS_HOURS,
        "lead_hours": round((start - asked).total_seconds() / 3600, 1),
        "in_freeze": frozen(start, end),
        "open_major_incidents": open_major,
        "app_failed_changes_90d": count(ChangeRequest.application_id == app.id, failed,
                                        ChangeRequest.created_at >= since),
        "app_changes_90d": count(ChangeRequest.application_id == app.id,
                                 ChangeRequest.created_at >= since),
        "requester_failed_changes_90d": count(ChangeRequest.requested_by == change.requested_by,
                                              failed, ChangeRequest.created_at >= since),
    }  # fmt: skip


def summary(db: Session, now: datetime | None = None) -> dict[str, Any]:
    now = now or _now()

    def count(model, *where) -> int:
        return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()

    unresolved = Incident.status.in_([IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED])
    return {
        "applications": count(Application, Application.status == "active"),
        "incidents_open": count(Incident, unresolved),
        "p1_open": count(Incident, unresolved, Incident.priority == 1),
        "incidents_breached": count(Incident, unresolved, Incident.resolve_by < now),
        "incidents_to_close": count(Incident, Incident.status == IncidentStatus.RESOLVED),
        "changes_to_approve": count(ChangeRequest, ChangeRequest.status == ChangeStatus.REQUESTED),
        "changes_scheduled": count(ChangeRequest, ChangeRequest.status == ChangeStatus.APPROVED),
        "changes_failed_30d": count(ChangeRequest, ChangeRequest.status == ChangeStatus.FAILED,
                                    ChangeRequest.implemented_at >= now - timedelta(days=30)),
        "frozen_now": frozen(now, now),
    }  # fmt: skip
