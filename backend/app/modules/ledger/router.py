import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.errors import NotFoundError
from app.core.idempotency import REPLAY_HEADER, RequiredIdempotencyKey
from app.core.pagination import Page, PageParamsDep
from app.core.permissions import Permission
from app.modules.identity.dependencies import Authorized
from app.modules.identity.models import User
from app.modules.ledger import service
from app.modules.ledger.models import LedgerAccountType, LedgerReconciliation, ReconciliationMode
from app.modules.ledger.schemas import (
    JournalEntryCreate,
    JournalEntryOut,
    LedgerAccountCreate,
    LedgerAccountOut,
    ReconciliationReport,
    ReconciliationRunOut,
    ReversalCreate,
    StatementLineOut,
)

router = APIRouter(prefix="/ledger", tags=["ledger"])


def _entry_response(db, entry, replayed: bool) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
        content=service.entry_out(db, entry).model_dump(mode="json"),
        headers={REPLAY_HEADER: "true"} if replayed else None,
    )


@router.get("/accounts", response_model=Page[LedgerAccountOut], summary="Chart of accounts")
def list_ledger_accounts(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.LEDGER_READ),
    currency: Annotated[str | None, Query(pattern=r"^[A-Z]{3}$")] = None,
    account_type: LedgerAccountType | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    code_prefix: Annotated[
        str | None, Query(max_length=60, description="Codes starting with this, e.g. 1000-")
    ] = None,
) -> Page[LedgerAccountOut]:
    items, total = service.list_ledger_accounts(
        db, page, currency=currency, account_type=account_type, q=q, code_prefix=code_prefix
    )
    amounts = service.balances(db, items)
    return Page(
        items=[service.account_out(a, amounts[a.id]) for a in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/accounts",
    response_model=LedgerAccountOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a general-ledger account",
)
def create_ledger_account(
    body: LedgerAccountCreate, db: DbSession, _: Authorized(Permission.LEDGER_POST)
) -> LedgerAccountOut:
    account = service.ensure_ledger_account(
        db,
        code=body.code,
        name=body.name,
        account_type=body.account_type,
        currency=body.currency,
    )
    return service.account_out(account, service.balance(db, account))


@router.get(
    "/accounts/{ledger_account_id}", response_model=LedgerAccountOut, summary="Ledger account"
)
def get_ledger_account(
    ledger_account_id: uuid.UUID, db: DbSession, _: Authorized(Permission.LEDGER_READ)
) -> LedgerAccountOut:
    account = service.get_ledger_account(db, ledger_account_id)
    return service.account_out(account, service.balance(db, account))


@router.get(
    "/accounts/{ledger_account_id}/statement",
    response_model=Page[StatementLineOut],
    summary="Lines posted to a ledger account",
)
def get_statement(
    ledger_account_id: uuid.UUID,
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.LEDGER_READ),
) -> Page[StatementLineOut]:
    lines, total = service.statement(db, service.get_ledger_account(db, ledger_account_id), page)
    return Page(items=lines, total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/journal-entries", response_model=Page[JournalEntryOut], summary="Journal (newest first)"
)
def list_entries(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.LEDGER_READ),
    currency: Annotated[str | None, Query(pattern=r"^[A-Z]{3}$")] = None,
    source: Annotated[str | None, Query(max_length=50)] = None,
    ledger_account_id: uuid.UUID | None = None,
) -> Page[JournalEntryOut]:
    items, total = service.list_entries(
        db, page, currency=currency, source=source, ledger_account_id=ledger_account_id
    )
    return Page(
        items=[service.entry_out(db, e) for e in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/journal-entries",
    response_model=JournalEntryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Post a manual, balanced journal entry (Idempotency-Key required)",
)
def post_entry(
    body: JournalEntryCreate,
    db: DbSession,
    actor: Authorized(Permission.LEDGER_POST),
    idempotency_key: RequiredIdempotencyKey,
):
    entry, replayed = service.post_entry(
        db,
        idempotency_key=f"manual:{actor.id}:{idempotency_key}",
        currency=body.currency,
        description=body.description,
        source="manual",
        effective_date=body.effective_date,
        lines=[
            service.LineSpec(line.ledger_account_id, line.direction, line.amount, line.memo)
            for line in body.lines
        ],
        actor_id=actor.id,
    )
    return _entry_response(db, entry, replayed)


@router.get(
    "/journal-entries/{entry_id}", response_model=JournalEntryOut, summary="A journal entry"
)
def get_entry(
    entry_id: uuid.UUID, db: DbSession, _: Authorized(Permission.LEDGER_READ)
) -> JournalEntryOut:
    return service.entry_out(db, service.get_entry(db, entry_id))


@router.post(
    "/journal-entries/{entry_id}/reverse",
    response_model=JournalEntryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Reverse an entry with an opposite entry (Idempotency-Key required)",
)
def reverse_entry(
    entry_id: uuid.UUID,
    body: ReversalCreate,
    db: DbSession,
    actor: Authorized(Permission.LEDGER_POST),
    idempotency_key: RequiredIdempotencyKey,
):
    reversal, replayed = service.reverse_entry(
        db,
        entry_id,
        reason=body.reason,
        idempotency_key=f"reversal:{actor.id}:{idempotency_key}",
        actor_id=actor.id,
    )
    return _entry_response(db, reversal, replayed)


@router.post(
    "/reconciliation",
    response_model=ReconciliationReport,
    summary="Run the ledger reconciliation checks (the run is recorded and audited)",
)
def run_reconciliation(
    db: DbSession,
    actor: Authorized(Permission.LEDGER_READ),
    mode: Annotated[
        ReconciliationMode,
        Query(description="full: everything; incremental: what was posted since the last run"),
    ] = ReconciliationMode.FULL,
) -> ReconciliationReport:
    return service.reconcile(db, actor.id, mode)


def _run_out(db, run: LedgerReconciliation) -> ReconciliationRunOut:
    username = (
        db.execute(select(User.username).where(User.id == run.run_by)).scalar()
        if run.run_by
        else None
    )
    return ReconciliationRunOut(
        id=run.id,
        run_number=run.run_number,
        mode=run.mode,
        ok=run.ok,
        window_start=run.window_start,
        window_end=run.window_end,
        entries_checked=run.entries_checked,
        lines_checked=run.lines_checked,
        duration_ms=run.duration_ms,
        failed_checks=[c["name"] for c in run.report.get("checks", []) if not c["passed"]],
        run_by_username=username,
        created_at=run.created_at,
    )


@router.get(
    "/reconciliations",
    response_model=Page[ReconciliationRunOut],
    summary="Reconciliation history, latest first",
)
def list_reconciliations(
    db: DbSession, page: PageParamsDep, _: Authorized(Permission.LEDGER_READ)
) -> Page[ReconciliationRunOut]:
    items, total = service.list_reconciliations(db, page)
    return Page(
        items=[_run_out(db, r) for r in items], total=total, limit=page.limit, offset=page.offset
    )


@router.get(
    "/reconciliations/{run_id}",
    response_model=ReconciliationReport,
    summary="One recorded reconciliation report",
)
def get_reconciliation(
    run_id: uuid.UUID, db: DbSession, _: Authorized(Permission.LEDGER_READ)
) -> ReconciliationReport:
    run = db.get(LedgerReconciliation, run_id)
    if run is None:
        raise NotFoundError("Reconciliation run not found.")
    return ReconciliationReport.model_validate(
        {**run.report, "id": run.id, "run_number": run.run_number}
    )
