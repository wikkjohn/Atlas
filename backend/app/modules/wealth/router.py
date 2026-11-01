"""Wealth and investments API (Phase 43)."""

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.errors import BusinessRuleViolation
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
from app.modules.accounts.models import Account
from app.modules.customers.models import Customer
from app.modules.identity.dependencies import Authorized
from app.modules.wealth import service
from app.modules.wealth.models import (
    IncomeDistribution,
    InvestmentOrder,
    OrderStatus,
    Portfolio,
    Security,
)

router = APIRouter(prefix="/wealth", tags=["wealth and investments"])


def _today() -> date:
    return datetime.now(UTC).date()


class SecurityOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    asset_class: str
    currency: str
    risk_level: int
    complex: bool
    price: int
    income_bps: int


class ProfileOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    objective: str
    horizon_years: int
    knowledge: str
    loss_capacity: str
    risk_profile: int
    assessed_on: date
    expires_on: date


class PortfolioOut(BaseModel):
    id: uuid.UUID
    portfolio_number: str
    customer_number: str
    customer_name: str
    account_number: str
    currency: str
    status: str
    risk_profile: int | None
    created_at: datetime


class OrderOut(BaseModel):
    id: uuid.UUID
    order_number: str
    portfolio_number: str
    security_code: str
    side: str
    units: int
    price: int
    price_currency: str
    amount: int
    fee: int
    currency: str
    status: str
    suitable: bool
    reasons: list[dict]
    note: str | None
    executed_on: date | None
    created_at: datetime


class DistributionOut(BaseModel):
    id: uuid.UUID
    distribution_number: str
    security_code: str
    record_date: date
    income_per_unit: int
    currency: str
    holders: int
    created_at: datetime


def _security_out(s: Security, today: date) -> SecurityOut:
    return SecurityOut(id=s.id, code=s.code, name=s.name, asset_class=s.asset_class,
                       currency=s.currency, risk_level=s.risk_level, complex=s.complex,
                       price=service.price_on(s, today), income_bps=s.income_bps)  # fmt: skip


def _portfolio_out(db, p: Portfolio) -> PortfolioOut:
    customer = db.get(Customer, p.customer_id)
    account = db.get(Account, p.cash_account_id)
    profile = service.current_profile(db, p.customer_id, _today())
    return PortfolioOut(
        id=p.id, portfolio_number=p.portfolio_number, customer_number=customer.customer_number,
        customer_name=customer.name, account_number=account.account_number, currency=p.currency,
        status=p.status, risk_profile=profile.risk_profile if profile else None,
        created_at=p.created_at,
    )  # fmt: skip


def _order_out(db, o: InvestmentOrder) -> OrderOut:
    portfolio = db.get(Portfolio, o.portfolio_id)
    security = db.get(Security, o.security_id)
    return OrderOut(
        id=o.id, order_number=o.order_number, portfolio_number=portfolio.portfolio_number,
        security_code=security.code, side=o.side, units=o.units, price=o.price,
        price_currency=security.currency, amount=o.amount, fee=o.fee,
        currency=portfolio.currency, status=o.status, suitable=o.suitable, reasons=o.reasons,
        note=o.note, executed_on=o.executed_on, created_at=o.created_at,
    )  # fmt: skip


def _distribution_out(db, d: IncomeDistribution) -> DistributionOut:
    security = db.get(Security, d.security_id)
    return DistributionOut(id=d.id, distribution_number=d.distribution_number,
                           security_code=security.code, record_date=d.record_date,
                           income_per_unit=d.income_per_unit, currency=security.currency,
                           holders=d.holders, created_at=d.created_at)  # fmt: skip


def _customer(db, number: str) -> Customer:
    customer = db.execute(
        select(Customer).where(Customer.customer_number == number.strip().upper())
    ).scalar_one_or_none()
    if customer is None:
        raise BusinessRuleViolation(f"No customer {number}.")
    return customer


def _security(db, code: str) -> Security:
    security = service.find_security(db, code)
    if security is None:
        raise BusinessRuleViolation(f"No security {code}.")
    return security


