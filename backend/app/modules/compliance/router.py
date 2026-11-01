"""Compliance API (Phase 45)."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
from app.modules.accounts.models import Account
from app.modules.compliance import service
from app.modules.compliance.models import (
    AlertStatus,
    AmlAlert,
    ComplianceCase,
    KycReview,
    MonitoringRun,
    ReviewStatus,
    SuspiciousActivityReport,
)
from app.modules.customers.models import Customer
from app.modules.identity.dependencies import Authorized

router = APIRouter(prefix="/compliance", tags=["compliance"])
READ = Permission.COMPLIANCE_READ


class RunOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    run_number: str
    window_start: date
    window_end: date
    accounts_scanned: int
    alerts_raised: int
    created_at: datetime


class AlertOut(BaseModel):
    id: uuid.UUID
    alert_number: str
    customer_number: str
    customer_name: str
    account_number: str
    rule: str
    score: int
    currency: str
    amount: int
    details: dict
    window_start: date
    window_end: date
    status: str
    case_number: str | None
    note: str | None
    created_at: datetime


class CaseOut(BaseModel):
    id: uuid.UUID
    case_number: str
    customer_number: str
    customer_name: str
    status: str
    alerts: list[str]
    sar_number: str | None
    note: str | None
    created_at: datetime


class SarOut(BaseModel):
    id: uuid.UUID
    sar_number: str
    case_number: str
    customer_number: str
    narrative: str
    currency: str
    amount: int
    status: str
    filing_reference: str | None
    created_at: datetime
    filed_at: datetime | None


class ReviewOut(BaseModel):
    id: uuid.UUID
    review_number: str
    customer_number: str
    customer_name: str
    due_on: date
    status: str
    risk_before: str
    risk_after: str | None
    outcome: str | None
    completed_on: date | None


def _customer(db, customer_id) -> Customer:
    return db.get(Customer, customer_id)


def _alert_out(db, a: AmlAlert) -> AlertOut:
    customer = _customer(db, a.customer_id)
    case_row = db.get(ComplianceCase, a.case_id) if a.case_id else None
    return AlertOut(
        id=a.id, alert_number=a.alert_number, customer_number=customer.customer_number,
        customer_name=customer.name, account_number=db.get(Account, a.account_id).account_number,
        rule=a.rule, score=a.score, currency=a.currency, amount=a.amount, details=a.details,
        window_start=a.window_start, window_end=a.window_end, status=a.status,
        case_number=case_row.case_number if case_row else None, note=a.note,
        created_at=a.created_at,
    )  # fmt: skip


def _case_out(db, c: ComplianceCase) -> CaseOut:
    customer = _customer(db, c.customer_id)
    sar = service.case_sar(db, c)
    return CaseOut(
        id=c.id, case_number=c.case_number, customer_number=customer.customer_number,
        customer_name=customer.name, status=c.status,
        alerts=[a.alert_number for a in service.case_alerts(db, c)],
        sar_number=sar.sar_number if sar else None, note=c.note, created_at=c.created_at,
    )  # fmt: skip


def _sar_out(db, s: SuspiciousActivityReport) -> SarOut:
    return SarOut(
        id=s.id, sar_number=s.sar_number, case_number=db.get(ComplianceCase, s.case_id).case_number,
        customer_number=_customer(db, s.customer_id).customer_number, narrative=s.narrative,
        currency=s.currency, amount=s.amount, status=s.status,
        filing_reference=s.filing_reference, created_at=s.created_at, filed_at=s.filed_at,
    )  # fmt: skip


def _review_out(db, r: KycReview) -> ReviewOut:
    customer = _customer(db, r.customer_id)
    return ReviewOut(
        id=r.id, review_number=r.review_number, customer_number=customer.customer_number,
        customer_name=customer.name, due_on=r.due_on, status=r.status,
        risk_before=r.risk_before, risk_after=r.risk_after, outcome=r.outcome,
        completed_on=r.completed_on,
    )  # fmt: skip


def _page(items, total, page, out):
    return Page(items=[out(i) for i in items], total=total, limit=page.limit, offset=page.offset)


class Note(BaseModel):
    note: str = Field(default="", max_length=200)


# --- Monitoring -------------------------------------------------------------------------------


class RunIn(BaseModel):
    days: int = Field(default=30, ge=1, le=366)


@router.get("/runs", response_model=Page[RunOut], summary="Monitoring runs")
def list_runs(db: DbSession, page: PageParamsDep, _: Authorized(READ)):
    query = select(MonitoringRun).order_by(MonitoringRun.created_at.desc(),
                                           MonitoringRun.run_number.desc())  # fmt: skip
    items, total = paginate(db, query, page)
    return _page(items, total, page, RunOut.model_validate)


@router.post("/runs", response_model=RunOut, status_code=status.HTTP_201_CREATED,
             summary="Run transaction monitoring over the last `days` days")  # fmt: skip
def run_monitoring(body: RunIn, db: DbSession,
                   actor: Authorized(Permission.COMPLIANCE_MONITOR)):  # fmt: skip
    return RunOut.model_validate(service.run_monitoring(db, days=body.days, actor_id=actor.id))


@router.get("/alerts", response_model=Page[AlertOut], summary="AML alerts, newest first")
def list_alerts(
    db: DbSession, page: PageParamsDep, _: Authorized(READ),
    status_filter: Annotated[AlertStatus | None, Query(alias="status")] = None,
    account_number: Annotated[str | None, Query(max_length=34)] = None,
) -> Page[AlertOut]:  # fmt: skip
    query = select(AmlAlert).order_by(AmlAlert.created_at.desc(), AmlAlert.alert_number.desc())
    if status_filter is not None:
        query = query.where(AmlAlert.status == status_filter)
    if account_number:
        query = query.join(Account, Account.id == AmlAlert.account_id).where(
            Account.account_number == account_number.strip().upper()
        )
    items, total = paginate(db, query, page)
    return _page(items, total, page, lambda a: _alert_out(db, a))


@router.post("/alerts/{alert_id}/dismiss", response_model=AlertOut,
             summary="Close an open alert as a false positive")  # fmt: skip
def dismiss_alert(alert_id: uuid.UUID, body: Note, db: DbSession,
                  actor: Authorized(Permission.COMPLIANCE_MONITOR)):  # fmt: skip
    alert = service.dismiss_alert(db, service.get_alert(db, alert_id), actor.id, body.note)
    return _alert_out(db, alert)


@router.post("/alerts/{alert_id}/investigate", response_model=CaseOut,
             summary="Open a case (or join the customer's) with their open alerts")  # fmt: skip
def investigate(alert_id: uuid.UUID, db: DbSession,
                actor: Authorized(Permission.COMPLIANCE_MONITOR)):  # fmt: skip
    return _case_out(db, service.open_case(db, service.get_alert(db, alert_id), actor.id))


# --- Cases and reports ------------------------------------------------------------------------


class SarIn(BaseModel):
    narrative: str = Field(default="", max_length=4000)


@router.get("/cases", response_model=Page[CaseOut], summary="Cases, newest first")
def list_cases(db: DbSession, page: PageParamsDep, _: Authorized(READ)):
    query = select(ComplianceCase).order_by(ComplianceCase.created_at.desc(),
                                            ComplianceCase.case_number.desc())  # fmt: skip
    items, total = paginate(db, query, page)
    return _page(items, total, page, lambda c: _case_out(db, c))


@router.post("/cases/{case_id}/close", response_model=CaseOut,
             summary="Close with no action; not by the investigator")  # fmt: skip
def close_case(case_id: uuid.UUID, body: Note, db: DbSession,
               actor: Authorized(Permission.COMPLIANCE_MONITOR)):  # fmt: skip
    return _case_out(db, service.close_case(db, service.get_case(db, case_id), actor.id,
                                            body.note))  # fmt: skip


@router.post("/cases/{case_id}/sar", response_model=SarOut, status_code=status.HTTP_201_CREATED,
             summary="Escalate: draft a suspicious activity report")  # fmt: skip
def draft_sar(case_id: uuid.UUID, body: SarIn, db: DbSession,
              actor: Authorized(Permission.COMPLIANCE_MONITOR)):  # fmt: skip
    return _sar_out(db, service.draft_sar(db, service.get_case(db, case_id), actor.id,
                                          body.narrative))  # fmt: skip


@router.get("/sars", response_model=Page[SarOut], summary="Suspicious activity reports")
def list_sars(db: DbSession, page: PageParamsDep, _: Authorized(READ)):
    query = select(SuspiciousActivityReport).order_by(
        SuspiciousActivityReport.created_at.desc(), SuspiciousActivityReport.sar_number.desc()
    )
    items, total = paginate(db, query, page)
    return _page(items, total, page, lambda s: _sar_out(db, s))


@router.post("/sars/{sar_id}/file", response_model=SarOut,
             summary="File with the (synthetic) FIU; not by the preparer")  # fmt: skip
def file_sar(sar_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.COMPLIANCE_FILE)):
    return _sar_out(db, service.file_sar(db, service.get_sar(db, sar_id), actor.id))


# --- KYC reviews ------------------------------------------------------------------------------


class ScheduleIn(BaseModel):
    horizon_days: int = Field(default=30, ge=0, le=365)


class CompleteIn(BaseModel):
    risk_rating: Literal["low", "medium", "high"]
    note: str = Field(default="", max_length=200)


@router.get("/reviews", response_model=Page[ReviewOut], summary="KYC reviews, soonest due first")
def list_reviews(
    db: DbSession, page: PageParamsDep, _: Authorized(READ),
    status_filter: Annotated[ReviewStatus | None, Query(alias="status")] = None,
) -> Page[ReviewOut]:  # fmt: skip
    query = select(KycReview).order_by(KycReview.status.desc(), KycReview.due_on,
                                       KycReview.review_number)  # fmt: skip
    if status_filter is not None:
        query = query.where(KycReview.status == status_filter)
    items, total = paginate(db, query, page)
    return _page(items, total, page, lambda r: _review_out(db, r))


@router.post("/reviews/schedule", summary="Open reviews falling due within the horizon")
def schedule_reviews(body: ScheduleIn, db: DbSession,
                     actor: Authorized(Permission.COMPLIANCE_MONITOR)) -> dict:  # fmt: skip
    return {"opened": service.schedule_reviews(db, horizon_days=body.horizon_days,
                                               actor_id=actor.id)}  # fmt: skip


@router.post("/reviews/{review_id}/complete", response_model=ReviewOut,
             summary="Record the review: the risk rating confirmed, raised or lowered")  # fmt: skip
def complete_review(review_id: uuid.UUID, body: CompleteIn, db: DbSession,
                    actor: Authorized(Permission.COMPLIANCE_MONITOR)):  # fmt: skip
    review = service.complete_review(db, service.get_review(db, review_id), actor.id,
                                     body.risk_rating, body.note)  # fmt: skip
    return _review_out(db, review)


@router.get("/summary/counts", summary="Counts for the compliance page")
def summary(db: DbSession, _: Authorized(READ)) -> dict:
    return service.summary(db)
