"""Finance API (Phase 49)."""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.idempotency import RequiredIdempotencyKey
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
from app.modules.finance import service
from app.modules.finance.models import CostAllocation, PeriodClose, RegulatoryReport, ReportType
from app.modules.identity.dependencies import Authorized

router = APIRouter(prefix="/finance", tags=["finance"])
READ = Permission.FINANCE_READ
PERIOD = r"^[0-9]{4}-(0[1-9]|1[0-2])$"


class CloseOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    close_number: str
    period: str
    period_start: date
    period_end: date
    status: str
    checks: list
    results: dict
    note: str | None
    created_at: datetime


class ReportOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    report_number: str
    report_type: str
    period: str
    status: str
    rows: list
    summary: dict
    reference: str | None
    note: str | None
    created_at: datetime


class AllocationOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    allocation_number: str
    period: str
    currency: str
    pool: int
    driver: str
    lines: list
    status: str
    note: str | None
    created_at: datetime


class PeriodIn(BaseModel):
    period: str = Field(pattern=PERIOD)


class Note(BaseModel):
    note: str = Field(default="", max_length=200)


def _page(db, query, page, out):
    items, total = paginate(db, query, page)
    return Page(items=[out.model_validate(x) for x in items], total=total, limit=page.limit,
                offset=page.offset)  # fmt: skip


# --- Period close -----------------------------------------------------------------------------


@router.get("/closes", response_model=Page[CloseOut], summary="Period closes, newest first")
def list_closes(db: DbSession, page: PageParamsDep, _: Authorized(READ)):
    query = select(PeriodClose).order_by(PeriodClose.created_at.desc(),
                                         PeriodClose.close_number.desc())  # fmt: skip
    return _page(db, query, page, CloseOut)


@router.post("/closes", response_model=CloseOut, status_code=status.HTTP_201_CREATED,
             summary="Prepare a month's close: run its checks and measure its result")  # fmt: skip
def prepare_close(body: PeriodIn, db: DbSession, actor: Authorized(Permission.FINANCE_CLOSE)):
    return CloseOut.model_validate(service.prepare_close(db, body.period, actor.id))


@router.post("/closes/{close_id}/approve", response_model=CloseOut,
             summary="Close the month: post the closing entry; not by the preparer")  # fmt: skip
def approve_close(close_id: uuid.UUID, db: DbSession,
                  actor: Authorized(Permission.FINANCE_APPROVE)):  # fmt: skip
    return CloseOut.model_validate(service.approve_close(db, service.get_close(db, close_id),
                                                         actor.id))  # fmt: skip


@router.post("/closes/{close_id}/reject", response_model=CloseOut, summary="Reject the close")
def reject_close(close_id: uuid.UUID, body: Note, db: DbSession,
                 actor: Authorized(Permission.FINANCE_APPROVE)):  # fmt: skip
    return CloseOut.model_validate(service.reject_close(db, service.get_close(db, close_id),
                                                        actor.id, body.note))  # fmt: skip


# --- Regulatory reports -----------------------------------------------------------------------


class ReportIn(BaseModel):
    report_type: ReportType
    period: str = Field(pattern=PERIOD)


@router.get("/reports", response_model=Page[ReportOut], summary="Reports, newest first")
def list_reports(db: DbSession, page: PageParamsDep, _: Authorized(READ),
                 report_type: ReportType | None = None):  # fmt: skip
    query = select(RegulatoryReport).order_by(RegulatoryReport.created_at.desc(),
                                              RegulatoryReport.report_number.desc())  # fmt: skip
    if report_type is not None:
        query = query.where(RegulatoryReport.report_type == report_type)
    return _page(db, query, page, ReportOut)


@router.post("/reports", response_model=ReportOut, status_code=status.HTTP_201_CREATED,
             summary="Extract a report for a closed month")  # fmt: skip
def prepare_report(body: ReportIn, db: DbSession, actor: Authorized(Permission.FINANCE_CLOSE)):
    return ReportOut.model_validate(service.prepare_report(db, body.report_type, body.period,
                                                           actor.id))  # fmt: skip


