"""Payments operations services (Phase 41): outgoing payments, clearing cycles, bulk payment
files and recalls."""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.modules.accounts import service as accounts
from app.modules.accounts.models import Account, AccountStatus
from app.modules.clearing.models import (
    BATCH_SEQUENCE,
    BULK_SEQUENCE,
    OUTGOING_SEQUENCE,
    RECALL_REASONS,
    RECALL_SEQUENCE,
    BatchStatus,
    BulkPaymentFile,
    BulkStatus,
    ClearingBatch,
    OutgoingPayment,
    OutgoingStatus,
    PaymentRecall,
    RecallStatus,
)
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, LedgerAccount, LedgerAccountType
from app.modules.payments import service as payments

# Synthetic banks reachable through the simulated clearing system (names invented).
BANKS = {
    "NBKAGB22": "Northbank Retail (synthetic)",
    "RIVRUS33": "Riverside Savings (synthetic)",
    "ALPEDEFF": "Alpenland Sparkasse (synthetic)",
    "KITSJPJT": "Kitsune Shinkin (synthetic)",
    "HARBSGSG": "Harbourfront Bank (synthetic)",
    "LACBFRPP": "Lac Bleu Banque (synthetic)",
}
MAX_BULK_LINES = 500
# How long after settlement the beneficiary's bank still returns a recalled payment, by
# reason (days).
RECALL_WINDOWS = {"DUPL": 10, "TECH": 10, "CUST": 5, "FRAD": 3}


# --- Beneficiary accounts ---------------------------------------------------------------------


def check_digits(base: str) -> str:
    """The two check digits of a 12-digit synthetic account number: the number mod 97."""
    return f"{int(base) % 97:02d}"


def account_number(base: str) -> str:
    return base + check_digits(base)


def validate_beneficiary(bank: str, account: str) -> str | None:
    """None if the bank and account are acceptable, else why not."""
    if bank not in BANKS:
        return f"Unknown beneficiary bank {bank}."
    if len(account) != 14 or not account.isdigit():
        return "The beneficiary account is 14 digits."
    if account[12:] != check_digits(account[:12]):
        return "The beneficiary account's check digits are wrong."
    return None


def closed_at_beneficiary_bank(account: str) -> bool:
    """The simulated beneficiary banks have closed every account whose number (before the
    check digits) ends in 00: payments to them are returned at settlement (code AC04)."""
    return account[10:12] == "00"


# --- Ledger -----------------------------------------------------------------------------------


def clearing_account(db: Session, currency: str) -> LedgerAccount:
    return ledger.ensure_ledger_account(
        db, code=f"CLEARING-OUT-{currency}", name=f"Outgoing clearing ({currency})",
        account_type=LedgerAccountType.LIABILITY, currency=currency,
    )  # fmt: skip


def _post(db: Session, *, key: str, currency: str, memo: str, lines: list[tuple], actor_id,
          today: date) -> None:  # fmt: skip
    ledger.post_entry(
        db, idempotency_key=key, currency=currency, description=memo, source="clearing",
        lines=[ledger.LineSpec(account_id, direction, amount, memo[:200])
               for account_id, direction, amount in lines if amount],
        actor_id=actor_id, effective_date=today,
    )  # fmt: skip


def _audit(db, actor_id, action: str, entity_type: str, entity_id, **metadata) -> None:
    record_audit_event(db, actor_id=actor_id, action=action, entity_type=entity_type,
                       entity_id=entity_id, metadata=metadata)  # fmt: skip


# --- Outgoing payments ------------------------------------------------------------------------


def find_account(db: Session, number: str) -> Account | None:
    return accounts.find_account(db, number.strip().upper())


def _validate_line(db: Session, debtor: Account, line: dict[str, Any], today: date) -> str | None:
    error = validate_beneficiary(str(line.get("bank", "")), str(line.get("account", "")))
    if error:
        return error
    amount = line.get("amount")
    if not isinstance(amount, int) or amount <= 0:
        return "The amount must be a positive whole number of minor units."
    _, limit = payments.limits_for(db, debtor, today)
    if amount > limit:
        return f"The amount is above the {limit} payment limit."
    if not str(line.get("name", "")).strip():
        return "The beneficiary's name is missing."
    return None


