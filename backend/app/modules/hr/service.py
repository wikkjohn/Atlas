"""Human resources (Phase 55): requisitions and hiring, onboarding, leave, shifts and the
staffing capacity simulations draw on."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.permissions import SERVICE_ROLES, RoleCode
from app.modules.employees.models import Employee, EmploymentStatus
from app.modules.hr.models import (
    CANDIDATE_SEQUENCE,
    LEAVE_SEQUENCE,
    REQUISITION_SEQUENCE,
    SHIFT_SEQUENCE,
    Candidate,
    CandidateStatus,
    JobRequisition,
    LeaveKind,
    LeaveRequest,
    LeaveStatus,
    OnboardingTask,
    RequisitionStatus,
    Shift,
    ShiftAssignment,
)
from app.modules.identity.models import Role
from app.modules.organizations.models import Organization, OrganizationType
from app.modules.reference import calendar

ANNUAL_ENTITLEMENT_DAYS = 25  # business days a calendar year
MAX_WEEKLY_HOURS = 48
MIN_REST_HOURS = 11
# Onboarding checklist: code, title, business-agnostic days after the start date.
ONBOARDING = (
    ("contract", "Signed contract on file", 0),
    ("it_access", "Systems access granted", 0),
    ("induction", "Induction completed", 7),
    ("compliance_training", "Compliance training completed", 30),
    ("probation_review", "Probation review held", 90),
)
# Simulated staff roles and the employee roles that fill them.
STAFF_ROLE = {
    RoleCode.BANKING_EMPLOYEE.value: "teller",
    RoleCode.DEPARTMENT_MANAGER.value: "manager",
    RoleCode.COMPLIANCE_OFFICER.value: "compliance",
    RoleCode.REGIONAL_EXECUTIVE.value: "executive",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _audit(db, actor_id, action: str, entity_type: str, entity_id, **metadata) -> None:
    record_audit_event(db, actor_id=actor_id, action=action, entity_type=entity_type,
                       entity_id=entity_id, metadata=metadata)  # fmt: skip


def _four_eyes(by: uuid.UUID | None, actor_id: uuid.UUID, who: str) -> None:
    if by == actor_id:
        raise BusinessRuleViolation(f"Four-eyes rule: the person who {who} it cannot decide it.",
                                    {"rule": "four_eyes"})  # fmt: skip


# --- Departments and people -------------------------------------------------------------------


def department(db: Session, department_id: uuid.UUID) -> Organization:
    org = db.get(Organization, department_id)
    if org is None or org.organization_type != OrganizationType.DEPARTMENT:
        raise NotFoundError("No such department.")
    return org


def departments(db: Session) -> list[dict[str, Any]]:
    """Every active department with its headcount (employees not terminated)."""
    counts = dict(db.execute(
        select(Employee.department_id, func.count()).where(
            Employee.employment_status != EmploymentStatus.TERMINATED)
        .group_by(Employee.department_id)
    ).all())  # fmt: skip
    rows = db.execute(
        select(Organization).where(Organization.organization_type == OrganizationType.DEPARTMENT,
                                   Organization.status == "active")
        .order_by(Organization.name)
    ).scalars()  # fmt: skip
    return [{"id": d.id, "name": d.name, "headcount": counts.get(d.id, 0),
             "country": d.country.iso_country_code if d.country else None,
             "currency": d.country.default_currency if d.country else None}
            for d in rows]  # fmt: skip


def find_employee(db: Session, number: str) -> Employee:
    employee = db.execute(
        select(Employee).where(Employee.employee_number == number.strip().upper())
    ).scalar_one_or_none()  # fmt: skip
    if employee is None:
        raise NotFoundError(f"No employee {number}.")
    return employee


def _currency(db: Session, org: Organization) -> str:
    if org.country is None:
        raise BusinessRuleViolation(f"{org.name} has no country.")
    return org.country.default_currency


# --- Requisitions and hiring ------------------------------------------------------------------


def open_requisition(db: Session, dept: Organization, *, job_title: str, role: str,
                     openings: int, salary_min: int, salary_max: int, reason: str,
                     requested_by: uuid.UUID) -> JobRequisition:  # fmt: skip
    """Ask to hire: it waits for someone other than the requester (hr:approve)."""
    if role not in {r.value for r in RoleCode} or RoleCode(role) in SERVICE_ROLES:
        raise BusinessRuleViolation(f"{role} is not a role people are hired into.",
                                    {"rule": "role_invalid"})  # fmt: skip
    if not 1 <= openings <= 50:
        raise BusinessRuleViolation("A requisition has 1 to 50 openings.",
                                    {"rule": "openings_range"})  # fmt: skip
    if salary_min <= 0 or salary_max < salary_min:
        raise BusinessRuleViolation("The salary band needs a positive minimum no larger than "
                                    "its maximum.", {"rule": "band_invalid"})  # fmt: skip
    if len(reason.strip()) < 10:
        raise BusinessRuleViolation("Explain why the department needs the hire.",
                                    {"rule": "reason_required"})  # fmt: skip
    number = db.execute(REQUISITION_SEQUENCE.next_value()).scalar_one()
    row = JobRequisition(
        requisition_number=f"REQ-{number:07d}", department_id=dept.id,
        job_title=job_title.strip(), role=role, openings=openings, filled=0,
        salary_min=salary_min, salary_max=salary_max, currency=_currency(db, dept),
        reason=reason.strip(), status=RequisitionStatus.OPEN.value, requested_by=requested_by,
    )  # fmt: skip
    db.add(row)
    db.flush()
    _audit(db, requested_by, "hr.requisition_opened", "job_requisition", row.id,
           requisition_number=row.requisition_number, department=dept.name)  # fmt: skip
    return row


def get_requisition(db: Session, requisition_id: uuid.UUID) -> JobRequisition:
    row = db.get(JobRequisition, requisition_id)
    if row is None:
        raise NotFoundError("No such requisition.")
    return row


def decide_requisition(db: Session, row: JobRequisition, actor_id: uuid.UUID,
                       approve: bool) -> JobRequisition:  # fmt: skip
    if row.status != RequisitionStatus.OPEN:
        raise ConflictError(f"{row.requisition_number} is {row.status}.")
    _four_eyes(row.requested_by, actor_id, "requested")
    row.status = (RequisitionStatus.APPROVED if approve else RequisitionStatus.CANCELLED).value
    row.approved_by = actor_id if approve else None
    row.decided_at = _now()
    db.flush()
    _audit(db, actor_id, f"hr.requisition_{row.status}", "job_requisition", row.id,
           requisition_number=row.requisition_number)  # fmt: skip
    return row


def add_candidate(db: Session, row: JobRequisition, first_name: str, last_name: str
                  ) -> Candidate:  # fmt: skip
    if row.status != RequisitionStatus.APPROVED:
        raise BusinessRuleViolation(f"{row.requisition_number} is {row.status}; candidates "
                                    "apply to an approved requisition.",
                                    {"rule": "not_recruiting"})  # fmt: skip
    number = db.execute(CANDIDATE_SEQUENCE.next_value()).scalar_one()
    candidate = Candidate(candidate_number=f"CAN-{number:07d}", requisition_id=row.id,
                          first_name=first_name.strip(), last_name=last_name.strip(),
                          status=CandidateStatus.APPLIED.value)  # fmt: skip
    db.add(candidate)
    db.flush()
    return candidate


def get_candidate(db: Session, candidate_id: uuid.UUID) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise NotFoundError("No such candidate.")
    return candidate


def make_offer(db: Session, candidate: Candidate, salary: int, start: date,
               offered_by: uuid.UUID, today: date | None = None) -> Candidate:  # fmt: skip
    """Offer a salary inside the requisition's band, starting today or later."""
    row = get_requisition(db, candidate.requisition_id)
    if candidate.status != CandidateStatus.APPLIED:
        raise ConflictError(f"{candidate.candidate_number} is {candidate.status}.")
    if row.status != RequisitionStatus.APPROVED:
        raise BusinessRuleViolation(f"{row.requisition_number} is {row.status}.",
                                    {"rule": "not_recruiting"})  # fmt: skip
    if not row.salary_min <= salary <= row.salary_max:
        raise BusinessRuleViolation(
            f"The offer must fall within the band, {row.salary_min} to {row.salary_max} minor "
            f"units of {row.currency}.", {"rule": "offer_outside_band"})  # fmt: skip
    if start < (today or _now().date()):
        raise BusinessRuleViolation("The start date cannot be in the past.",
                                    {"rule": "start_in_past"})  # fmt: skip
    candidate.status, candidate.offered_salary = CandidateStatus.OFFERED.value, salary
    candidate.start_date, candidate.offered_by = start, offered_by
    db.flush()
    return candidate


