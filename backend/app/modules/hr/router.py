"""Human resources API (Phase 55)."""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
from app.modules.employees.models import Employee
from app.modules.hr import service
from app.modules.hr.models import (
    Candidate,
    JobRequisition,
    LeaveRequest,
    OnboardingTask,
    Shift,
)
from app.modules.identity.dependencies import Authorized
from app.modules.organizations.models import Organization

router = APIRouter(prefix="/hr", tags=["hr"])
READ, MANAGE, APPROVE = Permission.HR_READ, Permission.HR_MANAGE, Permission.HR_APPROVE


class RequisitionIn(BaseModel):
    department_id: uuid.UUID
    job_title: str = Field(min_length=2, max_length=150)
    role: str = Field(default="banking_employee", max_length=40)
    openings: int = Field(default=1, ge=1, le=50)
    salary_min: int = Field(gt=0, description="Yearly, minor units of the department's currency")
    salary_max: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=300)


class RequisitionOut(BaseModel):
    id: uuid.UUID
    requisition_number: str
    department: str
    job_title: str
    role: str
    openings: int
    filled: int
    salary_min: int
    salary_max: int
    currency: str
    reason: str
    status: str
    created_at: datetime


class CandidateIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)


class OfferIn(BaseModel):
    salary: int = Field(gt=0)
    start_date: date


class CandidateOut(BaseModel):
    id: uuid.UUID
    candidate_number: str
    requisition_number: str
    name: str
    status: str
    offered_salary: int | None
    start_date: date | None
    employee_number: str | None


class LeaveIn(BaseModel):
    employee_number: str = Field(min_length=1, max_length=20)
    kind: str = "annual"
    start_date: date
    end_date: date
    note: str = Field(default="", max_length=300)


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=300)


class LeaveOut(BaseModel):
    id: uuid.UUID
    leave_number: str
    employee_number: str
    employee_name: str
    kind: str
    start_date: date
    end_date: date
    days: int
    status: str
    note: str | None
    created_at: datetime


class ShiftIn(BaseModel):
    department_id: uuid.UUID
    on: date
    start_hour: int = Field(ge=0, le=23)
    hours: int = Field(ge=1, le=12)
    required: int = Field(ge=1, le=100)


class AssignIn(BaseModel):
    employee_number: str = Field(min_length=1, max_length=20)


class ShiftOut(BaseModel):
    id: uuid.UUID
    shift_number: str
    department: str
    on: date
    start_hour: int
    hours: int
    required: int
    rostered: list[str]


class TaskOut(BaseModel):
    id: uuid.UUID
    employee_number: str
    employee_name: str
    code: str
    title: str
    due: date
    completed_at: datetime | None


def _name(employee: Employee) -> str:
    return f"{employee.first_name} {employee.last_name}"


def _req_out(db, row: JobRequisition) -> RequisitionOut:
    return RequisitionOut(
        id=row.id, requisition_number=row.requisition_number,
        department=db.get(Organization, row.department_id).name, job_title=row.job_title,
        role=row.role, openings=row.openings, filled=row.filled, salary_min=row.salary_min,
        salary_max=row.salary_max, currency=row.currency, reason=row.reason, status=row.status,
        created_at=row.created_at,
    )  # fmt: skip


def _cand_out(db, c: Candidate) -> CandidateOut:
    employee = db.get(Employee, c.employee_id) if c.employee_id else None
    return CandidateOut(
        id=c.id, candidate_number=c.candidate_number,
        requisition_number=db.get(JobRequisition, c.requisition_id).requisition_number,
        name=f"{c.first_name} {c.last_name}", status=c.status, offered_salary=c.offered_salary,
        start_date=c.start_date, employee_number=employee.employee_number if employee else None,
    )  # fmt: skip


def _leave_out(db, leave: LeaveRequest) -> LeaveOut:
    employee = db.get(Employee, leave.employee_id)
    return LeaveOut(
        id=leave.id, leave_number=leave.leave_number, employee_number=employee.employee_number,
        employee_name=_name(employee), kind=leave.kind, start_date=leave.start_date,
        end_date=leave.end_date, days=leave.days, status=leave.status, note=leave.note,
        created_at=leave.created_at,
    )  # fmt: skip


def _shift_out(db, shift: Shift) -> ShiftOut:
    return ShiftOut(
        id=shift.id, shift_number=shift.shift_number,
        department=db.get(Organization, shift.department_id).name, on=shift.on,
        start_hour=shift.start_hour, hours=shift.hours, required=shift.required,
        rostered=[e.employee_number for e in service.roster(db, shift)],
    )  # fmt: skip


