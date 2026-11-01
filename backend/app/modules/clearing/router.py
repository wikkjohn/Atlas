"""Payments operations API (Phase 41)."""

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
from app.modules.accounts.models import Account
from app.modules.clearing import service
from app.modules.clearing.models import (
    BulkPaymentFile,
    ClearingBatch,
    OutgoingPayment,
    OutgoingStatus,
    PaymentRecall,
)
from app.modules.identity.dependencies import Authorized

router = APIRouter(prefix="/payment-ops", tags=["payments operations"])


class OutgoingOut(BaseModel):
    id: uuid.UUID
    payment_number: str
    account_number: str
    beneficiary_name: str
    beneficiary_bank: str
    beneficiary_account: str
    amount: int
    currency: str
    reference: str
    status: str
    high_value: bool
    bulk_file_id: uuid.UUID | None
    return_code: str | None
    reason: str | None
    settled_on: date | None
    created_at: datetime


class BatchOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    batch_number: str
    currency: str
    business_date: date
    payments: int
    total: int
    settled_count: int
    returned_count: int
    status: str
    created_at: datetime


class BulkOut(BaseModel):
    id: uuid.UUID
    file_number: str
    account_number: str
    file_name: str
    currency: str
    lines: list[dict]
    valid_count: int
    invalid_count: int
    valid_total: int
    status: str
    decision_note: str | None
    created_at: datetime


class RecallOut(BaseModel):
    id: uuid.UUID
    recall_number: str
    payment_number: str
    reason_code: str
    status: str
    outcome_note: str | None
    created_at: datetime


def _numbers(db, ids) -> dict[uuid.UUID, str]:
    ids = set(ids)
    if not ids:
        return {}
    return dict(db.execute(select(Account.id, Account.account_number)
                           .where(Account.id.in_(ids))).tuples().all())  # fmt: skip


def _outgoing_out(db, items: list[OutgoingPayment]) -> list[OutgoingOut]:
    numbers = _numbers(db, (p.debtor_account_id for p in items))
    return [
        OutgoingOut(
            id=p.id,
            payment_number=p.payment_number,
            account_number=numbers[p.debtor_account_id],
            beneficiary_name=p.beneficiary_name,
            beneficiary_bank=p.beneficiary_bank,
            beneficiary_account=p.beneficiary_account,
            amount=p.amount,
            currency=p.currency,
            reference=p.reference,
            status=p.status,
            high_value=p.high_value,
            bulk_file_id=p.bulk_file_id,
            return_code=p.return_code,
            reason=p.reason,
            settled_on=p.settled_on,
            created_at=p.created_at,
        )  # fmt: skip
        for p in items
    ]


def _bulk_out(db, b: BulkPaymentFile) -> BulkOut:
    number = _numbers(db, [b.account_id])[b.account_id]
    return BulkOut(
        id=b.id, file_number=b.file_number, account_number=number,
        file_name=b.file_name, currency=b.currency, lines=b.lines, valid_count=b.valid_count,
        invalid_count=b.invalid_count, valid_total=b.valid_total, status=b.status,
        decision_note=b.decision_note, created_at=b.created_at,
    )  # fmt: skip


def _recall_out(db, r: PaymentRecall) -> RecallOut:
    payment = service.get_outgoing(db, r.payment_id)
    return RecallOut(id=r.id, recall_number=r.recall_number, payment_number=payment.payment_number,
                     reason_code=r.reason_code, status=r.status, outcome_note=r.outcome_note,
                     created_at=r.created_at)  # fmt: skip


def _account(db, number: str) -> Account:
    account = service.find_account(db, number)
    if account is None:
        raise BusinessRuleViolation(f"No account {number}.")
    return account


# --- Outgoing payments ------------------------------------------------------------------------


class OutgoingIn(BaseModel):
    account_number: str = Field(min_length=1, max_length=34)
    beneficiary_name: str = Field(min_length=1, max_length=140)
    beneficiary_bank: str = Field(min_length=8, max_length=11)
    beneficiary_account: str = Field(min_length=1, max_length=34)
    amount: int = Field(gt=0)
    reference: str = Field(default="", max_length=140)


@router.get("/banks", summary="Synthetic banks reachable through clearing")
def banks(_: Authorized(Permission.PAYMENTS_READ)) -> list[dict]:
    return [{"code": code, "name": name} for code, name in service.BANKS.items()]