def _portfolio(db, number: str) -> Portfolio:
    portfolio = service.find_portfolio(db, number)
    if portfolio is None:
        raise BusinessRuleViolation(f"No portfolio {number}.")
    return portfolio


# --- Securities -------------------------------------------------------------------------------


@router.get("/securities", response_model=list[SecurityOut],
            summary="The synthetic securities with today's prices")  # fmt: skip
def list_securities(db: DbSession, _: Authorized(Permission.ACCOUNTS_READ)) -> list[SecurityOut]:
    today = _today()
    items = db.execute(select(Security).where(Security.active.is_(True))
                       .order_by(Security.risk_level, Security.code)).scalars()  # fmt: skip
    return [_security_out(s, today) for s in items]


# --- Suitability profiles ---------------------------------------------------------------------


class ProfileIn(BaseModel):
    customer_number: str = Field(min_length=1, max_length=20)
    objective: Literal["preservation", "income", "balanced", "growth"]
    horizon_years: int = Field(ge=0, le=50)
    knowledge: Literal["none", "basic", "informed", "expert"]
    loss_capacity: Literal["low", "medium", "high"]


@router.post("/profiles", response_model=ProfileOut, status_code=status.HTTP_201_CREATED,
             summary="Record a suitability assessment; valid for a year")  # fmt: skip
def record_profile(body: ProfileIn, db: DbSession, actor: Authorized(Permission.WEALTH_ADVISE)):
    profile = service.record_profile(
        db, _customer(db, body.customer_number), objective=body.objective,
        horizon_years=body.horizon_years, knowledge=body.knowledge,
        loss_capacity=body.loss_capacity, assessed_by=actor.id,
    )  # fmt: skip
    return ProfileOut.model_validate(profile)


@router.get("/profiles/{customer_number}", response_model=ProfileOut | None,
            summary="A customer's current investment profile, if any")  # fmt: skip
def get_profile(customer_number: str, db: DbSession, _: Authorized(Permission.ACCOUNTS_READ)):
    profile = service.current_profile(db, _customer(db, customer_number).id, _today())
    return ProfileOut.model_validate(profile) if profile else None


# --- Portfolios -------------------------------------------------------------------------------


class PortfolioIn(BaseModel):
    account_number: str = Field(min_length=1, max_length=34)


@router.get("/portfolios", response_model=Page[PortfolioOut], summary="Portfolios in custody")
def list_portfolios(db: DbSession, page: PageParamsDep, _: Authorized(Permission.ACCOUNTS_READ)):
    query = select(Portfolio).order_by(Portfolio.created_at.desc(),
                                       Portfolio.portfolio_number.desc())  # fmt: skip
    items, total = paginate(db, query, page)
    return Page(items=[_portfolio_out(db, p) for p in items], total=total, limit=page.limit,
                offset=page.offset)  # fmt: skip


@router.post("/portfolios", response_model=PortfolioOut, status_code=status.HTTP_201_CREATED,
             summary="Open a portfolio paid for by one of the customer's accounts")  # fmt: skip
def open_portfolio(body: PortfolioIn, db: DbSession, actor: Authorized(Permission.WEALTH_ADVISE)):
    from app.modules.accounts import service as accounts

    account = accounts.find_account(db, body.account_number.strip().upper())
    if account is None:
        raise BusinessRuleViolation(f"No account {body.account_number}.")
    return _portfolio_out(db, service.open_portfolio(db, account, actor.id))


@router.get("/portfolios/{portfolio_number}/valuation",
            summary="Holdings at today's prices, with the gain on cost")  # fmt: skip
def valuation(portfolio_number: str, db: DbSession,
              _: Authorized(Permission.ACCOUNTS_READ)) -> dict:  # fmt: skip
    return service.valuation(db, _portfolio(db, portfolio_number))


@router.post("/portfolios/{portfolio_number}/close", response_model=PortfolioOut,
             summary="Close an empty portfolio")  # fmt: skip
def close_portfolio(portfolio_number: str, db: DbSession,
                    actor: Authorized(Permission.WEALTH_ADVISE)):  # fmt: skip
    return _portfolio_out(db, service.close_portfolio(db, _portfolio(db, portfolio_number),
                                                      actor.id))  # fmt: skip


