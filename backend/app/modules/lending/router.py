import uuid

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.idempotency import IdempotencyKey, RequiredIdempotencyKey, run_idempotent
from app.core.pagination import Page, PageParamsDep, paginate
from app.core.permissions import Permission
from app.modules.identity.dependencies import Authorized
from app.modules.identity.models import User
from app.modules.lending import service, servicing
from app.modules.lending.models import LoanServicingRun, LoanStatus
from app.modules.lending.schemas import (
    InstalmentOut,
    LoanOut,
    PayoffIn,
    PayoffQuote,
    RepaymentIn,
    ServicingRunIn,
    ServicingRunOut,
)

router = APIRouter(prefix="/loans", tags=["lending"])


@router.get("", response_model=Page[LoanOut], summary="List loans")
def list_loans(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.LOANS_READ),
    customer_id: uuid.UUID | None = None,
    status: LoanStatus | None = None,
    q: str | None = None,
) -> Page[LoanOut]:
    items, total = service.list_loans(db, page, customer_id=customer_id, status=status, q=q)
    return Page(
        items=service.loans_out(db, items), total=total, limit=page.limit, offset=page.offset
    )


# --- Servicing runs (declared before /{loan_id}) --------------------------------------------


def _run_out(db, run: LoanServicingRun) -> ServicingRunOut:
    username = db.execute(select(User.username).where(User.id == run.started_by)).scalar()
    return ServicingRunOut(
        id=run.id,
        run_number=run.run_number,
        as_of=run.as_of,
        started_by_username=username,
        summary=run.summary,
        created_at=run.created_at,
    )


@router.get(
    "/servicing-runs",
    response_model=Page[ServicingRunOut],
    summary="Servicing runs, latest first (the first one's as_of is the business date)",
)
def list_servicing_runs(
    db: DbSession, page: PageParamsDep, _: Authorized(Permission.LOANS_READ)
) -> Page[ServicingRunOut]:
    query = select(LoanServicingRun).order_by(LoanServicingRun.run_number.desc())
    items, total = paginate(db, query, page)
    return Page(
        items=[_run_out(db, r) for r in items], total=total, limit=page.limit, offset=page.offset
    )


@router.post(
    "/servicing-runs",
    response_model=ServicingRunOut,
    status_code=status.HTTP_201_CREATED,
    summary="Accrue and collect everything due up to a business date (never backwards)",
)
def start_servicing_run(
    body: ServicingRunIn,
    request: Request,
    db: DbSession,
    actor: Authorized(Permission.LOANS_SERVICE),
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
        operation=lambda: _run_out(db, servicing.run(db, body.as_of, actor)),
    )


# --- One loan --------------------------------------------------------------------------------


@router.get("/{loan_id}", response_model=LoanOut, summary="Get a loan")
def get_loan(loan_id: uuid.UUID, db: DbSession, _: Authorized(Permission.LOANS_READ)) -> LoanOut:
    return service.loans_out(db, [service.get_loan(db, loan_id)])[0]


@router.get("/{loan_id}/schedule", response_model=list[InstalmentOut], summary="Repayment schedule")
def get_schedule(
    loan_id: uuid.UUID, db: DbSession, _: Authorized(Permission.LOANS_READ)
) -> list[InstalmentOut]:
    loan = service.get_loan(db, loan_id)
    return [
        InstalmentOut(
            number=i.number,
            due_date=i.due_date,
            principal=i.principal,
            interest=i.interest,
            amount=i.amount,
            status=i.status,
            paid_on=i.paid_on,
        )
        for i in servicing.instalments_of(db, loan.id)
    ]


@router.get(
    "/{loan_id}/payoff-quote", response_model=PayoffQuote, summary="What an early payoff costs"
)
def get_payoff_quote(
    loan_id: uuid.UUID, db: DbSession, _: Authorized(Permission.LOANS_READ)
) -> PayoffQuote:
    loan = service.get_loan(db, loan_id)
    return PayoffQuote(**servicing.payoff_amount(db, loan), as_of=servicing.current_date(db))


@router.post(
    "/{loan_id}/repayments",
    response_model=LoanOut,
    summary="Repay overdue instalments from the borrower's account (Idempotency-Key required)",
)
def repay(
    loan_id: uuid.UUID,
    body: RepaymentIn,
    request: Request,
    db: DbSession,
    actor: Authorized(Permission.LOANS_REPAY),
    idempotency_key: RequiredIdempotencyKey,
):
    def operation() -> LoanOut:
        loan = servicing.repay_arrears(
            db, loan_id, actor, key=idempotency_key, instalments=body.instalments
        )
        return service.loans_out(db, [loan])[0]

    return run_idempotent(
        db,
        key=idempotency_key,
        actor_id=actor.id,
        method="POST",
        path=request.url.path,
        payload=body,
        status_code=status.HTTP_200_OK,
        operation=operation,
    )


@router.post(
    "/{loan_id}/payoff",
    response_model=LoanOut,
    summary="Pay the loan off early from the borrower's account (Idempotency-Key required)",
)
def pay_off(
    loan_id: uuid.UUID,
    request: Request,
    db: DbSession,
    actor: Authorized(Permission.LOANS_REPAY),
    idempotency_key: RequiredIdempotencyKey,
    body: PayoffIn | None = None,
):
    def operation() -> LoanOut:
        loan = servicing.payoff(db, loan_id, actor, key=idempotency_key)
        return service.loans_out(db, [loan])[0]

    return run_idempotent(
        db,
        key=idempotency_key,
        actor_id=actor.id,
        method="POST",
        path=request.url.path,
        payload=body or PayoffIn(),
        status_code=status.HTTP_200_OK,
        operation=operation,
    )
