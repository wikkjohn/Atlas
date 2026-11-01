"""Risk API (Phase 47)."""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.errors import BusinessRuleViolation
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
from app.modules.customers.models import Customer
from app.modules.identity.dependencies import Authorized
from app.modules.risk import service
from app.modules.risk.models import CreditRating, ProvisionLine, ProvisionRun

router = APIRouter(prefix="/risk", tags=["risk"])
READ = Permission.RISK_READ


class RatingOut(BaseModel):
    id: uuid.UUID
    rating_number: str
    customer_number: str
    customer_name: str
    grade: int
    suggested_grade: int
    pd_bps: int
    factors: dict
    rationale: str
    status: str
    rated_on: date
    expires_on: date


class RunOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    run_number: str
    as_of: date
    status: str
    exposures: int
    totals: dict
    note: str | None
    created_at: datetime


class LineOut(BaseModel):
    model_config = {"from_attributes": True}

    exposure_type: str
    reference: str
    currency: str
    ead: int
    days_past_due: int
    grade: int
    stage: int
    pd_bps: int
    lgd_bps: int
    ecl: int


def _customer(db, number: str) -> Customer:
    customer = db.execute(
        select(Customer).where(Customer.customer_number == number.strip().upper())
    ).scalar_one_or_none()
    if customer is None:
        raise BusinessRuleViolation(f"No customer {number}.")
    return customer


def _rating_out(db, r: CreditRating) -> RatingOut:
    customer = db.get(Customer, r.customer_id)
    return RatingOut(
        id=r.id, rating_number=r.rating_number, customer_number=customer.customer_number,
        customer_name=customer.name, grade=r.grade, suggested_grade=r.suggested_grade,
        pd_bps=r.pd_bps, factors=r.factors, rationale=r.rationale, status=r.status,
        rated_on=r.rated_on, expires_on=r.expires_on,
    )  # fmt: skip


# --- Obligors, ratings and limits -------------------------------------------------------------


class RateIn(BaseModel):
    customer_number: str = Field(min_length=1, max_length=20)
    grade: int | None = Field(default=None, ge=1, le=10)
    rationale: str = Field(default="", max_length=300)


class LimitIn(BaseModel):
    customer_number: str = Field(min_length=1, max_length=20)
    limit_usd: int = Field(ge=0, le=10_000_000_000)
    note: str = Field(default="", max_length=200)


@router.get("/obligors/{customer_number}", summary="An obligor's grade, limit and exposure")
def obligor(customer_number: str, db: DbSession, _: Authorized(READ)) -> dict:
    return service.obligor(db, _customer(db, customer_number))


@router.get("/breaches", summary="Obligors above their limit, largest excess first")
def breaches(db: DbSession, _: Authorized(READ)) -> list[dict]:
    return service.breaches(db)


@router.get("/ratings", response_model=Page[RatingOut], summary="Ratings, newest first")
def list_ratings(db: DbSession, page: PageParamsDep, _: Authorized(READ)):
    query = select(CreditRating).order_by(CreditRating.created_at.desc(),
                                          CreditRating.rating_number.desc())  # fmt: skip
    items, total = paginate(db, query, page)
    return Page(items=[_rating_out(db, r) for r in items], total=total, limit=page.limit,
                offset=page.offset)  # fmt: skip


@router.post("/ratings", response_model=RatingOut, status_code=status.HTTP_201_CREATED,
             summary="Rate an obligor: the model's grade, or another with a rationale")  # fmt: skip
def rate(body: RateIn, db: DbSession, actor: Authorized(Permission.RISK_RATE)):
    rating = service.rate(db, _customer(db, body.customer_number), body.grade, actor.id,
                          body.rationale)  # fmt: skip
    return _rating_out(db, rating)


@router.post("/ratings/{rating_id}/approve", response_model=RatingOut,
             summary="Approve a rating that departs from the model; not by the rater")  # fmt: skip
def approve_rating(rating_id: uuid.UUID, db: DbSession,
                   actor: Authorized(Permission.RISK_APPROVE)):  # fmt: skip
    return _rating_out(db, service.decide_rating(db, service.get_rating(db, rating_id), actor.id,
                                                 approve=True))  # fmt: skip


@router.post("/ratings/{rating_id}/reject", response_model=RatingOut, summary="Reject it")
def reject_rating(rating_id: uuid.UUID, db: DbSession,
                  actor: Authorized(Permission.RISK_APPROVE)):  # fmt: skip
    return _rating_out(db, service.decide_rating(db, service.get_rating(db, rating_id), actor.id,
                                                 approve=False))  # fmt: skip


@router.put("/limits", summary="Set an obligor's credit limit (US dollars)")
def set_limit(body: LimitIn, db: DbSession, actor: Authorized(Permission.RISK_APPROVE)) -> dict:
    customer = _customer(db, body.customer_number)
    service.set_limit(db, customer, body.limit_usd, actor.id, body.note)
    return service.obligor(db, customer)


# --- Provisioning -----------------------------------------------------------------------------


class Note(BaseModel):
    note: str = Field(default="", max_length=200)


@router.get("/provisions", response_model=Page[RunOut], summary="Provision runs, newest first")
def list_runs(db: DbSession, page: PageParamsDep, _: Authorized(READ)):
    query = select(ProvisionRun).order_by(ProvisionRun.created_at.desc(),
                                          ProvisionRun.run_number.desc())  # fmt: skip
    items, total = paginate(db, query, page)
    return Page(items=[RunOut.model_validate(r) for r in items], total=total, limit=page.limit,
                offset=page.offset)  # fmt: skip


@router.post("/provisions", response_model=RunOut, status_code=status.HTTP_201_CREATED,
             summary="Calculate the loan book's ECL as of today")  # fmt: skip
def calculate(db: DbSession, actor: Authorized(Permission.RISK_RATE)):
    return RunOut.model_validate(service.calculate(db, actor.id))


@router.get("/provisions/{run_id}/lines", response_model=Page[LineOut],
            summary="A run's exposures, largest ECL first")  # fmt: skip
def run_lines(run_id: uuid.UUID, db: DbSession, page: PageParamsDep, _: Authorized(READ)):
    service.get_run(db, run_id)
    query = (
        select(ProvisionLine)
        .where(ProvisionLine.run_id == run_id)
        .order_by(ProvisionLine.ecl.desc(), ProvisionLine.reference)
    )
    items, total = paginate(db, query, page)
    return Page(items=[LineOut.model_validate(x) for x in items], total=total,
                limit=page.limit, offset=page.offset)  # fmt: skip


@router.post("/provisions/{run_id}/post", response_model=RunOut,
             summary="Post the run to the ledger; not by its calculator")  # fmt: skip
def post_run(run_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.RISK_APPROVE)):
    return RunOut.model_validate(service.post_run(db, service.get_run(db, run_id), actor.id))


@router.post("/provisions/{run_id}/reject", response_model=RunOut, summary="Reject the run")
def reject_run(run_id: uuid.UUID, body: Note, db: DbSession,
               actor: Authorized(Permission.RISK_APPROVE)):  # fmt: skip
    return RunOut.model_validate(service.reject_run(db, service.get_run(db, run_id), actor.id,
                                                    body.note))  # fmt: skip


@router.get("/summary/counts", summary="Counts for the risk page")
def summary(db: DbSession, _: Authorized(READ)) -> dict:
    return service.summary(db)
