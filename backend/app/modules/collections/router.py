"""Collections and recoveries API (Phase 53)."""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
from app.modules.collections import service
from app.modules.collections.models import LoanRecovery, PaymentPlan
from app.modules.identity.dependencies import Authorized
from app.modules.lending.models import Loan

router = APIRouter(prefix="/collections", tags=["collections"])
READ = Permission.LOANS_READ


class PlanOut(BaseModel):
    id: uuid.UUID
    plan_number: str
    loan_number: str
    currency: str
    status: str
    arrears_amount: int
    days_past_due: int
    payments: int
    interval_days: int
    schedule: list
    missed: int
    start_date: date
    note: str | None
    created_at: datetime


class RecoveryOut(BaseModel):
    id: uuid.UUID
    recovery_number: str
    loan_number: str
    kind: str
    amount: int
    currency: str
    status: str
    entry_number: str | None
    note: str | None
    created_at: datetime


def _plan_out(db, plan: PaymentPlan) -> PlanOut:
    loan = db.get(Loan, plan.loan_id)
    return PlanOut(
        id=plan.id, plan_number=plan.plan_number, loan_number=loan.loan_number,
        currency=loan.currency, status=plan.status, arrears_amount=plan.arrears_amount,
        days_past_due=plan.days_past_due, payments=plan.payments,
        interval_days=plan.interval_days, schedule=plan.schedule, missed=plan.missed,
        start_date=plan.start_date, note=plan.note, created_at=plan.created_at,
    )  # fmt: skip


def _recovery_out(db, recovery: LoanRecovery) -> RecoveryOut:
    loan = db.get(Loan, recovery.loan_id)
    return RecoveryOut(
        id=recovery.id, recovery_number=recovery.recovery_number,
        loan_number=loan.loan_number, kind=recovery.kind, amount=recovery.amount,
        currency=recovery.currency, status=recovery.status,
        entry_number=recovery.entry_number, note=recovery.note,
        created_at=recovery.created_at,
    )  # fmt: skip


class PlanIn(BaseModel):
    loan_number: str = Field(min_length=1, max_length=20)
    interval_days: int = Field(default=14, ge=7, le=31)


class Note(BaseModel):
    note: str = Field(default="", max_length=200)


class CollectIn(BaseModel):
    as_of: date | None = None


class RecoveryIn(BaseModel):
    loan_number: str = Field(min_length=1, max_length=20)
    kind: str = Field(pattern="^(payment|agency|debt_sale)$")
    amount: int = Field(gt=0, le=10_000_000_000)
    note: str = Field(default="", max_length=200)


@router.get("/arrears", summary="Active loans in arrears, most days past due first")
def arrears(db: DbSession, _: Authorized(READ)) -> list[dict]:
    return service.arrears_book(db)


@router.get("/plans", response_model=Page[PlanOut], summary="Payment plans, newest first")
def list_plans(db: DbSession, page: PageParamsDep, _: Authorized(READ)):
    query = select(PaymentPlan).order_by(PaymentPlan.created_at.desc(),
                                         PaymentPlan.plan_number.desc())  # fmt: skip
    items, total = paginate(db, query, page)
    return Page(items=[_plan_out(db, p) for p in items], total=total, limit=page.limit,
                offset=page.offset)  # fmt: skip


@router.post("/plans", response_model=PlanOut, status_code=status.HTTP_201_CREATED,
             summary="Propose a payment plan for a loan in arrears")  # fmt: skip
def propose_plan(body: PlanIn, db: DbSession, actor: Authorized(Permission.LOANS_SERVICE)):
    plan = service.propose_plan(db, service.find_loan(db, body.loan_number), body.interval_days,
                                actor.id)  # fmt: skip
    return _plan_out(db, plan)


@router.post("/plans/{plan_id}/approve", response_model=PlanOut,
             summary="Approve the plan; not by its proposer")  # fmt: skip
def approve_plan(plan_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.LOANS_APPROVE)):
    return _plan_out(db, service.decide_plan(db, service.get_plan(db, plan_id), actor.id, True))


@router.post("/plans/{plan_id}/reject", response_model=PlanOut, summary="Reject the plan")
def reject_plan(plan_id: uuid.UUID, body: Note, db: DbSession,
                actor: Authorized(Permission.LOANS_APPROVE)):  # fmt: skip
    return _plan_out(db, service.decide_plan(db, service.get_plan(db, plan_id), actor.id, False,
                                             body.note))  # fmt: skip


@router.post("/plans/collect", summary="Take the plan payments due (default: the business date)")
def collect(body: CollectIn, db: DbSession, actor: Authorized(Permission.LOANS_SERVICE)) -> dict:
    from app.modules.lending import servicing

    as_of = body.as_of or servicing.current_date(db)
    return {"as_of": as_of.isoformat(), **service.collect(db, as_of, actor)}


@router.get("/written-off", summary="Written-off loans with what was recovered")
def written_off(db: DbSession, _: Authorized(READ)) -> list[dict]:
    return service.written_off_book(db)


@router.get("/recoveries", response_model=Page[RecoveryOut], summary="Recoveries, newest first")
def list_recoveries(db: DbSession, page: PageParamsDep, _: Authorized(READ)):
    query = select(LoanRecovery).order_by(LoanRecovery.created_at.desc(),
                                          LoanRecovery.recovery_number.desc())  # fmt: skip
    items, total = paginate(db, query, page)
    return Page(items=[_recovery_out(db, r) for r in items], total=total, limit=page.limit,
                offset=page.offset)  # fmt: skip


@router.post("/recoveries", response_model=RecoveryOut, status_code=status.HTTP_201_CREATED,
             summary="Record a recovery on a written-off loan")  # fmt: skip
def record_recovery(body: RecoveryIn, db: DbSession,
                    actor: Authorized(Permission.LOANS_SERVICE)):  # fmt: skip
    recovery = service.record_recovery(db, service.find_loan(db, body.loan_number), body.kind,
                                       body.amount, actor.id, body.note)  # fmt: skip
    return _recovery_out(db, recovery)


@router.post("/recoveries/{recovery_id}/approve", response_model=RecoveryOut,
             summary="Approve a debt sale (credit committee); not by its recorder")  # fmt: skip
def approve_recovery(recovery_id: uuid.UUID, db: DbSession,
                     actor: Authorized(Permission.LOANS_APPROVE_LARGE)):  # fmt: skip
    return _recovery_out(db, service.decide_recovery(db, service.get_recovery(db, recovery_id),
                                                     actor.id, True))  # fmt: skip


@router.post("/recoveries/{recovery_id}/reject", response_model=RecoveryOut,
             summary="Reject a debt sale")  # fmt: skip
def reject_recovery(recovery_id: uuid.UUID, body: Note, db: DbSession,
                    actor: Authorized(Permission.LOANS_APPROVE_LARGE)):  # fmt: skip
    return _recovery_out(db, service.decide_recovery(db, service.get_recovery(db, recovery_id),
                                                     actor.id, False, body.note))  # fmt: skip


@router.get("/summary/counts", summary="Counts for the collections page")
def summary(db: DbSession, _: Authorized(READ)) -> dict:
    return service.summary(db)