def decline(db: Session, candidate: Candidate, by_candidate: bool) -> Candidate:
    """The candidate declines the offer, or the bank turns the application down."""
    if candidate.status not in (CandidateStatus.APPLIED, CandidateStatus.OFFERED):
        raise ConflictError(f"{candidate.candidate_number} is {candidate.status}.")
    candidate.status = (CandidateStatus.DECLINED if by_candidate else
                        CandidateStatus.REJECTED).value  # fmt: skip
    db.flush()
    return candidate


def hire(db: Session, candidate: Candidate, actor_id: uuid.UUID) -> Employee:
    """The candidate accepted: hire them into the department, at the offered salary, and
    start their onboarding checklist. The requisition is filled when its last opening is."""
    from app.modules.employees.schemas import EmployeeCreate
    from app.modules.employees.service import create_employee

    if candidate.status != CandidateStatus.OFFERED:
        raise ConflictError(f"{candidate.candidate_number} has no open offer.")
    row = get_requisition(db, candidate.requisition_id)
    if row.status != RequisitionStatus.APPROVED or row.filled >= row.openings:
        raise BusinessRuleViolation(f"{row.requisition_number} has no opening left.",
                                    {"rule": "no_opening"})  # fmt: skip
    dept = department(db, row.department_id)
    manager = db.execute(
        select(Employee.id).join(Role, Role.id == Employee.role_id)
        .where(Employee.department_id == dept.id, Role.code == RoleCode.DEPARTMENT_MANAGER,
               Employee.employment_status != EmploymentStatus.TERMINATED)
        .order_by(Employee.employee_number).limit(1)
    ).scalar_one_or_none()  # fmt: skip
    employee = create_employee(db, EmployeeCreate(
        first_name=candidate.first_name, last_name=candidate.last_name,
        organization_id=dept.id, manager_id=manager, job_title=row.job_title,
        role=RoleCode(row.role), annual_compensation=candidate.offered_salary,
    ), actor_id)  # fmt: skip
    candidate.status, candidate.employee_id = CandidateStatus.HIRED.value, employee.id
    row.filled += 1
    if row.filled >= row.openings:
        row.status = RequisitionStatus.FILLED.value
    start = candidate.start_date or _now().date()
    for code, title, days in ONBOARDING:
        db.add(OnboardingTask(employee_id=employee.id, code=code, title=title,
                              due=start + timedelta(days=days)))  # fmt: skip
    db.flush()
    _audit(db, actor_id, "hr.hired", "candidate", candidate.id,
           candidate_number=candidate.candidate_number,
           employee_number=employee.employee_number,
           requisition_number=row.requisition_number)  # fmt: skip
    return employee


