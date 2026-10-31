"""Cards API (Phase 31)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.errors import BusinessRuleViolation
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
from app.modules.accounts import service as accounts
from app.modules.accounts.models import Account
from app.modules.cards import service
from app.modules.cards.models import (
    AuthorizationStatus,
    Card,
    CardAuthorization,
    CardDispute,
    CardStatus,
    DisputeStatus,
)
from app.modules.identity.dependencies import Authorized

router = APIRouter(prefix="/cards", tags=["cards"])

DisputeReason = Literal["not_recognised", "not_received", "duplicate", "wrong_amount"]


class ProductOut(BaseModel):
    product_code: str
    name: str
    daily_limit_usd: int
    validity_years: int


class CardOut(BaseModel):
    id: uuid.UUID
    card_number: str = Field(description="Masked: the first four and last four digits")
    last4: str
    product_code: str
    account_id: uuid.UUID
    account_number: str
    currency: str
    daily_limit: int
    expires_on: datetime
    status: str
    blocked_reason: str | None
    issued_at: datetime


class CardIssue(BaseModel):
    account_number: str = Field(min_length=6, max_length=34)
    product_code: str = Field(default="debit-standard", max_length=40)


class CardBlock(BaseModel):
    reason: Literal["lost", "stolen", "customer_request", "fraud_suspected"]


class AuthorizationRequest(BaseModel):
    """A purchase from the synthetic merchant terminal."""

    merchant_name: str = Field(min_length=2, max_length=100)
    merchant_category: str = Field(pattern=r"^\d{4}$", description="e.g. 5411 groceries")
    merchant_country: str = Field(pattern=r"^[A-Z]{2}$")
    amount: int = Field(gt=0, description="Minor units of the card's currency")


class AuthorizationOut(BaseModel):
    id: uuid.UUID
    auth_code: str
    card_id: uuid.UUID
    card_last4: str
    merchant_name: str
    merchant_category: str
    merchant_country: str
    amount: int
    currency: str
    status: str
    decline_reason: str | None
    fraud_score: int
    fraud_signals: list[str]
    created_at: datetime


class DisputeOpen(BaseModel):
    auth_code: str = Field(min_length=6, max_length=20)
    reason: DisputeReason
    amount: int | None = Field(default=None, gt=0, description="Default: the whole purchase")


class DisputeDecision(BaseModel):
    refund: bool


class DisputeOut(BaseModel):
    id: uuid.UUID
    dispute_number: str
    auth_code: str
    reason: str
    amount: int
    currency: str
    status: str
    opened_at: datetime
    decided_at: datetime | None


def _cards_out(db, cards: list[Card]) -> list[CardOut]:
    ids = list({c.account_id for c in cards})
    numbers = (
        dict(
            db.execute(select(Account.id, Account.account_number).where(Account.id.in_(ids)))
            .tuples()
            .all()
        )
        if ids
        else {}
    )
    return [
        CardOut(
            id=c.id,
            card_number=service.masked(c.card_number),
            last4=c.card_number[-4:],
            product_code=c.product_code,
            account_id=c.account_id,
            account_number=numbers[c.account_id],
            currency=c.currency,
            daily_limit=c.daily_limit,
            expires_on=c.expires_on,
            status=c.status,
            blocked_reason=c.blocked_reason,
            issued_at=c.issued_at,
        )
        for c in cards
    ]


def _auths_out(db, auths: list[CardAuthorization]) -> list[AuthorizationOut]:
    ids = list({a.card_id for a in auths})
    numbers = (
        dict(db.execute(select(Card.id, Card.card_number).where(Card.id.in_(ids))).tuples().all())
        if ids
        else {}
    )
    return [
        AuthorizationOut(
            id=a.id,
            auth_code=a.auth_code,
            card_id=a.card_id,
            card_last4=numbers[a.card_id][-4:],
            merchant_name=a.merchant_name,
            merchant_category=a.merchant_category,
            merchant_country=a.merchant_country,
            amount=a.amount,
            currency=a.currency,
            status=a.status,
            decline_reason=a.decline_reason,
            fraud_score=a.fraud_score,
            fraud_signals=[s for s in a.fraud_signals.split(",") if s],
            created_at=a.created_at,
        )
        for a in auths
    ]


def _disputes_out(db, disputes: list[CardDispute]) -> list[DisputeOut]:
    ids = list({d.authorization_id for d in disputes})
    auths = (
        {
            a.id: a
            for a in db.execute(
                select(CardAuthorization).where(CardAuthorization.id.in_(ids))
            ).scalars()
        }
        if ids
        else {}
    )
    return [
        DisputeOut(
            id=d.id,
            dispute_number=d.dispute_number,
            auth_code=auths[d.authorization_id].auth_code,
            reason=d.reason,
            amount=d.amount,
            currency=auths[d.authorization_id].currency,
            status=d.status,
            opened_at=d.opened_at,
            decided_at=d.decided_at,
        )
        for d in disputes
    ]


@router.get("/products", response_model=list[ProductOut], summary="Card products")
def list_products(db: DbSession, _: Authorized(Permission.ACCOUNTS_READ)):
    return service.list_products(db)


@router.get("", response_model=Page[CardOut], summary="Cards")
def list_cards(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.ACCOUNTS_READ),
    account_id: uuid.UUID | None = None,
    status_filter: Annotated[CardStatus | None, Query(alias="status")] = None,
) -> Page[CardOut]:
    query = select(Card).order_by(Card.issued_at.desc(), Card.card_number.desc())
    if account_id is not None:
        query = query.where(Card.account_id == account_id)
    if status_filter is not None:
        query = query.where(Card.status == status_filter)
    items, total = paginate(db, query, page)
    return Page(items=_cards_out(db, items), total=total, limit=page.limit, offset=page.offset)


@router.post("", response_model=CardOut, status_code=status.HTTP_201_CREATED, summary="Issue")
def issue_card(body: CardIssue, db: DbSession, actor: Authorized(Permission.ACCOUNTS_TRANSACT)):
    account = accounts.find_account(db, body.account_number)
    if account is None:
        raise BusinessRuleViolation(f"No account {body.account_number}.")
    return _cards_out(db, [service.issue_card(db, account, body.product_code, actor.id)])[0]


@router.post("/{card_id}/block", response_model=CardOut, summary="Block a card")
def block_card(
    card_id: uuid.UUID,
    body: CardBlock,
    db: DbSession,
    actor: Authorized(Permission.ACCOUNTS_TRANSACT),
):
    card = service.get_card(db, card_id, for_update=True)
    return _cards_out(db, [service.block_card(db, card, body.reason, actor.id)])[0]


@router.post("/{card_id}/unblock", response_model=CardOut, summary="Release a block")
def unblock_card(card_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.CARDS_MANAGE)):
    card = service.unblock_card(db, service.get_card(db, card_id, for_update=True), actor.id)
    return _cards_out(db, [card])[0]


@router.post("/{card_id}/cancel", response_model=CardOut, summary="Cancel a card")
def cancel_card(card_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.CARDS_MANAGE)):
    card = service.cancel_card(db, service.get_card(db, card_id, for_update=True), actor.id)
    return _cards_out(db, [card])[0]


@router.post(
    "/{card_id}/authorizations",
    response_model=AuthorizationOut,
    status_code=status.HTTP_201_CREATED,
    summary="A purchase from the synthetic merchant terminal (approved or declined)",
)
def authorize(
    card_id: uuid.UUID,
    body: AuthorizationRequest,
    db: DbSession,
    _: Authorized(Permission.ACCOUNTS_TRANSACT),
) -> AuthorizationOut:
    auth = service.authorize(
        db,
        service.get_card(db, card_id),
        merchant_name=body.merchant_name,
        merchant_category=body.merchant_category,
        merchant_country=body.merchant_country,
        amount=body.amount,
    )
    return _auths_out(db, [auth])[0]


@router.get("/authorizations/list", response_model=Page[AuthorizationOut], summary="Authorisations")
def list_authorizations(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.ACCOUNTS_READ),
    card_id: uuid.UUID | None = None,
    status_filter: Annotated[AuthorizationStatus | None, Query(alias="status")] = None,
) -> Page[AuthorizationOut]:
    query = select(CardAuthorization).order_by(CardAuthorization.created_at.desc())
    if card_id is not None:
        query = query.where(CardAuthorization.card_id == card_id)
    if status_filter is not None:
        query = query.where(CardAuthorization.status == status_filter)
    items, total = paginate(db, query, page)
    return Page(items=_auths_out(db, items), total=total, limit=page.limit, offset=page.offset)


@router.get("/disputes/list", response_model=Page[DisputeOut], summary="Disputes")
def list_disputes(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.ACCOUNTS_READ),
    status_filter: Annotated[DisputeStatus | None, Query(alias="status")] = None,
) -> Page[DisputeOut]:
    query = select(CardDispute).order_by(CardDispute.opened_at.desc())
    if status_filter is not None:
        query = query.where(CardDispute.status == status_filter)
    items, total = paginate(db, query, page)
    return Page(items=_disputes_out(db, items), total=total, limit=page.limit, offset=page.offset)


@router.post(
    "/disputes", response_model=DisputeOut, status_code=status.HTTP_201_CREATED, summary="Dispute"
)
def open_dispute(body: DisputeOpen, db: DbSession, actor: Authorized(Permission.ACCOUNTS_TRANSACT)):
    auth = service.find_authorization(db, body.auth_code)
    if auth is None:
        raise BusinessRuleViolation(f"No authorisation {body.auth_code}.")
    dispute = service.open_dispute(db, auth, body.reason, body.amount, actor.id)
    return _disputes_out(db, [dispute])[0]


@router.post(
    "/disputes/{dispute_id}/decide",
    response_model=DisputeOut,
    summary="Charge back (refund) or reject; four-eyes",
)
def decide_dispute(
    dispute_id: uuid.UUID,
    body: DisputeDecision,
    db: DbSession,
    actor: Authorized(Permission.CARDS_MANAGE),
) -> DisputeOut:
    dispute = service.decide_dispute(db, service.get_dispute(db, dispute_id), body.refund, actor.id)
    return _disputes_out(db, [dispute])[0]


@router.get("/summary/counts", summary="Counts for the cards page")
def summary(db: DbSession, _: Authorized(Permission.ACCOUNTS_READ)) -> dict:
    return service.summary(db)