# --- Orders -----------------------------------------------------------------------------------


class OrderIn(BaseModel):
    portfolio_number: str = Field(min_length=1, max_length=20)
    security_code: str = Field(min_length=1, max_length=20)
    side: Literal["buy", "sell"]
    units: int = Field(gt=0, le=10_000_000)


class Note(BaseModel):
    note: str = Field(default="", max_length=200)


@router.get("/orders", response_model=Page[OrderOut], summary="Investment orders")
def list_orders(
    db: DbSession, page: PageParamsDep, _: Authorized(Permission.ACCOUNTS_READ),
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
) -> Page[OrderOut]:  # fmt: skip
    query = select(InvestmentOrder).order_by(InvestmentOrder.created_at.desc(),
                                             InvestmentOrder.order_number.desc())  # fmt: skip
    if status_filter is not None:
        query = query.where(InvestmentOrder.status == status_filter)
    items, total = paginate(db, query, page)
    return Page(items=[_order_out(db, o) for o in items], total=total, limit=page.limit,
                offset=page.offset)  # fmt: skip


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED,
             summary="Place an order; an unsuitable buy waits for an approval")  # fmt: skip
def place_order(body: OrderIn, db: DbSession, actor: Authorized(Permission.WEALTH_ADVISE)):
    order = service.place_order(
        db, portfolio=_portfolio(db, body.portfolio_number),
        security=_security(db, body.security_code), side=body.side, units=body.units,
        placed_by=actor.id,
    )  # fmt: skip
    return _order_out(db, order)


@router.post("/orders/{order_id}/approve", response_model=OrderOut,
             summary="Approve an unsuitable order at the client's insistence")  # fmt: skip
def approve_order(order_id: uuid.UUID, body: Note, db: DbSession,
                  actor: Authorized(Permission.WEALTH_APPROVE)):  # fmt: skip
    return _order_out(db, service.approve_order(db, service.get_order(db, order_id), actor.id,
                                                body.note))  # fmt: skip


@router.post("/orders/{order_id}/release", response_model=OrderOut,
             summary="Dealing desk: execute a placed order; not by its adviser")  # fmt: skip
def release_order(order_id: uuid.UUID, db: DbSession,
                  actor: Authorized(Permission.WEALTH_ADVISE)):  # fmt: skip
    return _order_out(db, service.release_order(db, service.get_order(db, order_id), actor.id))


@router.post("/orders/{order_id}/reject", response_model=OrderOut, summary="Reject the order")
def reject_order(order_id: uuid.UUID, body: Note, db: DbSession,
                 actor: Authorized(Permission.WEALTH_APPROVE)):  # fmt: skip
    return _order_out(db, service.reject_order(db, service.get_order(db, order_id), actor.id,
                                               body.note))  # fmt: skip


# --- Income -----------------------------------------------------------------------------------


class DistributionIn(BaseModel):
    security_code: str = Field(min_length=1, max_length=20)


@router.get("/distributions", response_model=Page[DistributionOut],
            summary="Income paid to holders")  # fmt: skip
def list_distributions(db: DbSession, page: PageParamsDep,
                       _: Authorized(Permission.ACCOUNTS_READ)):  # fmt: skip
    query = select(IncomeDistribution).order_by(
        IncomeDistribution.created_at.desc(), IncomeDistribution.distribution_number.desc()
    )
    items, total = paginate(db, query, page)
    return Page(items=[_distribution_out(db, d) for d in items], total=total, limit=page.limit,
                offset=page.offset)  # fmt: skip


@router.post("/distributions", response_model=DistributionOut,
             status_code=status.HTTP_201_CREATED,
             summary="Pay a security's half-year income to every holder today")  # fmt: skip
def distribute(body: DistributionIn, db: DbSession,
               actor: Authorized(Permission.WEALTH_CUSTODY)):  # fmt: skip
    return _distribution_out(db, service.distribute_income(db, _security(db, body.security_code),
                                                           actor.id))  # fmt: skip


@router.get("/summary/counts", summary="Counts for the wealth page")
def summary(db: DbSession, _: Authorized(Permission.ACCOUNTS_READ)) -> dict:
    return service.summary(db)