def onboarding(db: Session, employee_id: uuid.UUID | None = None, open_only: bool = False
               ) -> list[OnboardingTask]:  # fmt: skip
    query = select(OnboardingTask).order_by(OnboardingTask.due, OnboardingTask.code)
    if employee_id is not None:
        query = query.where(OnboardingTask.employee_id == employee_id)
    if open_only:
        query = query.where(OnboardingTask.completed_at.is_(None))
    return list(db.execute(query.limit(200)).scalars())


def complete_task(db: Session, task_id: uuid.UUID, actor_id: uuid.UUID) -> OnboardingTask:
    task = db.get(OnboardingTask, task_id)
    if task is None:
        raise NotFoundError("No such onboarding task.")
    if task.completed_at is not None:
        raise ConflictError("The task is already complete.")
    task.completed_at, task.completed_by = _now(), actor_id
    db.flush()
    return task


# --- Leave -------------------------------------------------------------------------------------


def business_days(employee: Employee, start: date, end: date) -> int:
    """Days from start to end inclusive that are business days in the employee's country."""
    profile = employee.country.calendar_profile()
    days, day = 0, start
    while day <= end:
        days += calendar.is_business_day(profile, day)
        day += timedelta(days=1)
    return days


def leave_used(db: Session, employee_id: uuid.UUID, year: int,
               exclude: uuid.UUID | None = None) -> int:  # fmt: skip
    """Annual leave days approved or awaiting a decision, by start date's year."""
    query = select(func.coalesce(func.sum(LeaveRequest.days), 0)).where(
        LeaveRequest.employee_id == employee_id, LeaveRequest.kind == LeaveKind.ANNUAL,
        LeaveRequest.status.in_([LeaveStatus.REQUESTED, LeaveStatus.APPROVED]),
        func.extract("year", LeaveRequest.start_date) == year)  # fmt: skip
    if exclude is not None:
        query = query.where(LeaveRequest.id != exclude)
    return int(db.execute(query).scalar_one())


