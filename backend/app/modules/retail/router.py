"""Retail banking API (Phase 29)."""

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.audit import record_audit_event
from app.core.dependencies import DbSession
from app.core.errors import BusinessRuleViolation
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
from app.jobs import engine
from app.jobs.router import JobOut, _job_out
from app.modules.accounts import service as accounts
from app.modules.accounts.models import Account
from app.modules.identity.dependencies import Authorized
from app.modules.retail import service
from app.modules.retail.models import (
    AccountStatement,
    MonthEndRun,
    StandingOrder,
    StandingOrderFrequency,
    StandingOrderStatus,
)
from app.simulation.router import SessionFactory

router = APIRouter(prefix="/retail", tags=["retail banking"])


class ProductOut(BaseModel):
    account_type: str
    name: str
    credit_rate_bps: int
    overdraft_rate_bps: int
    monthly_fee_usd_cents: int
    max_overdraft_usd: int
    updated_at: datetime


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    credit_rate_bps: int | None = Field(default=None, ge=0, le=2000)
    overdraft_rate_bps: int | None = Field(default=None, ge=0, le=5000)
    monthly_fee_usd_cents: int | None = Field(default=None, ge=0, le=100_000)
    max_overdraft_usd: int | None = Field(default=None, ge=0, le=1_000_000)


class OverdraftUpdate(BaseModel):
    limit: int = Field(ge=0, le=10**15, description="Minor units of the account's currency")


class OverdraftOut(BaseModel):
    account_number: str
    currency: str
    overdraft_limit: int
    previous_limit: int
    maximum: int


class StandingOrderCreate(BaseModel):
    debtor_account_number: str = Field(min_length=6, max_length=34)
    creditor_account_number: str = Field(min_length=6, max_length=34)
    amount: int = Field(gt=0, description="Minor units of the payer's currency")
    frequency: StandingOrderFrequency
    first_date: date
    end_date: date | None = None
    reference: str = Field(min_length=1, max_length=100)


class StandingOrderOut(BaseModel):
    id: uuid.UUID
    order_number: str
    debtor_account_number: str
    creditor_account_number: str
    amount: int
    currency: str
    frequency: str
    next_date: date
    end_date: date | None
    reference: str
    status: str
    failures: int
    last_error: str | None
    payments_made: int
    created_at: datetime


class StatementOut(BaseModel):
    id: uuid.UUID
    statement_number: str
    account_id: uuid.UUID
    account_number: str
    period_start: date
    period_end: date
    currency: str
    opening_balance: int
    closing_balance: int
    total_credits: int
    total_debits: int
    lines: int
    overdraft_limit: int
    issued_at: datetime


class StatementDetail(StatementOut):
    entries: list[dict[str, Any]]


class MonthEndOut(BaseModel):
    id: uuid.UUID
    period_start: date
    period_end: date
    accounts: int
    statements: int
    entries: int
    totals: dict[str, dict[str, int]]
    completed_at: datetime


class MonthEndRequest(BaseModel):
    period: date | None = Field(
        default=None, description="Any day of the month; default: the last complete month"
    )


def _numbers(db, ids) -> dict[uuid.UUID, str]:
    ids = list(set(ids))
    if not ids:
        return {}
    return dict(db.execute(select(Account.id, Account.account_number).where(Account.id.in_(ids))))


def _orders_out(db, orders: list[StandingOrder]) -> list[StandingOrderOut]:
    numbers = _numbers(
        db, [o.debtor_account_id for o in orders] + [o.creditor_account_id for o in orders]
    )
    return [
        StandingOrderOut(
            id=o.id,
            order_number=o.order_number,
            debtor_account_number=numbers[o.debtor_account_id],
            creditor_account_number=numbers[o.creditor_account_id],
            amount=o.amount,
            currency=o.currency,
            frequency=o.frequency,
            next_date=o.next_date,
            end_date=o.end_date,
            reference=o.reference,
            status=o.status,
            failures=o.failures,
            last_error=o.last_error,
            payments_made=o.payments_made,
            created_at=o.created_at,
        )
        for o in orders
    ]  # fmt: skip


def _statements_out(db, statements: list[AccountStatement]) -> list[StatementOut]:
    numbers = _numbers(db, [s.account_id for s in statements])
    return [
        StatementOut(
            **{f: getattr(s, f) for f in StatementOut.model_fields if f != "account_number"},
            account_number=numbers[s.account_id],
        )
        for s in statements
    ]


def _account(db, number: str) -> Account:
    account = accounts.find_account(db, number)
    if account is None:
        raise BusinessRuleViolation(f"No account {number}.")
    return account


@router.get("/products", response_model=list[ProductOut], summary="Retail products")
def list_products(db: DbSession, _: Authorized(Permission.ACCOUNTS_READ)):
    return service.list_products(db)


@router.patch("/products/{account_type}", response_model=ProductOut, summary="Change terms")
def update_product(
    account_type: str,
    body: ProductUpdate,
    db: DbSession,
    actor: Authorized(Permission.RETAIL_MANAGE),
):
    return service.update_product(db, account_type, body.model_dump(exclude_none=True), actor.id)