def _task_out(db, task: OnboardingTask) -> TaskOut:
    employee = db.get(Employee, task.employee_id)
    return TaskOut(id=task.id, employee_number=employee.employee_number,
                   employee_name=_name(employee), code=task.code, title=task.title,
                   due=task.due, completed_at=task.completed_at)  # fmt: skip


# --- Departments and capacity ------------------------------------------------------------------


@router.get("/departments", summary="Departments with their headcount")
def departments(db: DbSession, _: Authorized(READ)) -> list[dict]:
    return service.departments(db)


@router.get("/capacity", summary="Who can work in a department on a day")
def capacity(db: DbSession, _: Authorized(READ), department_id: uuid.UUID,
             on: date | None = None) -> dict:  # fmt: skip
    return service.capacity(db, department_id, on or datetime.now().date())


@router.get("/summary/counts", summary="Counts for the HR page")
def summary(db: DbSession, _: Authorized(READ)) -> dict:
    return service.summary(db)


# --- Requisitions and candidates ---------------------------------------------------------------


@router.get("/requisitions", response_model=Page[RequisitionOut], summary="Requisitions")
def list_requisitions(db: DbSession, page: PageParamsDep, _: Authorized(READ)):
    query = select(JobRequisition).order_by(JobRequisition.created_at.desc(),
                                            JobRequisition.requisition_number.desc())  # fmt: skip
    items, total = paginate(db, query, page)
    return Page(items=[_req_out(db, r) for r in items], total=total, limit=page.limit,
                offset=page.offset)  # fmt: skip


@router.post("/requisitions", response_model=RequisitionOut, status_code=status.HTTP_201_CREATED,
             summary="Open a requisition (approved by someone else)")  # fmt: skip
def open_requisition(body: RequisitionIn, db: DbSession, user: Authorized(MANAGE)):
    row = service.open_requisition(
        db, service.department(db, body.department_id), job_title=body.job_title,
        role=body.role, openings=body.openings, salary_min=body.salary_min,
        salary_max=body.salary_max, reason=body.reason, requested_by=user.id,
    )  # fmt: skip
    return _req_out(db, row)


@router.post("/requisitions/{requisition_id}/approve", response_model=RequisitionOut)
def approve_requisition(requisition_id: uuid.UUID, db: DbSession, user: Authorized(APPROVE)):
    row = service.get_requisition(db, requisition_id)
    return _req_out(db, service.decide_requisition(db, row, user.id, True))


@router.post("/requisitions/{requisition_id}/cancel", response_model=RequisitionOut)
def cancel_requisition(requisition_id: uuid.UUID, db: DbSession, user: Authorized(APPROVE)):
    row = service.get_requisition(db, requisition_id)
    return _req_out(db, service.decide_requisition(db, row, user.id, False))


@router.get("/candidates", response_model=list[CandidateOut], summary="Candidates")
def list_candidates(db: DbSession, _: Authorized(READ),
                    requisition_id: uuid.UUID | None = None) -> list[CandidateOut]:  # fmt: skip
    query = select(Candidate).order_by(Candidate.created_at.desc()).limit(200)
    if requisition_id is not None:
        query = query.where(Candidate.requisition_id == requisition_id)
    return [_cand_out(db, c) for c in db.execute(query).scalars()]


@router.post("/requisitions/{requisition_id}/candidates", response_model=CandidateOut,
             status_code=status.HTTP_201_CREATED)  # fmt: skip
def add_candidate(requisition_id: uuid.UUID, body: CandidateIn, db: DbSession,
                  _: Authorized(MANAGE)):  # fmt: skip
    row = service.get_requisition(db, requisition_id)
    return _cand_out(db, service.add_candidate(db, row, body.first_name, body.last_name))


@router.post("/candidates/{candidate_id}/offer", response_model=CandidateOut)
def offer(candidate_id: uuid.UUID, body: OfferIn, db: DbSession, user: Authorized(MANAGE)):
    candidate = service.get_candidate(db, candidate_id)
    return _cand_out(db, service.make_offer(db, candidate, body.salary, body.start_date,
                                            user.id))  # fmt: skip


@router.post("/candidates/{candidate_id}/hire", response_model=CandidateOut,
             summary="The candidate accepted: hire them")  # fmt: skip
def hire(candidate_id: uuid.UUID, db: DbSession, user: Authorized(MANAGE)):
    candidate = service.get_candidate(db, candidate_id)
    service.hire(db, candidate, user.id)
    return _cand_out(db, candidate)


@router.post("/candidates/{candidate_id}/decline", response_model=CandidateOut)
def decline(candidate_id: uuid.UUID, db: DbSession, _: Authorized(MANAGE),
            by_candidate: bool = True):  # fmt: skip
    return _cand_out(db, service.decline(db, service.get_candidate(db, candidate_id),
                                         by_candidate))  # fmt: skip


# --- Onboarding --------------------------------------------------------------------------------