def request_leave(db: Session, employee: Employee, kind: str, start: date, end: date,
                  requested_by: uuid.UUID, note: str = "") -> LeaveRequest:  # fmt: skip
    """Ask for leave; decided by someone other than the requester. Annual leave counts
    against the year's entitlement; no request may overlap another awaiting or approved."""
    if employee.employment_status == EmploymentStatus.TERMINATED:
        raise BusinessRuleViolation(f"{employee.employee_number} has left the bank.",
                                    {"rule": "terminated"})  # fmt: skip
    if kind not in set(LeaveKind):
        raise BusinessRuleViolation("Leave is annual, sick or unpaid.", {"rule": "kind_invalid"})
    if end < start:
        raise BusinessRuleViolation("The leave ends before it starts.", {"rule": "dates_invalid"})
    if end.year != start.year:
        raise BusinessRuleViolation("Split leave that spans two years at the year end.",
                                    {"rule": "spans_years"})  # fmt: skip
    days = business_days(employee, start, end)
    if days == 0:
        raise BusinessRuleViolation("There are no working days in that period.",
                                    {"rule": "no_working_days"})  # fmt: skip
    overlap = db.execute(
        select(LeaveRequest.leave_number).where(
            LeaveRequest.employee_id == employee.id,
            LeaveRequest.status.in_([LeaveStatus.REQUESTED, LeaveStatus.APPROVED]),
            LeaveRequest.start_date <= end, LeaveRequest.end_date >= start).limit(1)
    ).scalar_one_or_none()  # fmt: skip
    if overlap:
        raise BusinessRuleViolation(f"It overlaps {overlap}.", {"rule": "overlap"})
    if kind == LeaveKind.ANNUAL:
        left = ANNUAL_ENTITLEMENT_DAYS - leave_used(db, employee.id, start.year)
        if days > left:
            raise BusinessRuleViolation(
                f"{days} days requested; {left} of the year's {ANNUAL_ENTITLEMENT_DAYS} remain.",
                {"rule": "insufficient_balance", "remaining": left})  # fmt: skip
    number = db.execute(LEAVE_SEQUENCE.next_value()).scalar_one()
    leave = LeaveRequest(leave_number=f"LV-{number:07d}", employee_id=employee.id, kind=kind,
                         start_date=start, end_date=end, days=days,
                         status=LeaveStatus.REQUESTED.value, note=note.strip() or None,
                         requested_by=requested_by)  # fmt: skip
    db.add(leave)
    db.flush()
    _audit(db, requested_by, "hr.leave_requested", "leave_request", leave.id,
           leave_number=leave.leave_number, days=days, kind=kind)  # fmt: skip
    return leave


def get_leave(db: Session, leave_id: uuid.UUID) -> LeaveRequest:
    leave = db.get(LeaveRequest, leave_id)
    if leave is None:
        raise NotFoundError("No such leave request.")
    return leave


def decide_leave(db: Session, leave: LeaveRequest, actor_id: uuid.UUID, approve: bool,
                 note: str = "") -> LeaveRequest:  # fmt: skip
    if leave.status != LeaveStatus.REQUESTED:
        raise ConflictError(f"{leave.leave_number} is {leave.status}.")
    _four_eyes(leave.requested_by, actor_id, "requested")
    leave.status = (LeaveStatus.APPROVED if approve else LeaveStatus.REJECTED).value
    leave.decided_by, leave.decided_at = actor_id, _now()
    if note.strip():
        leave.note = note.strip()
    db.flush()
    _audit(db, actor_id, f"hr.leave_{leave.status}", "leave_request", leave.id,
           leave_number=leave.leave_number)  # fmt: skip
    return leave