@router.put(
    "/accounts/{account_id}/overdraft",
    response_model=OverdraftOut,
    summary="Arrange, change or remove (0) an account's overdraft",
)
def set_overdraft(
    account_id: uuid.UUID,
    body: OverdraftUpdate,
    db: DbSession,
    actor: Authorized(Permission.RETAIL_MANAGE),
) -> OverdraftOut:
    account, previous = service.set_overdraft(
        db, accounts.get_account(db, account_id), body.limit, actor.id
    )
    return OverdraftOut(
        account_number=account.account_number,
        currency=account.currency,
        overdraft_limit=account.overdraft_limit,
        previous_limit=previous,
        maximum=service.max_overdraft(
            service.get_product(db, account.account_type), account.currency
        ),
    )


@router.get("/standing-orders", response_model=Page[StandingOrderOut], summary="Standing orders")
def list_standing_orders(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.ACCOUNTS_READ),
    account_id: uuid.UUID | None = None,
    status_filter: Annotated[StandingOrderStatus | None, Query(alias="status")] = None,
) -> Page[StandingOrderOut]:
    query = select(StandingOrder).order_by(StandingOrder.order_number.desc())
    if account_id is not None:
        query = query.where(
            (StandingOrder.debtor_account_id == account_id)
            | (StandingOrder.creditor_account_id == account_id)
        )
    if status_filter is not None:
        query = query.where(StandingOrder.status == status_filter)
    items, total = paginate(db, query, page)
    return Page(items=_orders_out(db, items), total=total, limit=page.limit, offset=page.offset)


@router.post(
    "/standing-orders",
    response_model=StandingOrderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Set up a standing order",
)
def create_standing_order(
    body: StandingOrderCreate,
    db: DbSession,
    actor: Authorized(Permission.ACCOUNTS_TRANSACT),
) -> StandingOrderOut:
    order = service.create_standing_order(
        db,
        debtor=_account(db, body.debtor_account_number),
        creditor=_account(db, body.creditor_account_number),
        amount=body.amount,
        frequency=body.frequency,
        first_date=body.first_date,
        end_date=body.end_date,
        reference=body.reference,
        actor_id=actor.id,
    )
    return _orders_out(db, [order])[0]


@router.post(
    "/standing-orders/{order_id}/cancel",
    response_model=StandingOrderOut,
    summary="Cancel a standing order",
)
def cancel_standing_order(
    order_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.ACCOUNTS_TRANSACT)
) -> StandingOrderOut:
    order = service.cancel_standing_order(db, service.get_standing_order(db, order_id), actor.id)
    return _orders_out(db, [order])[0]


@router.get("/statements", response_model=Page[StatementOut], summary="Account statements")
def list_statements(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.ACCOUNTS_READ),
    account_id: uuid.UUID | None = None,
) -> Page[StatementOut]:
    query = select(AccountStatement).order_by(
        AccountStatement.period_start.desc(), AccountStatement.statement_number.desc()
    )
    if account_id is not None:
        query = query.where(AccountStatement.account_id == account_id)
    items, total = paginate(db, query, page)
    return Page(items=_statements_out(db, items), total=total, limit=page.limit, offset=page.offset)


@router.get("/statements/{statement_id}", response_model=StatementDetail, summary="A statement")
def get_statement(
    statement_id: uuid.UUID, db: DbSession, _: Authorized(Permission.ACCOUNTS_READ)
) -> StatementDetail:
    statement = db.get(AccountStatement, statement_id)
    if statement is None:
        from app.core.errors import NotFoundError

        raise NotFoundError("Statement not found.")
    out = _statements_out(db, [statement])[0]
    return StatementDetail(**out.model_dump(), entries=service.statement_lines(db, statement))


@router.get("/month-ends", response_model=list[MonthEndOut], summary="Month-end runs")
def list_month_ends(db: DbSession, _: Authorized(Permission.ACCOUNTS_READ)):
    return list(
        db.execute(
            select(MonthEndRun).order_by(MonthEndRun.period_start.desc()).limit(24)
        ).scalars()
    )


@router.post(
    "/month-ends",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run month end (interest, fees, statements) as a background job",
)
def run_month_end(
    body: MonthEndRequest,
    db: DbSession,
    actor: Authorized(Permission.RETAIL_MANAGE),
    tasks: BackgroundTasks,
    factory: SessionFactory,
) -> JobOut:
    payload = {"period": body.period.isoformat()} if body.period else {}
    job = engine.enqueue(
        db, "retail.month_end", payload, created_by=actor.id, dedupe_key="retail.month_end"
    )
    record_audit_event(
        db,
        actor_id=actor.id,
        action="job.queued",
        entity_type="job",
        entity_id=job.id,
        metadata={"kind": job.kind, "payload": job.payload},
    )
    db.commit()
    engine.dispatch(tasks, factory, [job.id])
    return _job_out(job, {actor.id: actor.username})


@router.get("/summary", summary="Counts for the retail banking page")
def summary(db: DbSession, _: Authorized(Permission.ACCOUNTS_READ)) -> dict[str, int]:
    return {
        "overdrafts": db.execute(
            select(func.count()).where(Account.overdraft_limit > 0)
        ).scalar_one(),
        "active_standing_orders": db.execute(
            select(func.count()).where(StandingOrder.status == StandingOrderStatus.ACTIVE)
        ).scalar_one(),
        "statements": db.execute(select(func.count()).select_from(AccountStatement)).scalar_one(),
    }
