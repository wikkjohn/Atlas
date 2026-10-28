import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from app.core.dependencies import DbSession
from app.core.idempotency import IdempotencyKey, run_idempotent
from app.core.pagination import Page, PageParamsDep
from app.core.permissions import Permission
from app.modules.accounts.models import AccountType
from app.modules.accounts.schemas import Eligibility
from app.modules.accounts.service import eligibility
from app.modules.customers import service
from app.modules.customers.models import CustomerType, KycStatus, RiskRating
from app.modules.customers.schemas import (
    CustomerCreate,
    CustomerOut,
    CustomerReview,
    CustomerUpdate,
)
from app.modules.identity.dependencies import Authorized

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=Page[CustomerOut], summary="List synthetic customers")
def list_customers(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.CUSTOMERS_READ),
    q: Annotated[str | None, Query(max_length=100, description="Name or customer number")] = None,
    customer_type: CustomerType | None = None,
    country_id: uuid.UUID | None = None,
    risk_rating: RiskRating | None = None,
    kyc_status: KycStatus | None = None,
) -> Page[CustomerOut]:
    items, total = service.list_customers(
        db,
        page,
        q=q,
        customer_type=customer_type,
        country_id=country_id,
        risk_rating=risk_rating,
        kyc_status=kyc_status,
    )
    return Page(
        items=[service.to_out(c) for c in items], total=total, limit=page.limit, offset=page.offset
    )


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED, summary="Onboard")
def create_customer(
    body: CustomerCreate,
    request: Request,
    db: DbSession,
    actor: Authorized(Permission.CUSTOMERS_MANAGE),
    idempotency_key: IdempotencyKey = None,
):
    return run_idempotent(
        db,
        key=idempotency_key,
        actor_id=actor.id,
        method="POST",
        path=request.url.path,
        payload=body,
        status_code=status.HTTP_201_CREATED,
        operation=lambda: service.to_out(service.create_customer(db, body, actor.id)),
    )


@router.get("/{customer_id}", response_model=CustomerOut, summary="Get a customer")
def get_customer(
    customer_id: uuid.UUID, db: DbSession, _: Authorized(Permission.CUSTOMERS_READ)
) -> CustomerOut:
    return service.to_out(service.get_customer(db, customer_id))


@router.patch("/{customer_id}", response_model=CustomerOut, summary="Edit customer details")
def update_customer(
    customer_id: uuid.UUID,
    body: CustomerUpdate,
    db: DbSession,
    actor: Authorized(Permission.CUSTOMERS_MANAGE),
) -> CustomerOut:
    customer = service.update_customer(db, service.get_customer(db, customer_id), body, actor.id)
    return service.to_out(customer)


@router.post(
    "/{customer_id}/review",
    response_model=CustomerOut,
    summary="Record a KYC decision and/or risk rating",
)
def review_customer(
    customer_id: uuid.UUID,
    body: CustomerReview,
    db: DbSession,
    actor: Authorized(Permission.CUSTOMERS_REVIEW),
) -> CustomerOut:
    customer = service.get_customer(db, customer_id, for_update=True)
    return service.to_out(service.review_customer(db, customer, body, actor.id))


@router.get(
    "/{customer_id}/eligibility",
    response_model=Eligibility,
    summary="Would this customer be eligible for an account?",
)
def check_eligibility(
    customer_id: uuid.UUID,
    account_type: AccountType,
    db: DbSession,
    _: Authorized(Permission.ACCOUNTS_READ),
    currency: Annotated[str | None, Query(pattern=r"^[A-Z]{3}$")] = None,
) -> Eligibility:
    customer = service.get_customer(db, customer_id)
    return eligibility(db, customer, account_type, currency or customer.country.default_currency)