def cancel_leave(db: Session, leave: LeaveRequest, actor_id: uuid.UUID) -> LeaveRequest:
    if leave.status not in (LeaveStatus.REQUESTED, LeaveStatus.APPROVED):
        raise ConflictError(f"{leave.leave_number} is {leave.status}.")
    leave.status = LeaveStatus.CANCELLED.value
    db.flush()
    _audit(db, actor_id, "hr.leave_cancelled", "leave_request", leave.id,
           leave_number=leave.leave_number)  # fmt: skip
    return leave


def on_leave_ids(db: Session, on: date, department_id: uuid.UUID | None = None
                 ) -> set[uuid.UUID]:  # fmt: skip
    query = select(LeaveRequest.employee_id).where(
        LeaveRequest.status == LeaveStatus.APPROVED,
        LeaveRequest.start_date <= on, LeaveRequest.end_date >= on)  # fmt: skip
    if department_id is not None:
        query = query.join(Employee, Employee.id == LeaveRequest.employee_id).where(
            Employee.department_id == department_id
        )
    return set(db.execute(query).scalars())


def leave_sweep(db: Session, on: date | None = None) -> dict[str, Any]:
    """Employees on approved leave today are on leave; those whose leave has ended are
    active again. Nobody terminated is touched."""
    on = on or _now().date()
    db.flush()
    # Set-based (Phase 69): with 150,000 employees, loading each one took minutes.
    away = (select(LeaveRequest.employee_id).where(
        LeaveRequest.status == LeaveStatus.APPROVED,
        LeaveRequest.start_date <= on, LeaveRequest.end_date >= on))  # fmt: skip
    started = db.execute(update(Employee).where(
        Employee.employment_status == EmploymentStatus.ACTIVE, Employee.id.in_(away))
        .values(employment_status=EmploymentStatus.ON_LEAVE.value)
        .execution_options(synchronize_session="fetch")).rowcount  # fmt: skip
    ended = db.execute(update(Employee).where(
        Employee.employment_status == EmploymentStatus.ON_LEAVE, Employee.id.not_in(away))
        .values(employment_status=EmploymentStatus.ACTIVE.value)
        .execution_options(synchronize_session="fetch")).rowcount  # fmt: skip
    away = on_leave_ids(db, on)
    return {"swept_on": on.isoformat(), "on_leave": len(away), "started": started,
            "ended": ended}  # fmt: skip


# --- Shifts ------------------------------------------------------------------------------------


def create_shift(db: Session, dept: Organization, on: date, start_hour: int, hours: int,
                 required: int, created_by: uuid.UUID | None) -> Shift:  # fmt: skip
    if not 0 <= start_hour <= 23 or not 1 <= hours <= 12 or not 1 <= required <= 100:
        raise BusinessRuleViolation(
            "A shift starts at hour 0 to 23, lasts 1 to 12 hours and needs 1 to 100 people.",
            {"rule": "shift_invalid"})  # fmt: skip
    number = db.execute(SHIFT_SEQUENCE.next_value()).scalar_one()
    shift = Shift(shift_number=f"SHF-{number:07d}", department_id=dept.id, on=on,
                  start_hour=start_hour, hours=hours, required=required,
                  created_by=created_by)  # fmt: skip
    db.add(shift)
    db.flush()
    return shift


def get_shift(db: Session, shift_id: uuid.UUID) -> Shift:
    shift = db.get(Shift, shift_id)
    if shift is None:
        raise NotFoundError("No such shift.")
    return shift


def _window(shift: Shift) -> tuple[datetime, datetime]:
    start = datetime.combine(shift.on, datetime.min.time()) + timedelta(hours=shift.start_hour)
    return start, start + timedelta(hours=shift.hours)


def _shifts_of(db: Session, employee_id: uuid.UUID, start: date, end: date) -> list[Shift]:
    return list(db.execute(
        select(Shift).join(ShiftAssignment, ShiftAssignment.shift_id == Shift.id)
        .where(ShiftAssignment.employee_id == employee_id, Shift.on >= start, Shift.on <= end)
    ).scalars())  # fmt: skip