@router.get("/payments", response_model=Page[OutgoingOut], summary="Outgoing payments")
def list_outgoing(
    db: DbSession, page: PageParamsDep, _: Authorized(Permission.PAYMENTS_READ),
    status_filter: Annotated[OutgoingStatus | None, Query(alias="status")] = None,
) -> Page[OutgoingOut]:  # fmt: skip
    query = select(OutgoingPayment).order_by(OutgoingPayment.created_at.desc(),
                                             OutgoingPayment.payment_number.desc())  # fmt: skip
    if status_filter is not None:
        query = query.where(OutgoingPayment.status == status_filter)
    items, total = paginate(db, query, page)
    return Page(items=_outgoing_out(db, items), total=total, limit=page.limit, offset=page.offset)


@router.post("/payments", response_model=OutgoingOut, status_code=status.HTTP_201_CREATED,
             summary="A payment to another bank; high value waits for an approval")  # fmt: skip
def create_outgoing(body: OutgoingIn, db: DbSession,
                    actor: Authorized(Permission.ACCOUNTS_TRANSACT)):  # fmt: skip
    payment = service.create_outgoing(
        db, debtor=_account(db, body.account_number), beneficiary_name=body.beneficiary_name,
        beneficiary_bank=body.beneficiary_bank, beneficiary_account=body.beneficiary_account,
        amount=body.amount, reference=body.reference, initiated_by=actor.id,
    )  # fmt: skip
    return _outgoing_out(db, [payment])[0]


class Note(BaseModel):
    note: str = Field(default="Not approved", min_length=3, max_length=200)


@router.post("/payments/{payment_id}/approve", response_model=OutgoingOut,
             summary="Approve a high-value payment; not by the person who entered it")  # fmt: skip
def approve_outgoing(payment_id: uuid.UUID, db: DbSession,
                     actor: Authorized(Permission.PAYMENTS_APPROVE)):  # fmt: skip
    payment = service.approve_outgoing(db, service.get_outgoing(db, payment_id), actor.id)
    return _outgoing_out(db, [payment])[0]


@router.post("/payments/{payment_id}/reject", response_model=OutgoingOut, summary="Reject")
def reject_outgoing(payment_id: uuid.UUID, body: Note, db: DbSession,
                    actor: Authorized(Permission.PAYMENTS_APPROVE)):  # fmt: skip
    payment = service.reject_outgoing(db, service.get_outgoing(db, payment_id), actor.id,
                                      body.note)  # fmt: skip
    return _outgoing_out(db, [payment])[0]


# --- Clearing ---------------------------------------------------------------------------------


class CycleIn(BaseModel):
    currency: str = Field(min_length=3, max_length=3)


@router.get("/batches", response_model=Page[BatchOut], summary="Clearing batches")
def list_batches(db: DbSession, page: PageParamsDep, _: Authorized(Permission.PAYMENTS_READ)):
    query = select(ClearingBatch).order_by(ClearingBatch.created_at.desc(),
                                           ClearingBatch.batch_number.desc())  # fmt: skip
    items, total = paginate(db, query, page)
    return Page(items=[BatchOut.model_validate(b) for b in items], total=total,
                limit=page.limit, offset=page.offset)  # fmt: skip


@router.post("/cycles", summary="Run a clearing cycle for a currency: submit and settle")
def run_cycle(body: CycleIn, db: DbSession,
              actor: Authorized(Permission.PAYMENTS_OPERATE)) -> dict:  # fmt: skip
    batch = service.run_cycle(db, body.currency, actor.id)
    return {"batch": BatchOut.model_validate(batch).model_dump(mode="json") if batch else None}


# --- Bulk files -------------------------------------------------------------------------------


class BulkLine(BaseModel):
    name: str = Field(default="", max_length=140)
    bank: str = Field(default="", max_length=11)
    account: str = Field(default="", max_length=34)
    amount: int | None = None
    reference: str = Field(default="", max_length=140)


class BulkIn(BaseModel):
    account_number: str = Field(min_length=1, max_length=34)
    file_name: str = Field(default="bulk", max_length=140)
    lines: list[BulkLine] = Field(min_length=1, max_length=service.MAX_BULK_LINES)


@router.get("/bulk", response_model=Page[BulkOut], summary="Bulk payment files")
def list_bulk(db: DbSession, page: PageParamsDep, _: Authorized(Permission.PAYMENTS_READ)):
    query = select(BulkPaymentFile).order_by(BulkPaymentFile.created_at.desc(),
                                             BulkPaymentFile.file_number.desc())  # fmt: skip
    items, total = paginate(db, query, page)
    return Page(items=[_bulk_out(db, b) for b in items], total=total, limit=page.limit,
                offset=page.offset)  # fmt: skip


