"""Thin departments' API (Phase 61): the departments, their processes and requests."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
from app.modules.backoffice import service
from app.modules.backoffice.models import DepartmentRequest
from app.modules.identity.dependencies import Authorized

router = APIRouter(prefix="/backoffice", tags=["backoffice"])
READ, REQUEST = Permission.DEPARTMENTS_READ, Permission.DEPARTMENTS_REQUEST
APPROVE, MAJOR = Permission.DEPARTMENTS_APPROVE, Permission.DEPARTMENTS_APPROVE_MAJOR


class RequestIn(BaseModel):
    department: str = Field(min_length=1, max_length=40)
    process: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=5, max_length=200)
    details: str = Field(default="", max_length=4000)
    amount: int | None = Field(default=None, gt=0, description="US cents")


class DecisionIn(BaseModel):
    note: str | None = Field(default=None, max_length=300)


class RequestOut(BaseModel):
    id: uuid.UUID
    request_number: str
    department: str
    process: str
    process_name: str
    title: str
    details: str
    amount: int | None
    over_budget: bool
    needs_executive: bool
    status: str
    due_at: datetime
    breached: bool
    note: str | None
    created_at: datetime


def _out(db, r: DepartmentRequest) -> RequestOut:
    _, proc = service.spec(r)
    return RequestOut(
        id=r.id, request_number=r.request_number, department=r.department, process=r.process,
        process_name=proc.name, title=r.title, details=r.details, amount=r.amount,
        over_budget=service.over_budget(r), needs_executive=service.needs_executive(r),
        status=r.status, due_at=r.due_at, breached=r.breached, note=r.note,
        created_at=r.created_at,
    )  # fmt: skip


@router.get("/departments", summary="The thin departments, their processes and counts")
def departments(db: DbSession, _: Authorized(READ)) -> list[dict]:
    return service.departments(db)


@router.get("/requests", response_model=Page[RequestOut], summary="Requests, newest first")
def list_requests(db: DbSession, page: PageParamsDep, _: Authorized(READ),
                  department: str | None = None,
                  status_: str | None = Query(default=None, alias="status")):  # fmt: skip
    query = select(DepartmentRequest).order_by(DepartmentRequest.created_at.desc(),
                                               DepartmentRequest.request_number.desc())  # fmt: skip
    if department:
        query = query.where(DepartmentRequest.department == department)
    if status_:
        query = query.where(DepartmentRequest.status == status_)
    items, total = paginate(db, query, page)
    return Page(items=[_out(db, r) for r in items], total=total, limit=page.limit,
                offset=page.offset)  # fmt: skip


@router.post("/requests", response_model=RequestOut, status_code=status.HTTP_201_CREATED,
             summary="Submit a request to a department's process")  # fmt: skip
def submit(body: RequestIn, db: DbSession, user: Authorized(REQUEST)):
    request = service.submit(db, body.department, body.process, title=body.title,
                             details=body.details, amount=body.amount,
                             requested_by=user.id)  # fmt: skip
    return _out(db, request)


@router.post("/requests/{request_id}/approve", response_model=RequestOut)
def approve(request_id: uuid.UUID, body: DecisionIn, db: DbSession, user: Authorized(APPROVE)):
    request = service.get(db, request_id)
    return _out(db, service.decide(db, request, user.id, True, user.can(MAJOR), body.note))


@router.post("/requests/{request_id}/reject", response_model=RequestOut)
def reject(request_id: uuid.UUID, body: DecisionIn, db: DbSession, user: Authorized(APPROVE)):
    request = service.get(db, request_id)
    return _out(db, service.decide(db, request, user.id, False, note=body.note))


@router.post("/requests/{request_id}/complete", response_model=RequestOut)
def complete(request_id: uuid.UUID, db: DbSession, user: Authorized(REQUEST)):
    return _out(db, service.complete(db, service.get(db, request_id), user.id))
