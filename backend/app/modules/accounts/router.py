import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.idempotency import (
    REPLAY_HEADER,
    IdempotencyKey,
    RequiredIdempotencyKey,
    run_idempotent,
)
from app.core.pagination import Page, PageParamsDep
from app.core.permissions import Permission
from app.modules.accounts import service
from app.modules.accounts.models import (
    Account,
    AccountRequest,
    AccountStatus,
    AccountType,
    RequestStatus,
)
from app.modules.accounts.schemas import (
    AccountOut,
    AccountRequestCreate,
    AccountRequestOut,
    Decision,
    Movement,
    MovementOut,
    Rejection,
)
from app.modules.countries.models import Country
from app.modules.customers.models import Customer
from app.modules.identity import scopes
from app.modules.identity.dependencies import Authorized
from app.modules.identity.service import AuthenticatedUser
from app.modules.ledger import service as ledger
from app.modules.ledger.schemas import StatementLineOut

requests_router = APIRouter(prefix="/account-requests", tags=["accounts"])
accounts_router = APIRouter(prefix="/accounts", tags=["accounts"])


class ApprovalOut(BaseModel):
    request: AccountRequestOut
    account: AccountOut


class StatusChange(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


# --- Scope (Phase 84): records outside the caller's countries do not exist for them --------


def _customer_country(db, customer_id) -> str | None:
    return db.execute(
        select(Country.iso_country_code)
        .join(Customer, Customer.country_id == Country.id)
        .where(Customer.id == customer_id)
    ).scalar_one_or_none()


def _scope_customer(db, user: AuthenticatedUser, customer_id: uuid.UUID) -> None:
    if user.scope.countries is not None:
        country = _customer_country(db, customer_id)
        if country is not None:
            scopes.require_visible(user.scope, "Customer", country=country)


def _scope_request(db, user: AuthenticatedUser, request_id: uuid.UUID) -> None:
    if user.scope.countries is not None:
        customer_id = db.execute(
            select(AccountRequest.customer_id).where(AccountRequest.id == request_id)
        ).scalar_one_or_none()
        if customer_id is not None:
            scopes.require_visible(user.scope, "Account request",
                                   country=_customer_country(db, customer_id))  # fmt: skip


def _scope_account(db, user: AuthenticatedUser, account_id: uuid.UUID) -> None:
    if user.scope.countries is not None:
        customer_id = db.execute(
            select(Account.customer_id).where(Account.id == account_id)
        ).scalar_one_or_none()
        if customer_id is not None:
            scopes.require_visible(user.scope, "Account",
                                   country=_customer_country(db, customer_id))  # fmt: skip


# --- Requests ------------------------------------------------------------------------------


@requests_router.get("", response_model=Page[AccountRequestOut], summary="List requests")
def list_requests(
    db: DbSession,
    page: PageParamsDep,
    user: Authorized(Permission.ACCOUNTS_READ),
    status: RequestStatus | None = None,
    customer_id: uuid.UUID | None = None,
) -> Page[AccountRequestOut]:
    items, total = service.list_requests(
        db, page, status=status, customer_id=customer_id, countries=user.scope.countries
    )
    return Page(
        items=service.requests_out(db, items), total=total, limit=page.limit, offset=page.offset
    )


@requests_router.post(
    "",
    response_model=AccountRequestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Request an account (eligibility is checked now and again at approval)",
)
def submit_request(
    body: AccountRequestCreate,
    request: Request,
    db: DbSession,
    actor: Authorized(Permission.ACCOUNTS_REQUEST),
    idempotency_key: IdempotencyKey = None,
):
    _scope_customer(db, actor, body.customer_id)
    return run_idempotent(
        db,
        key=idempotency_key,
        actor_id=actor.id,
        method="POST",
        path=request.url.path,
        payload=body,
        status_code=status.HTTP_201_CREATED,
        operation=lambda: service.requests_out(
            db,
            [
                service.submit_request(
                    db,
                    customer_id=body.customer_id,
                    account_type=body.account_type,
                    currency=body.currency,
                    requested_by=actor.id,
                )
            ],
        )[0],
    )


@requests_router.get("/{request_id}", response_model=AccountRequestOut, summary="Get a request")
def get_request(
    request_id: uuid.UUID, db: DbSession, user: Authorized(Permission.ACCOUNTS_READ)
) -> AccountRequestOut:
    _scope_request(db, user, request_id)
    return service.requests_out(db, [service.get_request(db, request_id)])[0]


@requests_router.post(
    "/{request_id}/approve",
    response_model=ApprovalOut,
    summary="Approve and open the account (not your own request; high risk needs compliance)",
)
def approve_request(
    request_id: uuid.UUID,
    body: Decision,
    db: DbSession,
    approver: Authorized(Permission.ACCOUNTS_APPROVE),
) -> ApprovalOut:
    _scope_request(db, approver, request_id)
    account = service.approve_request(db, request_id, approver, body.note)
    return ApprovalOut(
        request=service.requests_out(db, [service.get_request(db, request_id)])[0],
        account=service.accounts_out(db, [account])[0],
    )


@requests_router.post(
    "/{request_id}/reject", response_model=AccountRequestOut, summary="Reject a request"
)
def reject_request(
    request_id: uuid.UUID,
    body: Rejection,
    db: DbSession,
    approver: Authorized(Permission.ACCOUNTS_APPROVE),
) -> AccountRequestOut:
    _scope_request(db, approver, request_id)
    return service.requests_out(
        db, [service.reject_request(db, request_id, approver, body.reason)]
    )[0]


# --- Accounts ------------------------------------------------------------------------------


@accounts_router.get("", response_model=Page[AccountOut], summary="List accounts")
def list_accounts(
    db: DbSession,
    page: PageParamsDep,
    user: Authorized(Permission.ACCOUNTS_READ),
    q: Annotated[str | None, Query(max_length=100, description="Number or customer name")] = None,
    customer_id: uuid.UUID | None = None,
    status: AccountStatus | None = None,
    currency: Annotated[str | None, Query(pattern=r"^[A-Z]{3}$")] = None,
    account_type: AccountType | None = None,
) -> Page[AccountOut]:
    items, total = service.list_accounts(
        db,
        page,
        q=q,
        customer_id=customer_id,
        status=status,
        currency=currency,
        account_type=account_type,
        countries=user.scope.countries,
    )
    return Page(
        items=service.accounts_out(db, items), total=total, limit=page.limit, offset=page.offset
    )


@accounts_router.get("/{account_id}", response_model=AccountOut, summary="Get an account")
def get_account(
    account_id: uuid.UUID, db: DbSession, user: Authorized(Permission.ACCOUNTS_READ)
) -> AccountOut:
    _scope_account(db, user, account_id)
    return service.accounts_out(db, [service.get_account(db, account_id)])[0]


@accounts_router.get(
    "/{account_id}/transactions",
    response_model=Page[StatementLineOut],
    summary="Posted ledger lines for this account, newest first",
)
def list_transactions(
    account_id: uuid.UUID,
    db: DbSession,
    page: PageParamsDep,
    user: Authorized(Permission.ACCOUNTS_READ),
) -> Page[StatementLineOut]:
    _scope_account(db, user, account_id)
    account = service.get_account(db, account_id)
    lines, total = ledger.statement(
        db, ledger.get_ledger_account(db, account.ledger_account_id), page
    )
    return Page(items=lines, total=total, limit=page.limit, offset=page.offset)


def _movement_response(db, result) -> JSONResponse:
    account, entry_number, entry_id, replayed = result
    body = MovementOut(
        account=service.accounts_out(db, [account])[0],
        journal_entry_id=entry_id,
        entry_number=entry_number,
        replayed=replayed,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
        content=body.model_dump(mode="json"),
        headers={REPLAY_HEADER: "true"} if replayed else None,
    )


@accounts_router.post(
    "/{account_id}/deposits",
    response_model=MovementOut,
    status_code=status.HTTP_201_CREATED,
    summary="Synthetic cash deposit (Idempotency-Key required)",
)
def deposit(
    account_id: uuid.UUID,
    body: Movement,
    db: DbSession,
    actor: Authorized(Permission.ACCOUNTS_TRANSACT),
    idempotency_key: RequiredIdempotencyKey,
):
    _scope_account(db, actor, account_id)
    return _movement_response(
        db,
        service.deposit(
            db,
            account_id,
            amount=body.amount,
            memo=body.memo,
            idempotency_key=idempotency_key,
            actor_id=actor.id,
        ),
    )


@accounts_router.post(
    "/{account_id}/withdrawals",
    response_model=MovementOut,
    status_code=status.HTTP_201_CREATED,
    summary="Synthetic cash withdrawal; no overdrafts (Idempotency-Key required)",
)
def withdraw(
    account_id: uuid.UUID,
    body: Movement,
    db: DbSession,
    actor: Authorized(Permission.ACCOUNTS_TRANSACT),
    idempotency_key: RequiredIdempotencyKey,
):
    _scope_account(db, actor, account_id)
    return _movement_response(
        db,
        service.withdraw(
            db,
            account_id,
            amount=body.amount,
            memo=body.memo,
            idempotency_key=idempotency_key,
            actor_id=actor.id,
        ),
    )


@accounts_router.post(
    "/{account_id}/freeze",
    response_model=AccountOut,
    summary="Freeze: blocks deposits and withdrawals",
)
def freeze_account(
    account_id: uuid.UUID,
    body: StatusChange,
    db: DbSession,
    actor: Authorized(Permission.ACCOUNTS_MANAGE),
) -> AccountOut:
    _scope_account(db, actor, account_id)
    account = service.change_status(db, account_id, AccountStatus.FROZEN, actor.id, body.reason)
    return service.accounts_out(db, [account])[0]


@accounts_router.post("/{account_id}/unfreeze", response_model=AccountOut, summary="Unfreeze")
def unfreeze_account(
    account_id: uuid.UUID,
    body: StatusChange,
    db: DbSession,
    actor: Authorized(Permission.ACCOUNTS_MANAGE),
) -> AccountOut:
    _scope_account(db, actor, account_id)
    account = service.change_status(db, account_id, AccountStatus.OPEN, actor.id, body.reason)
    return service.accounts_out(db, [account])[0]


@accounts_router.post(
    "/{account_id}/close", response_model=AccountOut, summary="Close (balance must be zero)"
)
def close_account(
    account_id: uuid.UUID,
    body: StatusChange,
    db: DbSession,
    actor: Authorized(Permission.ACCOUNTS_MANAGE),
) -> AccountOut:
    _scope_account(db, actor, account_id)
    account = service.change_status(db, account_id, AccountStatus.CLOSED, actor.id, body.reason)
    return service.accounts_out(db, [account])[0]