@router.get("/reports/{report_id}/csv", response_class=PlainTextResponse,
            summary="The report's rows as CSV")  # fmt: skip
def report_csv(report_id: uuid.UUID, db: DbSession, _: Authorized(READ)):
    report = service.get_report(db, report_id)
    name = f"{report.report_number}-{report.report_type}-{report.period}.csv"
    return PlainTextResponse(
        service.report_csv(report),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/reports/{report_id}/submit", response_model=ReportOut,
             summary="Submit it to the (synthetic) regulator; not by the preparer")  # fmt: skip
def submit_report(report_id: uuid.UUID, db: DbSession,
                  actor: Authorized(Permission.FINANCE_APPROVE)):  # fmt: skip
    return ReportOut.model_validate(service.submit_report(db, service.get_report(db, report_id),
                                                          actor.id))  # fmt: skip


@router.post("/reports/{report_id}/reject", response_model=ReportOut, summary="Reject it")
def reject_report(report_id: uuid.UUID, body: Note, db: DbSession,
                  actor: Authorized(Permission.FINANCE_APPROVE)):  # fmt: skip
    return ReportOut.model_validate(service.reject_report(db, service.get_report(db, report_id),
                                                          actor.id, body.note))  # fmt: skip


# --- Shared costs and allocation --------------------------------------------------------------


class ExpenseIn(BaseModel):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount: int = Field(gt=0, le=10_000_000_000_000)
    description: str = Field(min_length=1, max_length=200)
    effective_date: date | None = None


class AllocationIn(BaseModel):
    period: str = Field(pattern=PERIOD)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


@router.post(
    "/expenses",
    status_code=status.HTTP_201_CREATED,
    summary="Record a shared operating cost paid from cash (Idempotency-Key required)",
)
def record_expense(body: ExpenseIn, db: DbSession, idempotency_key: RequiredIdempotencyKey,
                   actor: Authorized(Permission.FINANCE_CLOSE)) -> dict:  # fmt: skip
    return service.record_expense(db, currency=body.currency, amount=body.amount,
                                  description=body.description, actor_id=actor.id,
                                  idempotency_key=idempotency_key,
                                  effective_date=body.effective_date)  # fmt: skip


@router.get("/allocations", response_model=Page[AllocationOut], summary="Newest first")
def list_allocations(db: DbSession, page: PageParamsDep, _: Authorized(READ)):
    query = select(CostAllocation).order_by(CostAllocation.created_at.desc(),
                                            CostAllocation.allocation_number.desc())  # fmt: skip
    return _page(db, query, page, AllocationOut)


@router.post("/allocations", response_model=AllocationOut, status_code=status.HTTP_201_CREATED,
             summary="Split a month's shared costs across departments by headcount")  # fmt: skip
def calculate_allocation(body: AllocationIn, db: DbSession,
                         actor: Authorized(Permission.FINANCE_CLOSE)):  # fmt: skip
    return AllocationOut.model_validate(
        service.calculate_allocation(db, body.period, body.currency, actor.id)
    )


@router.post("/allocations/{allocation_id}/post", response_model=AllocationOut,
             summary="Post it to the cost centres; not by its calculator")  # fmt: skip
def post_allocation(allocation_id: uuid.UUID, db: DbSession,
                    actor: Authorized(Permission.FINANCE_APPROVE)):  # fmt: skip
    return AllocationOut.model_validate(
        service.post_allocation(db, service.get_allocation(db, allocation_id), actor.id)
    )


@router.post("/allocations/{allocation_id}/reject", response_model=AllocationOut,
             summary="Reject it")  # fmt: skip
def reject_allocation(allocation_id: uuid.UUID, body: Note, db: DbSession,
                      actor: Authorized(Permission.FINANCE_APPROVE)):  # fmt: skip
    return AllocationOut.model_validate(
        service.reject_allocation(
            db, service.get_allocation(db, allocation_id), actor.id, body.note
        )  # fmt: skip
    )


@router.get("/summary/counts", summary="Counts for the finance page")
def summary(db: DbSession, _: Authorized(READ)) -> dict:
    return service.summary(db)