def assign(db: Session, shift: Shift, employee: Employee, assigned_by: uuid.UUID | None
           ) -> ShiftAssignment:  # fmt: skip
    """Roster an employee: same department, working, not on leave that day, not on another
    shift at the same time, within 48 hours that week and with 11 hours' rest between."""
    if employee.department_id != shift.department_id:
        raise BusinessRuleViolation(f"{employee.employee_number} works in another department.",
                                    {"rule": "other_department"})  # fmt: skip
    if employee.employment_status == EmploymentStatus.TERMINATED:
        raise BusinessRuleViolation(f"{employee.employee_number} has left the bank.",
                                    {"rule": "terminated"})  # fmt: skip
    if employee.id in on_leave_ids(db, shift.on, shift.department_id):
        raise BusinessRuleViolation(f"{employee.employee_number} is on leave that day.",
                                    {"rule": "on_leave"})  # fmt: skip
    taken = db.execute(
        select(func.count()).select_from(ShiftAssignment)
        .where(ShiftAssignment.shift_id == shift.id)
    ).scalar_one()  # fmt: skip
    if taken >= shift.required:
        raise BusinessRuleViolation(f"{shift.shift_number} is fully staffed.",
                                    {"rule": "shift_full"})  # fmt: skip
    start, end = _window(shift)
    monday = shift.on - timedelta(days=shift.on.weekday())
    week = _shifts_of(db, employee.id, monday, monday + timedelta(days=6))
    if any(s.id == shift.id for s in week):
        raise ConflictError(f"{employee.employee_number} is already on {shift.shift_number}.")
    if sum(s.hours for s in week) + shift.hours > MAX_WEEKLY_HOURS:
        raise BusinessRuleViolation(
            f"{employee.employee_number} would work more than {MAX_WEEKLY_HOURS} hours that week.",
            {"rule": "weekly_hours"})  # fmt: skip
    for other in _shifts_of(db, employee.id, shift.on - timedelta(days=1),
                            shift.on + timedelta(days=1)):  # fmt: skip
        o_start, o_end = _window(other)
        if o_start < end and start < o_end:
            raise BusinessRuleViolation(
                f"{employee.employee_number} is on {other.shift_number} at the same time.",
                {"rule": "double_booked"})  # fmt: skip
        gap = (start - o_end) if o_end <= start else (o_start - end)
        if gap < timedelta(hours=MIN_REST_HOURS):
            raise BusinessRuleViolation(
                f"{employee.employee_number} needs {MIN_REST_HOURS} hours' rest after "
                f"{other.shift_number}.", {"rule": "rest_period"})  # fmt: skip
    row = ShiftAssignment(shift_id=shift.id, employee_id=employee.id, assigned_by=assigned_by)
    db.add(row)
    db.flush()
    return row


def roster(db: Session, shift: Shift) -> list[Employee]:
    return list(db.execute(
        select(Employee).join(ShiftAssignment, ShiftAssignment.employee_id == Employee.id)
        .where(ShiftAssignment.shift_id == shift.id).order_by(Employee.employee_number)
    ).scalars())  # fmt: skip


def unassign(db: Session, shift: Shift, employee: Employee) -> None:
    row = db.execute(
        select(ShiftAssignment).where(ShiftAssignment.shift_id == shift.id,
                                      ShiftAssignment.employee_id == employee.id)
    ).scalar_one_or_none()  # fmt: skip
    if row is None:
        raise NotFoundError(f"{employee.employee_number} is not on {shift.shift_number}.")
    db.delete(row)
    db.flush()


# --- Capacity ----------------------------------------------------------------------------------


def capacity(db: Session, department_id: uuid.UUID, on: date) -> dict[str, Any]:
    """Who can work in the department that day: its staff not terminated, less those on
    approved leave; when shifts are rostered that day, only the rostered staff count. By
    simulated role (teller, manager, compliance, executive) too."""
    dept = department(db, department_id)
    staff = list(db.execute(
        select(Employee).where(Employee.department_id == dept.id,
                               Employee.employment_status != EmploymentStatus.TERMINATED)
    ).scalars())  # fmt: skip
    away = on_leave_ids(db, on, dept.id)
    rostered = set(db.execute(
        select(ShiftAssignment.employee_id).join(Shift, Shift.id == ShiftAssignment.shift_id)
        .where(Shift.department_id == dept.id, Shift.on == on)
    ).scalars())  # fmt: skip
    shifts = db.execute(
        select(func.count()).select_from(Shift).where(Shift.department_id == dept.id,
                                                      Shift.on == on)
    ).scalar_one()  # fmt: skip
    working = [e for e in staff if e.id not in away and (not shifts or e.id in rostered)]
    by_role: dict[str, int] = {}
    for e in working:
        role = STAFF_ROLE.get(e.role.code)
        if role:
            by_role[role] = by_role.get(role, 0) + 1
    return {"department_id": str(dept.id), "department": dept.name, "on": on.isoformat(),
            "headcount": len(staff), "on_leave": len(away & {e.id for e in staff}),
            "shifts": shifts, "rostered": len(rostered), "available": len(working),
            "available_by_role": by_role}  # fmt: skip