def create_outgoing(
    db: Session, *, debtor: Account, beneficiary_name: str, beneficiary_bank: str,
    beneficiary_account: str, amount: int, reference: str, initiated_by: uuid.UUID,
    today: date | None = None, bulk_file: BulkPaymentFile | None = None,
) -> OutgoingPayment:  # fmt: skip
    """A payment to another bank. High value waits for a second person's approval, unless it
    comes from an approved bulk file; otherwise it waits for the next clearing cycle."""
    today = today or datetime.now(UTC).date()
    if debtor.status != AccountStatus.OPEN:
        raise BusinessRuleViolation(f"The account is {debtor.status}.")
    line = {"name": beneficiary_name, "bank": beneficiary_bank.strip().upper(),
            "account": beneficiary_account.strip(), "amount": amount}  # fmt: skip
    error = _validate_line(db, debtor, line, today)
    if error:
        raise BusinessRuleViolation(error, {"rule": "beneficiary_or_amount"})
    threshold, _ = payments.limits_for(db, debtor, today)
    high_value = amount >= threshold
    number = f"OPY-{db.execute(OUTGOING_SEQUENCE.next_value()).scalar_one():08d}"
    status = (
        OutgoingStatus.AWAITING_APPROVAL
        if high_value and bulk_file is None
        else OutgoingStatus.PENDING
    )
    payment = OutgoingPayment(
        payment_number=number, debtor_account_id=debtor.id,
        beneficiary_name=beneficiary_name.strip()[:140], beneficiary_bank=line["bank"],
        beneficiary_account=line["account"], amount=amount, currency=debtor.currency,
        reference=(reference.strip() or "Payment")[:140], status=status.value,
        high_value=high_value, bulk_file_id=bulk_file.id if bulk_file else None,
        initiated_by=initiated_by,
        approved_by=bulk_file.approved_by if bulk_file else None,
    )  # fmt: skip
    db.add(payment)
    db.flush()
    _audit(db, initiated_by, "clearing.payment_created", "outgoing_payment", payment.id,
           payment_number=number, amount=amount, high_value=high_value)  # fmt: skip
    return payment


