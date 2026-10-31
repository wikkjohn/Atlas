"""Mortgages API (Phase 33)."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.errors import BusinessRuleViolation, PermissionDeniedError
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
from app.modules.accounts import service as accounts
from app.modules.customers.models import Customer
from app.modules.identity.dependencies import Authorized
from app.modules.lending.models import Loan
from app.modules.mortgages import service
from app.modules.mortgages.models import (
    MortgageOffer,
    OfferStatus,
    Property,
    PropertyType,
    PropertyValuation,
)

router = APIRouter(prefix="/mortgages", tags=["mortgages"])


class ProductOut(BaseModel):
    product_code: str
    name: str
    max_ltv_bps: int
    annual_rate_bps: int
    max_term_years: int
    min_loan_usd: int
    max_loan_usd: int


class ValuationOut(BaseModel):
    id: uuid.UUID
    valuation_number: str
    method: str
    value: int
    currency: str
    valued_on: date
    notes: str | None


class PropertyOut(BaseModel):
    id: uuid.UUID
    property_number: str
    customer_number: str
    customer_name: str
    country_code: str
    property_type: str
    address: str
    purchase_price: int
    currency: str
    latest_valuation: ValuationOut | None
    charged_loan_number: str | None
    created_at: datetime


class PropertyCreate(BaseModel):
    customer_number: str = Field(min_length=4, max_length=20)
    property_type: PropertyType
    purchase_price: int = Field(gt=0, description="Minor units of the customer's currency")


class ValuationCreate(BaseModel):
    method: Literal["desktop", "surveyor"]
    value: int | None = Field(default=None, gt=0, description="Surveyor valuations only")
    notes: str | None = Field(default=None, max_length=500)


class Application(BaseModel):
    customer_number: str = Field(min_length=4, max_length=20)
    property_number: str = Field(min_length=4, max_length=20)
    product_code: str = Field(max_length=40)
    account_number: str = Field(min_length=6, max_length=34)
    loan_amount: int = Field(gt=0)
    term_years: int = Field(ge=1, le=40)
    declared_monthly_income: int = Field(ge=0)


class OfferOut(BaseModel):
    id: uuid.UUID
    offer_number: str
    customer_number: str
    property_number: str
    product_code: str
    loan_amount: int
    currency: str
    term_months: int
    annual_rate_bps: int
    monthly_payment: int
    ltv_bps: int
    status: str
    expired: bool
    expires_on: date | None
    loan_number: str | None
    created_at: datetime


class Decision(BaseModel):
    approve: bool


def _properties_out(db, props: list[Property]) -> list[PropertyOut]:
    customers = {
        c.id: c
        for c in db.execute(
            select(Customer).where(Customer.id.in_({p.customer_id for p in props}))
        ).scalars()
    }
    out = []
    for p in props:
        valuation = service.latest_valuation(db, p)
        loan = service.charged_loan(db, p)
        out.append(
            PropertyOut(
                id=p.id,
                property_number=p.property_number,
                customer_number=customers[p.customer_id].customer_number,
                customer_name=customers[p.customer_id].name,
                country_code=p.country_code,
                property_type=p.property_type,
                address=p.address,
                purchase_price=p.purchase_price,
                currency=p.currency,
                latest_valuation=ValuationOut.model_validate(valuation, from_attributes=True)
                if valuation
                else None,
                charged_loan_number=loan.loan_number if loan else None,
                created_at=p.created_at,
            )  # fmt: skip
        )
    return out


def _offers_out(db, offers: list[MortgageOffer]) -> list[OfferOut]:
    today = datetime.now().date()

    def lookup(model, column, ids):
        return dict(
            db.execute(select(model.id, column).where(model.id.in_(ids))).tuples().all()
        ) if ids else {}  # fmt: skip

    customers = lookup(Customer, Customer.customer_number, {o.customer_id for o in offers})
    props = lookup(Property, Property.property_number, {o.property_id for o in offers})
    loans = lookup(Loan, Loan.loan_number, {o.loan_id for o in offers if o.loan_id})
    return [
        OfferOut(
            id=o.id,
            offer_number=o.offer_number,
            customer_number=customers[o.customer_id],
            property_number=props[o.property_id],
            product_code=o.product_code,
            loan_amount=o.loan_amount,
            currency=o.currency,
            term_months=o.term_months,
            annual_rate_bps=o.annual_rate_bps,
            monthly_payment=o.monthly_payment,
            ltv_bps=o.ltv_bps,
            status=o.status,
            expired=service.expired(o, today),
            expires_on=o.expires_on,
            loan_number=loans.get(o.loan_id) if o.loan_id else None,
            created_at=o.created_at,
        )  # fmt: skip
        for o in offers
    ]


def _resolve(db, body: Application) -> dict:
    customer = service.find_customer(db, body.customer_number)
    if customer is None:
        raise BusinessRuleViolation(f"No customer {body.customer_number}.")
    prop = service.find_property(db, body.property_number)
    if prop is None:
        raise BusinessRuleViolation(f"No property {body.property_number}.")
    account = accounts.find_account(db, body.account_number)
    if account is None:
        raise BusinessRuleViolation(f"No account {body.account_number}.")
    return {
        "customer": customer,
        "prop": prop,
        "product": service.get_product(db, body.product_code),
        "account": account,
        "loan_amount": body.loan_amount,
        "term_years": body.term_years,
        "declared_monthly_income": body.declared_monthly_income,
    }


@router.get("/products", response_model=list[ProductOut], summary="Mortgage products")
def list_products(db: DbSession, _: Authorized(Permission.LOANS_READ)):
    return service.list_products(db)


@router.get("/properties", response_model=Page[PropertyOut], summary="Properties")
def list_properties(
    db: DbSession, page: PageParamsDep, _: Authorized(Permission.LOANS_READ)
) -> Page[PropertyOut]:
    query = select(Property).order_by(Property.created_at.desc(), Property.property_number.desc())
    items, total = paginate(db, query, page)
    return Page(items=_properties_out(db, items), total=total, limit=page.limit, offset=page.offset)


@router.post(
    "/properties", response_model=PropertyOut, status_code=status.HTTP_201_CREATED,
    summary="Register a property",
)  # fmt: skip
def register_property(
    body: PropertyCreate, db: DbSession, actor: Authorized(Permission.ACCOUNTS_TRANSACT)
):
    customer = service.find_customer(db, body.customer_number)
    if customer is None:
        raise BusinessRuleViolation(f"No customer {body.customer_number}.")
    prop = service.register_property(
        db, customer, body.property_type, body.purchase_price, actor.id
    )
    return _properties_out(db, [prop])[0]


@router.get(
    "/properties/{property_id}/valuations", response_model=list[ValuationOut],
    summary="A property's valuations",
)  # fmt: skip
def list_valuations(property_id: uuid.UUID, db: DbSession, _: Authorized(Permission.LOANS_READ)):
    return db.execute(
        select(PropertyValuation)
        .where(PropertyValuation.property_id == property_id)
        .order_by(PropertyValuation.valued_on.desc(), PropertyValuation.valuation_number.desc())
    ).scalars().all()  # fmt: skip


@router.post(
    "/properties/{property_id}/valuations", response_model=ValuationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Value a property: desktop model (accounts:transact) or surveyor (mortgages:manage)",
)  # fmt: skip
def value_property(
    property_id: uuid.UUID,
    body: ValuationCreate,
    db: DbSession,
    actor: Authorized(Permission.ACCOUNTS_TRANSACT),
):
    if body.method == "surveyor" and not actor.can(Permission.MORTGAGES_MANAGE):
        raise PermissionDeniedError("Surveyor valuations need mortgages:manage.")
    return service.value_property(
        db, service.get_property(db, property_id), body.method, value=body.value,
        actor_id=actor.id if body.method == "surveyor" else None, notes=body.notes,
    )  # fmt: skip


@router.post("/quote", summary="A decision in principle: every rule with the figures")
def quote(body: Application, db: DbSession, _: Authorized(Permission.ACCOUNTS_TRANSACT)) -> dict:
    return service.quote(db, **_resolve(db, body))


@router.get("/offers", response_model=Page[OfferOut], summary="Mortgage offers")
def list_offers(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.LOANS_READ),
    status_filter: Annotated[OfferStatus | None, Query(alias="status")] = None,
) -> Page[OfferOut]:
    query = select(MortgageOffer).order_by(
        MortgageOffer.created_at.desc(), MortgageOffer.offer_number.desc()
    )
    if status_filter is not None:
        query = query.where(MortgageOffer.status == status_filter)
    items, total = paginate(db, query, page)
    return Page(items=_offers_out(db, items), total=total, limit=page.limit, offset=page.offset)


@router.post(
    "/offers", response_model=OfferOut, status_code=status.HTTP_201_CREATED,
    summary="Apply: refused unless every rule passes; then pending a decision",
)  # fmt: skip
def request_offer(
    body: Application, db: DbSession, actor: Authorized(Permission.ACCOUNTS_TRANSACT)
):
    offer = service.request_offer(db, requested_by=actor.id, **_resolve(db, body))
    return _offers_out(db, [offer])[0]


@router.post(
    "/offers/{offer_id}/decide", response_model=OfferOut,
    summary="Approve (valid 90 days) or decline; not by the requester",
)  # fmt: skip
def decide_offer(
    offer_id: uuid.UUID, body: Decision, db: DbSession, actor: Authorized(Permission.LOANS_APPROVE)
):
    offer = service.get_offer(db, offer_id, for_update=True)
    return _offers_out(db, [service.decide_offer(db, offer, body.approve, actor.id)])[0]


@router.post("/offers/{offer_id}/accept", response_model=OfferOut, summary="The customer accepts")
def accept_offer(
    offer_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.ACCOUNTS_TRANSACT)
):
    offer = service.get_offer(db, offer_id, for_update=True)
    return _offers_out(db, [service.accept_offer(db, offer, actor.id)])[0]


@router.post(
    "/offers/{offer_id}/complete", response_model=OfferOut,
    summary="Draw the loan down and charge it on the property; not by the requester",
)  # fmt: skip
def complete_offer(offer_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.LOANS_APPROVE)):
    offer = service.get_offer(db, offer_id, for_update=True)
    service.complete_offer(db, offer, actor.id)
    return _offers_out(db, [offer])[0]


@router.post("/offers/{offer_id}/withdraw", response_model=OfferOut, summary="Withdraw")
def withdraw_offer(
    offer_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.ACCOUNTS_TRANSACT)
):
    offer = service.get_offer(db, offer_id, for_update=True)
    return _offers_out(db, [service.withdraw_offer(db, offer, actor.id)])[0]


@router.get("/summary/counts", summary="Counts for the mortgages page")
def summary(db: DbSession, _: Authorized(Permission.LOANS_READ)) -> dict:
    return service.summary(db)