@router.post("/bulk", response_model=BulkOut, status_code=status.HTTP_201_CREATED,
             summary="Receive a bulk file; every line validated")  # fmt: skip
def receive_bulk(body: BulkIn, db: DbSession, actor: Authorized(Permission.ACCOUNTS_TRANSACT)):
    bulk = service.receive_bulk(
        db, account=_account(db, body.account_number), file_name=body.file_name,
        lines=[line.model_dump() for line in body.lines], received_by=actor.id,
    )  # fmt: skip
    return _bulk_out(db, bulk)


@router.post("/bulk/{bulk_id}/release", response_model=BulkOut,
             summary="Approve: the valid lines become payments; not by the receiver")  # fmt: skip
def release_bulk(bulk_id: uuid.UUID, db: DbSession,
                 actor: Authorized(Permission.PAYMENTS_APPROVE)):  # fmt: skip
    bulk = service.get_bulk(db, bulk_id)
    service.release_bulk(db, bulk, actor.id)
    return _bulk_out(db, service.get_bulk(db, bulk_id))


@router.post("/bulk/{bulk_id}/reject", response_model=BulkOut, summary="Reject the file")
def reject_bulk(bulk_id: uuid.UUID, body: Note, db: DbSession,
                actor: Authorized(Permission.PAYMENTS_APPROVE)):  # fmt: skip
    return _bulk_out(db, service.reject_bulk(db, service.get_bulk(db, bulk_id), actor.id,
                                             body.note))  # fmt: skip


# --- Recalls ----------------------------------------------------------------------------------


class RecallIn(BaseModel):
    payment_number: str = Field(min_length=1, max_length=20)
    reason_code: Literal["DUPL", "FRAD", "TECH", "CUST"]


@router.get("/recalls", response_model=Page[RecallOut], summary="Recalls")
def list_recalls(db: DbSession, page: PageParamsDep, _: Authorized(Permission.PAYMENTS_READ)):
    query = select(PaymentRecall).order_by(PaymentRecall.created_at.desc(),
                                           PaymentRecall.recall_number.desc())  # fmt: skip
    items, total = paginate(db, query, page)
    return Page(items=[_recall_out(db, r) for r in items], total=total, limit=page.limit,
                offset=page.offset)  # fmt: skip


@router.post("/recalls", response_model=RecallOut, status_code=status.HTTP_201_CREATED,
             summary="Ask for a payment back")  # fmt: skip
def request_recall(body: RecallIn, db: DbSession,
                   actor: Authorized(Permission.ACCOUNTS_TRANSACT)):  # fmt: skip
    payment = service.find_outgoing(db, body.payment_number)
    if payment is None:
        raise BusinessRuleViolation(f"No outgoing payment {body.payment_number}.")
    return _recall_out(db, service.request_recall(db, payment, body.reason_code, actor.id))


@router.post("/recalls/{recall_id}/approve", response_model=RecallOut,
             summary="Approve: cancel before clearing, or ask the beneficiary's bank")  # fmt: skip
def approve_recall(recall_id: uuid.UUID, db: DbSession,
                   actor: Authorized(Permission.PAYMENTS_APPROVE)):  # fmt: skip
    return _recall_out(db, service.approve_recall(db, service.get_recall(db, recall_id), actor.id))


@router.post("/recalls/{recall_id}/withdraw", response_model=RecallOut, summary="Withdraw")
def withdraw_recall(recall_id: uuid.UUID, db: DbSession,
                    actor: Authorized(Permission.PAYMENTS_APPROVE)):  # fmt: skip
    return _recall_out(db, service.withdraw_recall(db, service.get_recall(db, recall_id),
                                                   actor.id))  # fmt: skip


@router.post("/recalls/{recall_id}/resolve", response_model=RecallOut,
             summary="Record the beneficiary bank's answer to a sent recall")  # fmt: skip
def resolve_recall(recall_id: uuid.UUID, db: DbSession,
                   actor: Authorized(Permission.PAYMENTS_OPERATE)):  # fmt: skip
    return _recall_out(db, service.resolve_recall(db, service.get_recall(db, recall_id), actor.id))


@router.get("/summary/counts", summary="Counts for the payments operations page")
def summary(db: DbSession, _: Authorized(Permission.PAYMENTS_READ)) -> dict:
    return service.summary(db)