SHORT_NOTICE_DAYS = 7  # leave asked for less than a week ahead


def leave_profile(db: Session, leave: LeaveRequest) -> dict[str, Any]:
    """What a manager weighs before approving leave (Phase 56), as of the day it was asked
    for: its kind, length and notice; the annual balance left after it; the department's
    cover on its working days, with the others already away; the employee's sick days this
    year; and their other leave requests in the 90 days before, and how many came at short
    notice."""
    employee = db.get(Employee, leave.employee_id)
    asked = leave.created_at.date()
    profile = employee.country.calendar_profile()
    colleagues = list(db.execute(
        select(Employee.id).where(Employee.department_id == employee.department_id,
                                  Employee.employment_status != EmploymentStatus.TERMINATED)
    ).scalars())  # fmt: skip
    headcount = len(colleagues)
    others_away = 0
    day = leave.start_date
    while day <= leave.end_date:
        if calendar.is_business_day(profile, day):
            away = on_leave_ids(db, day, employee.department_id) - {employee.id}
            others_away = max(others_away, len(away))
        day += timedelta(days=1)
    working = headcount - others_away - 1
    earlier = list(db.execute(
        select(LeaveRequest).where(
            LeaveRequest.employee_id == employee.id, LeaveRequest.id != leave.id,
            LeaveRequest.created_at < leave.created_at,
            LeaveRequest.created_at >= leave.created_at - timedelta(days=90))
    ).scalars())  # fmt: skip
    sick = db.execute(
        select(func.coalesce(func.sum(LeaveRequest.days), 0)).where(
            LeaveRequest.employee_id == employee.id, LeaveRequest.id != leave.id,
            LeaveRequest.kind == LeaveKind.SICK, LeaveRequest.status == LeaveStatus.APPROVED,
            LeaveRequest.start_date > asked - timedelta(days=365))
    ).scalar_one()  # fmt: skip
    balance = None
    if leave.kind == LeaveKind.ANNUAL:
        balance = ANNUAL_ENTITLEMENT_DAYS - leave_used(db, employee.id, leave.start_date.year)
    return {
        "kind": leave.kind, "days": leave.days,
        "notice_days": (leave.start_date - asked).days,
        "annual_balance_after": balance,
        "department_headcount": headcount, "others_away": others_away,
        "coverage_pct": max(working, 0) * 100 // headcount if headcount else 0,
        "sick_days_365": int(sick),
        "prior_requests_90d": len(earlier),
        "prior_short_notice_90d": sum(
            1 for e in earlier
            if (e.start_date - e.created_at.date()).days < SHORT_NOTICE_DAYS),
    }  # fmt: skip


def summary(db: Session, on: date | None = None) -> dict[str, Any]:
    on = on or _now().date()

    def count(model, *where) -> int:
        return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()

    return {
        "requisitions_to_approve": count(JobRequisition,
                                         JobRequisition.status == RequisitionStatus.OPEN),
        "requisitions_recruiting": count(JobRequisition,
                                         JobRequisition.status == RequisitionStatus.APPROVED),
        "offers_out": count(Candidate, Candidate.status == CandidateStatus.OFFERED),
        "leave_to_decide": count(LeaveRequest, LeaveRequest.status == LeaveStatus.REQUESTED),
        "on_leave_today": len(on_leave_ids(db, on)),
        "onboarding_overdue": count(OnboardingTask, OnboardingTask.completed_at.is_(None),
                                    OnboardingTask.due < on),
        "shifts_today": count(Shift, Shift.on == on),
    }  # fmt: skip