@router.get("/onboarding", response_model=list[TaskOut], summary="Onboarding tasks")
def onboarding(db: DbSession, _: Authorized(READ), open_only: bool = True) -> list[TaskOut]:
    return [_task_out(db, t) for t in service.onboarding(db, open_only=open_only)]


@router.post("/onboarding/{task_id}/complete", response_model=TaskOut)
def complete_task(task_id: uuid.UUID, db: DbSession, user: Authorized(MANAGE)):
    return _task_out(db, service.complete_task(db, task_id, user.id))


# --- Leave -------------------------------------------------------------------------------------


@router.get("/leave", response_model=Page[LeaveOut], summary="Leave requests")
def list_leave(db: DbSession, page: PageParamsDep, _: Authorized(READ),
               status_: str | None = Query(default=None, alias="status")):  # fmt: skip
    query = select(LeaveRequest).order_by(LeaveRequest.created_at.desc(),
                                          LeaveRequest.leave_number.desc())  # fmt: skip
    if status_:
        query = query.where(LeaveRequest.status == status_)
    items, total = paginate(db, query, page)
    return Page(items=[_leave_out(db, r) for r in items], total=total, limit=page.limit,
                offset=page.offset)  # fmt: skip


@router.post("/leave", response_model=LeaveOut, status_code=status.HTTP_201_CREATED,
             summary="Request leave for an employee")  # fmt: skip
def request_leave(body: LeaveIn, db: DbSession, user: Authorized(MANAGE)):
    employee = service.find_employee(db, body.employee_number)
    leave = service.request_leave(db, employee, body.kind, body.start_date, body.end_date,
                                  user.id, body.note)  # fmt: skip
    return _leave_out(db, leave)


@router.post("/leave/{leave_id}/approve", response_model=LeaveOut)
def approve_leave(leave_id: uuid.UUID, db: DbSession, user: Authorized(MANAGE),
                  body: NoteIn | None = None):  # fmt: skip
    leave = service.get_leave(db, leave_id)
    return _leave_out(db, service.decide_leave(db, leave, user.id, True,
                                               body.note if body else ""))  # fmt: skip


@router.post("/leave/{leave_id}/reject", response_model=LeaveOut)
def reject_leave(leave_id: uuid.UUID, db: DbSession, user: Authorized(MANAGE),
                 body: NoteIn | None = None):  # fmt: skip
    leave = service.get_leave(db, leave_id)
    return _leave_out(db, service.decide_leave(db, leave, user.id, False,
                                               body.note if body else ""))  # fmt: skip


@router.post("/leave/{leave_id}/cancel", response_model=LeaveOut)
def cancel_leave(leave_id: uuid.UUID, db: DbSession, user: Authorized(MANAGE)):
    return _leave_out(db, service.cancel_leave(db, service.get_leave(db, leave_id), user.id))


@router.post("/leave/sweep", summary="Set who is on leave today")
def leave_sweep(db: DbSession, _: Authorized(MANAGE)) -> dict:
    return service.leave_sweep(db)


# --- Shifts ------------------------------------------------------------------------------------


@router.get("/shifts", response_model=list[ShiftOut], summary="Shifts on a day")
def list_shifts(db: DbSession, _: Authorized(READ), on: date | None = None,
                department_id: uuid.UUID | None = None) -> list[ShiftOut]:  # fmt: skip
    query = select(Shift).where(Shift.on == (on or datetime.now().date()))
    if department_id is not None:
        query = query.where(Shift.department_id == department_id)
    query = query.order_by(Shift.start_hour, Shift.shift_number)
    return [_shift_out(db, s) for s in db.execute(query).scalars()]


@router.post("/shifts", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
def create_shift(body: ShiftIn, db: DbSession, user: Authorized(MANAGE)):
    shift = service.create_shift(db, service.department(db, body.department_id), body.on,
                                 body.start_hour, body.hours, body.required,
                                 user.id)  # fmt: skip
    return _shift_out(db, shift)


@router.post("/shifts/{shift_id}/assign", response_model=ShiftOut,
             summary="Roster an employee onto the shift")  # fmt: skip
def assign(shift_id: uuid.UUID, body: AssignIn, db: DbSession, user: Authorized(MANAGE)):
    shift = service.get_shift(db, shift_id)
    service.assign(db, shift, service.find_employee(db, body.employee_number), user.id)
    return _shift_out(db, shift)


@router.post("/shifts/{shift_id}/unassign", response_model=ShiftOut)
def unassign(shift_id: uuid.UUID, body: AssignIn, db: DbSession, _: Authorized(MANAGE)):
    shift = service.get_shift(db, shift_id)
    service.unassign(db, shift, service.find_employee(db, body.employee_number))
    return _shift_out(db, shift)
