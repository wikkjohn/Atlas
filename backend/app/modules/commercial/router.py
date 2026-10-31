"""Commercial lending API (Phase 35)."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.errors import BusinessRuleViolation
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
from app.modules.accounts import service as accounts
from app.modules.commercial import service
from app.modules.commercial.models import (
    CommercialFacility,
    CovenantTest,
    FacilityReview,
    FacilityStatus,
)
from app.modules.customers.models import Customer
from app.modules.identity.dependencies import Authorized

router = APIRouter(prefix="/commercial", tags=["commercial lending"])


class CovenantOut(BaseModel):
    kind: str
    threshold_centi: int


class FacilityOut(BaseModel):
    id: uuid.UUID
    facility_number: str
    customer_number: str
    customer_name: str
    facility_type: str
    purpose: str
    credit_limit: int
    currency: str
    annual_rate_bps: int
    term_months: int
    drawn: int
    available: int
    status: str
    frozen_reason: str | None
    draw_block: str | None
    needs_committee: bool
    approved: bool
    committee_approved: bool
    review_due_on: date | None
    matures_on: date | None
    covenants: list[CovenantOut]
    created_at: datetime


class FacilityProposal(BaseModel):
    customer_number: str = Field(min_length=4, max_length=20)
    account_number: str = Field(min_length=6, max_length=34)
    facility_type: Literal["term_loan", "revolving"]
    credit_limit: int = Field(gt=0, description="Minor units of the account's currency")
    term_months: int = Field(ge=12, le=120)
    purpose: str = Field(default="Working capital", max_length=100)
    min_dscr_centi: int | None = Field(default=None, ge=1, le=10_000, description="125 = 1.25×")
    max_leverage_centi: int | None = Field(default=None, ge=1, le=10_000, description="350 = 3.5×")


class Amount(BaseModel):
    amount: int = Field(gt=0)


class Figures(BaseModel):
    period_end: date
    ebitda: int = Field(ge=0, description="Minor units, the year to period_end")
    debt_service: int = Field(gt=0)
    total_debt: int = Field(ge=0)


class TestOut(BaseModel):
    id: uuid.UUID
    facility_id: uuid.UUID
    period_end: date
    ebitda: int
    debt_service: int
    total_debt: int
    results: list[dict]
    breached: bool
    waived: bool
    created_at: datetime


class ReviewOut(BaseModel):
    id: uuid.UUID
    review_number: str
    facility_id: uuid.UUID
    due_on: date
    outcome: str | None
    new_limit: int | None
    decided_at: datetime | None


class ReviewDecision(BaseModel):
    renew: bool
    new_limit: int | None = Field(default=None, gt=0)


def _facilities_out(db, facilities: list[CommercialFacility]) -> list[FacilityOut]:
    today = datetime.now().date()
    ids = {f.customer_id for f in facilities}
    customers = {
        c.id: c for c in db.execute(select(Customer).where(Customer.id.in_(ids))).scalars()
    } if ids else {}  # fmt: skip
    return [
        FacilityOut(
            id=f.id,
            facility_number=f.facility_number,
            customer_number=customers[f.customer_id].customer_number,
            customer_name=customers[f.customer_id].name,
            facility_type=f.facility_type,
            purpose=f.purpose,
            credit_limit=f.credit_limit,
            currency=f.currency,
            annual_rate_bps=f.annual_rate_bps,
            term_months=f.term_months,
            drawn=f.drawn,
            available=service.available(f) if f.status != FacilityStatus.PROPOSED else 0,
            status=f.status,
            frozen_reason=f.frozen_reason,
            draw_block=service.draw_block(f, today),
            needs_committee=service.needs_committee(f),
            approved=f.approved_by is not None,
            committee_approved=f.committee_approved_by is not None,
            review_due_on=f.review_due_on,
            matures_on=f.matures_on,
            covenants=[
                CovenantOut(kind=c.kind, threshold_centi=c.threshold_centi)
                for c in service.covenants(db, f)
            ],
            created_at=f.created_at,
        )  # fmt: skip
        for f in facilities
    ]


def _test_out(t: CovenantTest) -> TestOut:
    return TestOut(
        id=t.id, facility_id=t.facility_id, period_end=t.period_end, ebitda=t.ebitda,
        debt_service=t.debt_service, total_debt=t.total_debt, results=t.results,
        breached=t.breached, waived=t.waived_by is not None, created_at=t.created_at,
    )  # fmt: skip


def _one(db, facility: CommercialFacility) -> FacilityOut:
    return _facilities_out(db, [facility])[0]


@router.get("/facilities", response_model=Page[FacilityOut], summary="Facilities")
def list_facilities(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.LOANS_READ),
    status_filter: Annotated[FacilityStatus | None, Query(alias="status")] = None,
) -> Page[FacilityOut]:
    query = select(CommercialFacility).order_by(
        CommercialFacility.created_at.desc(), CommercialFacility.facility_number.desc()
    )
    if status_filter is not None:
        query = query.where(CommercialFacility.status == status_filter)
    items, total = paginate(db, query, page)
    return Page(items=_facilities_out(db, items), total=total, limit=page.limit, offset=page.offset)


@router.post(
    "/facilities", response_model=FacilityOut, status_code=status.HTTP_201_CREATED,
    summary="Propose a facility",
)  # fmt: skip
def propose(body: FacilityProposal, db: DbSession, actor: Authorized(Permission.ACCOUNTS_TRANSACT)):
    customer = service.find_customer(db, body.customer_number)
    if customer is None:
        raise BusinessRuleViolation(f"No customer {body.customer_number}.")
    account = accounts.find_account(db, body.account_number)
    if account is None:
        raise BusinessRuleViolation(f"No account {body.account_number}.")
    thresholds = {k: v for k, v in (("min_dscr", body.min_dscr_centi),
                                    ("max_leverage", body.max_leverage_centi)) if v}  # fmt: skip
    facility = service.propose_facility(
        db, customer=customer, account=account, facility_type=body.facility_type,
        credit_limit=body.credit_limit, term_months=body.term_months, purpose=body.purpose,
        requested_by=actor.id, covenant_thresholds=thresholds,
    )  # fmt: skip
    return _one(db, facility)


@router.post(
    "/facilities/{facility_id}/approve", response_model=FacilityOut,
    summary="Credit approval; not by the proposer",
)  # fmt: skip
def approve(facility_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.LOANS_APPROVE)):
    facility = service.get_facility(db, facility_id, for_update=True)
    return _one(db, service.approve_facility(db, facility, actor.id))


@router.post(
    "/facilities/{facility_id}/committee", response_model=FacilityOut,
    summary="Credit committee approval above US$1m; a third person",
)  # fmt: skip
def committee(
    facility_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.LOANS_APPROVE_LARGE)
):
    facility = service.get_facility(db, facility_id, for_update=True)
    return _one(db, service.committee_approve(db, facility, actor.id))


@router.post("/facilities/{facility_id}/decline", response_model=FacilityOut, summary="Decline")
def decline(facility_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.LOANS_APPROVE)):
    facility = service.get_facility(db, facility_id, for_update=True)
    return _one(db, service.decline_facility(db, facility, actor.id))


@router.post("/facilities/{facility_id}/draw", response_model=FacilityOut, summary="Draw down")
def draw(
    facility_id: uuid.UUID, body: Amount, db: DbSession,
    actor: Authorized(Permission.ACCOUNTS_TRANSACT),
):  # fmt: skip
    facility = service.get_facility(db, facility_id, for_update=True)
    return _one(db, service.draw(db, facility, body.amount, actor.id))


@router.post("/facilities/{facility_id}/repay", response_model=FacilityOut, summary="Repay")
def repay(
    facility_id: uuid.UUID, body: Amount, db: DbSession,
    actor: Authorized(Permission.ACCOUNTS_TRANSACT),
):  # fmt: skip
    facility = service.get_facility(db, facility_id, for_update=True)
    return _one(db, service.repay(db, facility, body.amount, actor.id))


@router.get(
    "/facilities/{facility_id}/tests", response_model=list[TestOut], summary="Covenant tests"
)
def list_tests(facility_id: uuid.UUID, db: DbSession, _: Authorized(Permission.LOANS_READ)):
    tests = db.execute(
        select(CovenantTest).where(CovenantTest.facility_id == facility_id)
        .order_by(CovenantTest.period_end.desc())
    ).scalars().all()  # fmt: skip
    return [_test_out(t) for t in tests]


@router.post(
    "/facilities/{facility_id}/tests", response_model=TestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Test the covenants on a year's figures; a breach freezes the facility",
)  # fmt: skip
def covenant_test(
    facility_id: uuid.UUID, body: Figures, db: DbSession,
    actor: Authorized(Permission.ACCOUNTS_TRANSACT),
):  # fmt: skip
    facility = service.get_facility(db, facility_id, for_update=True)
    test = service.run_covenant_test(
        db, facility, period_end=body.period_end, ebitda=body.ebitda,
        debt_service=body.debt_service, total_debt=body.total_debt, actor_id=actor.id,
    )  # fmt: skip
    return _test_out(test)


@router.post(
    "/tests/{test_id}/waive", response_model=FacilityOut,
    summary="Credit committee waives a breach; not by the submitter",
)  # fmt: skip
def waive(test_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.LOANS_APPROVE_LARGE)):
    return _one(db, service.waive_breach(db, service.get_test(db, test_id), actor.id))


@router.get("/reviews", response_model=list[ReviewOut], summary="Open and recent reviews")
def list_reviews(db: DbSession, _: Authorized(Permission.LOANS_READ)):
    return db.execute(
        select(FacilityReview).order_by(FacilityReview.created_at.desc()).limit(50)
    ).scalars().all()  # fmt: skip


@router.post(
    "/facilities/{facility_id}/reviews", response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
    summary="Open the annual review (from 60 days before it is due)",
)  # fmt: skip
def open_review(
    facility_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.ACCOUNTS_TRANSACT)
):
    facility = service.get_facility(db, facility_id, for_update=True)
    return service.open_review(db, facility, actor.id)


@router.post(
    "/reviews/{review_id}/decide", response_model=ReviewOut,
    summary="Renew (optionally with a new limit) or terminate; not by the opener",
)  # fmt: skip
def decide_review(
    review_id: uuid.UUID, body: ReviewDecision, db: DbSession,
    actor: Authorized(Permission.LOANS_APPROVE),
):  # fmt: skip
    return service.decide_review(
        db, service.get_review(db, review_id), body.renew, actor.id, new_limit=body.new_limit
    )


@router.get("/summary/counts", summary="Counts for the commercial lending page")
def summary(db: DbSession, _: Authorized(Permission.LOANS_READ)) -> dict:
    return service.summary(db)