def get_outgoing(db: Session, payment_id: uuid.UUID, *, for_update: bool = False):
    query = select(OutgoingPayment).where(OutgoingPayment.id == payment_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    payment = db.execute(query).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("Outgoing payment not found.")
    return payment


def find_outgoing(db: Session, number: str) -> OutgoingPayment | None:
    return db.execute(
        select(OutgoingPayment).where(OutgoingPayment.payment_number == number.strip().upper())
    ).scalar_one_or_none()


def _require(payment: OutgoingPayment, *statuses: OutgoingStatus) -> None:
    if payment.status not in statuses:
        raise ConflictError(f"{payment.payment_number} is {payment.status}.")


def approve_outgoing(db: Session, payment: OutgoingPayment, actor_id: uuid.UUID):
    payment = get_outgoing(db, payment.id, for_update=True)
    _require(payment, OutgoingStatus.AWAITING_APPROVAL)
    if actor_id == payment.initiated_by:
        raise BusinessRuleViolation("Four-eyes rule: the person who entered the payment cannot "
                                    "approve it.", {"rule": "four_eyes"})  # fmt: skip
    payment.status, payment.approved_by = OutgoingStatus.PENDING.value, actor_id
    db.flush()
    _audit(db, actor_id, "clearing.payment_approved", "outgoing_payment", payment.id,
           payment_number=payment.payment_number)  # fmt: skip
    return payment


def reject_outgoing(db: Session, payment: OutgoingPayment, actor_id: uuid.UUID | None,
                    reason: str) -> OutgoingPayment:  # fmt: skip
    payment = get_outgoing(db, payment.id, for_update=True)
    _require(payment, OutgoingStatus.AWAITING_APPROVAL, OutgoingStatus.PENDING)
    if actor_id is not None and actor_id == payment.initiated_by:
        raise BusinessRuleViolation("Four-eyes rule: the person who entered the payment cannot "
                                    "reject it.", {"rule": "four_eyes"})  # fmt: skip
    payment.status, payment.reason = OutgoingStatus.REJECTED.value, reason.strip()[:200]
    payment.closed_at = datetime.now(UTC)
    db.flush()
    _audit(db, actor_id, "clearing.payment_rejected", "outgoing_payment", payment.id,
           payment_number=payment.payment_number, reason=payment.reason)  # fmt: skip
    return payment


# --- Clearing cycles --------------------------------------------------------------------------


def submit_batch(db: Session, currency: str, actor_id: uuid.UUID | None,
                 *, today: date | None = None) -> ClearingBatch | None:  # fmt: skip
    """A clearing cycle for one currency: every pending payment goes into a batch and its
    payer is debited into clearing suspense. A payer who cannot pay any more has that
    payment rejected (code AM04) instead. Returns None when nothing is pending."""
    today = today or datetime.now(UTC).date()
    currency = currency.strip().upper()
    pending = list(
        db.execute(
            select(OutgoingPayment)
            .where(OutgoingPayment.currency == currency,
                   OutgoingPayment.status == OutgoingStatus.PENDING)
            .order_by(OutgoingPayment.created_at, OutgoingPayment.payment_number)
            .with_for_update()
        ).scalars()
    )  # fmt: skip
    if not pending:
        return None
    number = f"CLB-{db.execute(BATCH_SEQUENCE.next_value()).scalar_one():07d}"
    batch = ClearingBatch(batch_number=number, currency=currency, business_date=today,
                          payments=0, total=0, status=BatchStatus.SUBMITTED.value,
                          run_by=actor_id)  # fmt: skip
    db.add(batch)
    db.flush()
    suspense = clearing_account(db, currency)
    # Every payer locked up front in id order, the same order internal transfers lock in, so
    # a cycle cannot deadlock with them (PR #32 review); payments still go oldest first.
    debtors = payments._lock_accounts(db, sorted({p.debtor_account_id for p in pending}))
    for payment in pending:
        debtor = debtors[payment.debtor_account_id]
        if debtor.status != AccountStatus.OPEN or payment.amount > accounts.available(db, debtor):
            payment.status, payment.return_code = OutgoingStatus.REJECTED.value, "AM04"
            payment.reason, payment.closed_at = "Insufficient funds at clearing.", datetime.now(UTC)
            continue
        _post(db, key=f"clearing-submit:{payment.payment_number}", currency=currency,
              memo=f"{payment.payment_number} to {payment.beneficiary_bank} {payment.reference}",
              lines=[(debtor.ledger_account_id, Direction.DEBIT, payment.amount),
                     (suspense.id, Direction.CREDIT, payment.amount)],
              actor_id=actor_id, today=today)  # fmt: skip
        payment.status, payment.batch_id = OutgoingStatus.IN_CLEARING.value, batch.id
        batch.payments += 1
        batch.total += payment.amount
    db.flush()
    _audit(db, actor_id, "clearing.batch_submitted", "clearing_batch", batch.id,
           batch_number=number, payments=batch.payments, total=batch.total)  # fmt: skip
    return batch


def get_batch(db: Session, batch_id: uuid.UUID, *, for_update: bool = False) -> ClearingBatch:
    query = select(ClearingBatch).where(ClearingBatch.id == batch_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    batch = db.execute(query).scalar_one_or_none()
    if batch is None:
        raise NotFoundError("Clearing batch not found.")
    return batch


def settle_batch(db: Session, batch: ClearingBatch, actor_id: uuid.UUID | None,
                 *, today: date | None = None) -> ClearingBatch:  # fmt: skip
    """The clearing system's answer: payments to accounts the beneficiary banks have closed
    come back (AC04) and are refunded to the payer; the rest are paid out of the bank's
    cash account."""
    today = today or datetime.now(UTC).date()
    batch = get_batch(db, batch.id, for_update=True)
    if batch.status != BatchStatus.SUBMITTED:
        raise ConflictError(f"{batch.batch_number} is {batch.status}.")
    suspense = clearing_account(db, batch.currency)
    cash = ledger.cash_account(db, batch.currency)
    items = list(
        db.execute(
            select(OutgoingPayment).where(OutgoingPayment.batch_id == batch.id,
                                          OutgoingPayment.status == OutgoingStatus.IN_CLEARING)
            .with_for_update()
        ).scalars()
    )  # fmt: skip
    for payment in items:
        if closed_at_beneficiary_bank(payment.beneficiary_account):
            debtor = accounts.get_account(db, payment.debtor_account_id)
            _post(db, key=f"clearing-return:{payment.payment_number}", currency=batch.currency,
                  memo=f"Returned {payment.payment_number}: account closed (AC04)",
                  lines=[(suspense.id, Direction.DEBIT, payment.amount),
                         (debtor.ledger_account_id, Direction.CREDIT, payment.amount)],
                  actor_id=actor_id, today=today)  # fmt: skip
            payment.status, payment.return_code = OutgoingStatus.RETURNED.value, "AC04"
            payment.reason = "The beneficiary's bank has closed the account."
            payment.closed_at = datetime.now(UTC)
            batch.returned_count += 1
        else:
            # One entry per payment: a batch total could exceed the ledger's line limit
            # where each payment does not (PR #32 review).
            _post(db, key=f"clearing-settle:{payment.payment_number}", currency=batch.currency,
                  memo=f"Settlement {batch.batch_number}: {payment.payment_number}",
                  lines=[(suspense.id, Direction.DEBIT, payment.amount),
                         (cash.id, Direction.CREDIT, payment.amount)],
                  actor_id=actor_id, today=today)  # fmt: skip
            payment.status, payment.settled_on = OutgoingStatus.SETTLED.value, today
            batch.settled_count += 1
    batch.status, batch.settled_at = BatchStatus.SETTLED.value, datetime.now(UTC)
    db.flush()
    _audit(db, actor_id, "clearing.batch_settled", "clearing_batch", batch.id,
           batch_number=batch.batch_number, settled=batch.settled_count,
           returned=batch.returned_count)  # fmt: skip
    return batch


def run_cycle(db: Session, currency: str, actor_id: uuid.UUID | None,
              *, today: date | None = None) -> ClearingBatch | None:  # fmt: skip
    """Submit and settle one currency's clearing cycle."""
    batch = submit_batch(db, currency, actor_id, today=today)
    return settle_batch(db, batch, actor_id, today=today) if batch else None


# --- Bulk payment files -----------------------------------------------------------------------


def receive_bulk(
    db: Session, *, account: Account, file_name: str, lines: list[dict[str, Any]],
    received_by: uuid.UUID, today: date | None = None,
) -> BulkPaymentFile:  # fmt: skip
    """Validate every line; the valid lines must not add up to more than the account can
    pay. The file then waits for a second person's approval."""
    today = today or datetime.now(UTC).date()
    if account.status != AccountStatus.OPEN:
        raise BusinessRuleViolation(f"The account is {account.status}.")
    if not 1 <= len(lines) <= MAX_BULK_LINES:
        raise BusinessRuleViolation(f"A bulk file has 1 to {MAX_BULK_LINES} lines.")
    checked, total, valid = [], 0, 0
    for index, raw in enumerate(lines, start=1):
        line = {"line": index, "name": str(raw.get("name", ""))[:140],
                "bank": str(raw.get("bank", "")).strip().upper(),
                "account": str(raw.get("account", "")).strip(), "amount": raw.get("amount"),
                "reference": str(raw.get("reference", ""))[:140]}  # fmt: skip
        error = _validate_line(db, account, line, today)
        if error:
            line["error"] = error
        else:
            valid += 1
            total += line["amount"]
        checked.append(line)
    if valid == 0:
        raise BusinessRuleViolation("No line of the file is valid.", {"rule": "no_valid_lines"})
    if total > accounts.available(db, account):
        raise BusinessRuleViolation(
            f"The valid lines total {total}, more than the account can pay.",
            {"rule": "insufficient_funds", "total": total},
        )  # fmt: skip
    number = f"BLK-{db.execute(BULK_SEQUENCE.next_value()).scalar_one():07d}"
    bulk = BulkPaymentFile(
        file_number=number, account_id=account.id, file_name=file_name.strip()[:140] or "bulk",
        currency=account.currency, lines=checked, valid_count=valid,
        invalid_count=len(checked) - valid, valid_total=total,
        status=BulkStatus.RECEIVED.value, received_by=received_by,
    )  # fmt: skip
    db.add(bulk)
    db.flush()
    _audit(db, received_by, "clearing.bulk_received", "bulk_payment_file", bulk.id,
           file_number=number, valid=valid, invalid=bulk.invalid_count, total=total)  # fmt: skip
    return bulk


def get_bulk(db: Session, bulk_id: uuid.UUID, *, for_update: bool = False) -> BulkPaymentFile:
    query = select(BulkPaymentFile).where(BulkPaymentFile.id == bulk_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    bulk = db.execute(query).scalar_one_or_none()
    if bulk is None:
        raise NotFoundError("Bulk payment file not found.")
    return bulk


def release_bulk(db: Session, bulk: BulkPaymentFile, actor_id: uuid.UUID,
                 *, today: date | None = None) -> list[OutgoingPayment]:  # fmt: skip
    """A second person approves the file: each valid line becomes an outgoing payment waiting
    for clearing (the file's approval covers high-value lines)."""
    bulk = get_bulk(db, bulk.id, for_update=True)
    if bulk.status != BulkStatus.RECEIVED:
        raise ConflictError(f"{bulk.file_number} is {bulk.status}.")
    if actor_id == bulk.received_by:
        raise BusinessRuleViolation("Four-eyes rule: the person who received the file cannot "
                                    "approve it.", {"rule": "four_eyes"})  # fmt: skip
    account = accounts.get_account(db, bulk.account_id, for_update=True)
    if bulk.valid_total > accounts.available(db, account):
        raise BusinessRuleViolation("The account can no longer pay the file.",
                                    {"rule": "insufficient_funds"})  # fmt: skip
    bulk.status, bulk.approved_by = BulkStatus.RELEASED.value, actor_id
    bulk.decided_at = datetime.now(UTC)
    db.flush()
    created = [
        create_outgoing(db, debtor=account, beneficiary_name=line["name"],
                        beneficiary_bank=line["bank"], beneficiary_account=line["account"],
                        amount=line["amount"],
                        reference=line["reference"] or f"{bulk.file_number}/{line['line']}",
                        initiated_by=bulk.received_by, today=today, bulk_file=bulk)
        for line in bulk.lines if "error" not in line
    ]  # fmt: skip
    _audit(db, actor_id, "clearing.bulk_released", "bulk_payment_file", bulk.id,
           file_number=bulk.file_number, payments=len(created))  # fmt: skip
    return created


def reject_bulk(db: Session, bulk: BulkPaymentFile, actor_id: uuid.UUID, note: str):
    bulk = get_bulk(db, bulk.id, for_update=True)
    if bulk.status != BulkStatus.RECEIVED:
        raise ConflictError(f"{bulk.file_number} is {bulk.status}.")
    if actor_id == bulk.received_by:
        raise BusinessRuleViolation("Four-eyes rule: the person who received the file cannot "
                                    "reject it.", {"rule": "four_eyes"})  # fmt: skip
    bulk.status, bulk.approved_by = BulkStatus.REJECTED.value, actor_id
    bulk.decision_note, bulk.decided_at = note.strip()[:200], datetime.now(UTC)
    db.flush()
    _audit(db, actor_id, "clearing.bulk_rejected", "bulk_payment_file", bulk.id,
           file_number=bulk.file_number, note=bulk.decision_note)  # fmt: skip
    return bulk


# --- Recalls ----------------------------------------------------------------------------------


def request_recall(db: Session, payment: OutgoingPayment, reason_code: str,
                   requested_by: uuid.UUID) -> PaymentRecall:  # fmt: skip
    """Ask for a payment back. Not while it is in a clearing batch."""
    payment = get_outgoing(db, payment.id, for_update=True)
    if reason_code not in RECALL_REASONS:
        raise BusinessRuleViolation(f"Unknown recall reason {reason_code}.")
    _require(payment, OutgoingStatus.AWAITING_APPROVAL, OutgoingStatus.PENDING,
             OutgoingStatus.SETTLED)  # fmt: skip
    open_recall = db.execute(
        select(PaymentRecall.recall_number).where(
            PaymentRecall.payment_id == payment.id,
            PaymentRecall.status.in_([RecallStatus.REQUESTED, RecallStatus.SENT]),
        )
    ).scalar_one_or_none()  # fmt: skip
    if open_recall:
        raise ConflictError(f"{open_recall} is already open for {payment.payment_number}.")
    number = f"RCL-{db.execute(RECALL_SEQUENCE.next_value()).scalar_one():07d}"
    recall = PaymentRecall(
        recall_number=number, payment_id=payment.id, reason_code=reason_code,
        status=RecallStatus.REQUESTED.value, requested_by=requested_by,
    )  # fmt: skip
    db.add(recall)
    db.flush()
    _audit(db, requested_by, "clearing.recall_requested", "payment_recall", recall.id,
           recall_number=number, payment_number=payment.payment_number,
           reason=reason_code)  # fmt: skip
    return recall


def get_recall(db: Session, recall_id: uuid.UUID, *, for_update: bool = False) -> PaymentRecall:
    query = select(PaymentRecall).where(PaymentRecall.id == recall_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    recall = db.execute(query).scalar_one_or_none()
    if recall is None:
        raise NotFoundError("Recall not found.")
    return recall


def approve_recall(db: Session, recall: PaymentRecall, actor_id: uuid.UUID,
                   *, now: datetime | None = None) -> PaymentRecall:  # fmt: skip
    """A second person approves. A payment not yet cleared is cancelled at once; a settled
    one is sent to the beneficiary's bank for an answer."""
    now = now or datetime.now(UTC)
    recall = get_recall(db, recall.id, for_update=True)
    if recall.status != RecallStatus.REQUESTED:
        raise ConflictError(f"{recall.recall_number} is {recall.status}.")
    if actor_id == recall.requested_by:
        raise BusinessRuleViolation("Four-eyes rule: the person who asked for the recall "
                                    "cannot approve it.", {"rule": "four_eyes"})  # fmt: skip
    payment = get_outgoing(db, recall.payment_id, for_update=True)
    recall.approved_by = actor_id
    if payment.status in (OutgoingStatus.AWAITING_APPROVAL, OutgoingStatus.PENDING):
        payment.status, payment.reason = OutgoingStatus.RECALLED.value, "Recalled before clearing."
        payment.closed_at = now
        recall.status, recall.decided_at = RecallStatus.ACCEPTED.value, now
        recall.outcome_note = "Cancelled before clearing; nothing had left the bank."
    elif payment.status == OutgoingStatus.SETTLED:
        recall.status = RecallStatus.SENT.value
    else:
        raise ConflictError(f"{payment.payment_number} is {payment.status}.")
    db.flush()
    _audit(db, actor_id, "clearing.recall_approved", "payment_recall", recall.id,
           recall_number=recall.recall_number, status=recall.status)  # fmt: skip
    return recall


def withdraw_recall(db: Session, recall: PaymentRecall, actor_id: uuid.UUID) -> PaymentRecall:
    recall = get_recall(db, recall.id, for_update=True)
    if recall.status != RecallStatus.REQUESTED:
        raise ConflictError(f"{recall.recall_number} is {recall.status}.")
    recall.status, recall.decided_at = RecallStatus.WITHDRAWN.value, datetime.now(UTC)
    recall.approved_by = None
    db.flush()
    _audit(db, actor_id, "clearing.recall_withdrawn", "payment_recall", recall.id,
           recall_number=recall.recall_number)  # fmt: skip
    return recall


def resolve_recall(db: Session, recall: PaymentRecall, actor_id: uuid.UUID | None,
                   *, today: date | None = None) -> PaymentRecall:  # fmt: skip
    """The beneficiary's bank answers a sent recall: it returns the money while the recall
    is within the reason's window after settlement (10 days for duplicates and technical
    errors, 5 for customer requests, 3 for fraud), otherwise it refuses."""
    today = today or datetime.now(UTC).date()
    recall = get_recall(db, recall.id, for_update=True)
    if recall.status != RecallStatus.SENT:
        raise ConflictError(f"{recall.recall_number} is {recall.status}.")
    payment = get_outgoing(db, recall.payment_id, for_update=True)
    days = (today - payment.settled_on).days if payment.settled_on else 0
    window = RECALL_WINDOWS[recall.reason_code]
    if days <= window:
        debtor = accounts.get_account(db, payment.debtor_account_id, for_update=True)
        cash = ledger.cash_account(db, payment.currency)
        _post(db, key=f"clearing-recall:{recall.recall_number}", currency=payment.currency,
              memo=f"Recall {recall.recall_number}: {payment.payment_number} returned",
              lines=[(cash.id, Direction.DEBIT, payment.amount),
                     (debtor.ledger_account_id, Direction.CREDIT, payment.amount)],
              actor_id=actor_id, today=today)  # fmt: skip
        payment.status, payment.reason = OutgoingStatus.RECALLED.value, "Returned after a recall."
        payment.closed_at = datetime.now(UTC)
        recall.status = RecallStatus.ACCEPTED.value
        recall.outcome_note = f"Returned by the beneficiary's bank, {days} days after settlement."
    else:
        recall.status = RecallStatus.REFUSED.value
        recall.outcome_note = (f"Refused: {days} days after settlement, beyond the {window}-day "
                               f"window for {RECALL_REASONS[recall.reason_code]}.")  # fmt: skip
    recall.decided_at = datetime.now(UTC)
    db.flush()
    _audit(db, actor_id, "clearing.recall_resolved", "payment_recall", recall.id,
           recall_number=recall.recall_number, status=recall.status)  # fmt: skip
    return recall


def refundable_payment(db: Session, account_id: uuid.UUID, today: date) -> str | None:
    """An outgoing payment from the account that could still credit it back: not yet
    settled, settled within the longest recall window, or with an open recall."""
    from datetime import timedelta

    since = today - timedelta(days=max(RECALL_WINDOWS.values()))
    live = (OutgoingStatus.AWAITING_APPROVAL, OutgoingStatus.PENDING, OutgoingStatus.IN_CLEARING)
    found = db.execute(
        select(OutgoingPayment.payment_number).where(
            OutgoingPayment.debtor_account_id == account_id,
            (OutgoingPayment.status.in_(live))
            | ((OutgoingPayment.status == OutgoingStatus.SETTLED)
               & (OutgoingPayment.settled_on >= since)),
        )
    ).scalars().first()  # fmt: skip
    if found:
        return found
    return db.execute(
        select(OutgoingPayment.payment_number)
        .join(PaymentRecall, PaymentRecall.payment_id == OutgoingPayment.id)
        .where(OutgoingPayment.debtor_account_id == account_id,
               PaymentRecall.status.in_([RecallStatus.REQUESTED, RecallStatus.SENT]))
    ).scalars().first()  # fmt: skip


def recall_profile(db: Session, recall: PaymentRecall, today: date) -> dict[str, Any]:
    """What a back-office officer weighs before sending a recall (Phase 42): the reason and
    how much of its window is left, the payment's size, whether a matching duplicate exists
    (same payer, beneficiary account and amount within three days), how often the payer has
    paid this beneficiary before, and the payer's other recalls in the last 90 days."""
    from datetime import timedelta

    payment = get_outgoing(db, recall.payment_id)
    window = RECALL_WINDOWS[recall.reason_code]
    days = (today - payment.settled_on).days if payment.settled_on else 0
    others = list(
        db.execute(
            select(OutgoingPayment).where(
                OutgoingPayment.debtor_account_id == payment.debtor_account_id,
                OutgoingPayment.id != payment.id,
            )
        ).scalars()
    )  # fmt: skip
    created = payment.settled_on or today

    def near(p: OutgoingPayment) -> bool:
        when = p.settled_on or created
        return abs((when - created).days) <= 3

    same_payee = [p for p in others if p.beneficiary_account == payment.beneficiary_account]
    duplicates = [p for p in same_payee if p.amount == payment.amount and near(p)
                  and p.status in (OutgoingStatus.SETTLED, OutgoingStatus.PENDING,
                                   OutgoingStatus.IN_CLEARING)]  # fmt: skip
    history = [p for p in same_payee if p.status == OutgoingStatus.SETTLED and p not in duplicates]
    since = today - timedelta(days=90)
    recent = [
        r for r, p in db.execute(
            select(PaymentRecall, OutgoingPayment)
            .join(OutgoingPayment, OutgoingPayment.id == PaymentRecall.payment_id)
            .where(OutgoingPayment.debtor_account_id == payment.debtor_account_id,
                   PaymentRecall.id != recall.id)
        ).all()
        if (p.settled_on or today) >= since
    ]  # fmt: skip
    return {
        "reason_code": recall.reason_code, "currency": payment.currency,
        "amount": payment.amount, "high_value": payment.high_value,
        "days_since_settlement": days, "window_days": window, "days_left": window - days,
        "duplicate_matches": len(duplicates), "payee_history": len(history),
        "payer_recalls_90d": len(recent),
        "payer_refused_90d": sum(r.status == RecallStatus.REFUSED for r in recent),
    }  # fmt: skip


def summary(db: Session) -> dict[str, Any]:
    def count(model, *where) -> int:
        return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()

    return {
        "awaiting_approval": count(OutgoingPayment,
                                   OutgoingPayment.status == OutgoingStatus.AWAITING_APPROVAL),
        "pending": count(OutgoingPayment, OutgoingPayment.status == OutgoingStatus.PENDING),
        "returned": count(OutgoingPayment, OutgoingPayment.status == OutgoingStatus.RETURNED),
        "bulk_received": count(BulkPaymentFile, BulkPaymentFile.status == BulkStatus.RECEIVED),
        "open_recalls": count(PaymentRecall, PaymentRecall.status.in_(
            [RecallStatus.REQUESTED, RecallStatus.SENT])),
    }  # fmt: skip
