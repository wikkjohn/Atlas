"""Phase 41: payments operations — outgoing payments, clearing, bulk files and recalls."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError
from app.modules.accounts.models import AccountType
from app.modules.accounts.service import deposit
from app.modules.clearing import service as clearing
from app.modules.ledger import service as ledger
from app.modules.payments import service as payments
from tests.factories import auth, make_customer, make_staff, open_account

TODAY = date(2026, 7, 1)
OPEN = clearing.account_number("123456789012")  # a live beneficiary account
CLOSED = clearing.account_number("123456789000")  # closed at the beneficiary's bank


def _payer(db: Session, staff, balance: int = 5_000_000):
    customer = make_customer(db)
    account = open_account(db, staff, customer, AccountType.CURRENT)
    if balance:
        deposit(db, account.id, amount=balance, memo="Synthetic", actor_id=staff.employee.id,
                idempotency_key=f"clearing-{account.id}")  # fmt: skip
    return account


def _pay(db, staff, account, amount=100_000, beneficiary=OPEN, bank="NBKAGB22"):
    return clearing.create_outgoing(
        db, debtor=account, beneficiary_name="Synthetic Supplier Ltd", beneficiary_bank=bank,
        beneficiary_account=beneficiary, amount=amount, reference="Invoice 42",
        initiated_by=staff.employee.id, today=TODAY,
    )  # fmt: skip


def _balance(db, account) -> int:
    return ledger.balance(db, ledger.get_ledger_account(db, account.ledger_account_id))


def test_outgoing_payments_are_validated_and_high_value_needs_approval(db: Session) -> None:
    staff = make_staff(db)
    account = _payer(db, staff, balance=50_000_000)
    with pytest.raises(BusinessRuleViolation, match="Unknown beneficiary bank"):
        _pay(db, staff, account, bank="NOSUCHXX")
    with pytest.raises(BusinessRuleViolation, match="check digits"):
        _pay(db, staff, account, beneficiary="12345678901299")
    small = _pay(db, staff, account)
    assert small.payment_number.startswith("OPY-") and small.status == "pending"
    threshold, _ = payments.limits_for(db, account, TODAY)
    big = _pay(db, staff, account, amount=threshold)
    assert big.high_value and big.status == "awaiting_approval"
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        clearing.approve_outgoing(db, big, staff.employee.id)
    clearing.approve_outgoing(db, big, staff.manager.id)
    assert big.status == "pending" and big.approved_by == staff.manager.id


def test_a_clearing_cycle_settles_returns_and_rejects(db: Session) -> None:
    staff = make_staff(db)
    account = _payer(db, staff, balance=500_000)
    currency = account.currency
    paid = _pay(db, staff, account, amount=200_000)
    returned = _pay(db, staff, account, amount=150_000, beneficiary=CLOSED)
    too_much = _pay(db, staff, account, amount=200_000)  # only 150,000 left by then
    cash_before = ledger.balance(db, ledger.cash_account(db, currency))
    batch = clearing.submit_batch(db, currency, staff.manager.id, today=TODAY)
    assert batch.batch_number.startswith("CLB-") and batch.payments == 2
    assert too_much.status == "rejected" and too_much.return_code == "AM04"
    assert _balance(db, account) == 150_000  # both debited into clearing suspense
    assert ledger.balance(db, clearing.clearing_account(db, currency)) == 350_000
    clearing.settle_batch(db, batch, staff.manager.id, today=TODAY)
    assert (batch.settled_count, batch.returned_count) == (1, 1)
    assert paid.status == "settled" and paid.settled_on == TODAY
    assert returned.status == "returned" and returned.return_code == "AC04"
    assert _balance(db, account) == 300_000  # the returned 150,000 is back
    assert ledger.balance(db, clearing.clearing_account(db, currency)) == 0
    assert ledger.balance(db, ledger.cash_account(db, currency)) == cash_before - 200_000
    assert clearing.submit_batch(db, currency, None, today=TODAY) is None  # nothing pending


def test_a_bulk_file_is_validated_and_released_with_four_eyes(db: Session) -> None:
    staff = make_staff(db)
    account = _payer(db, staff, balance=1_000_000)
    threshold, _ = payments.limits_for(db, account, TODAY)
    lines = [
        {"name": "Supplier A", "bank": "ALPEDEFF", "account": OPEN, "amount": 100_000},
        {"name": "Supplier B", "bank": "LACBFRPP", "account": "12345678901200",
         "amount": 50_000},
        {"name": "Supplier C", "bank": "HARBSGSG", "account": OPEN, "amount": 200_000},
    ]  # fmt: skip
    with pytest.raises(BusinessRuleViolation, match="more than the account can pay"):
        clearing.receive_bulk(db, account=account, file_name="too-big.csv",
                              lines=[{**lines[0], "amount": 2_000_000}],
                              received_by=staff.employee.id, today=TODAY)  # fmt: skip
    bulk = clearing.receive_bulk(db, account=account, file_name="october.csv", lines=lines,
                                 received_by=staff.employee.id, today=TODAY)  # fmt: skip
    assert bulk.file_number.startswith("BLK-") and (bulk.valid_count, bulk.invalid_count) == (2, 1)
    assert bulk.valid_total == 300_000 and "check digits" in bulk.lines[1]["error"]
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        clearing.release_bulk(db, bulk, staff.employee.id, today=TODAY)
    created = clearing.release_bulk(db, bulk, staff.manager.id, today=TODAY)
    assert bulk.status == "released" and len(created) == 2
    assert all(p.status == "pending" and p.bulk_file_id == bulk.id for p in created)
    assert threshold > 200_000 or created[1].high_value  # the file's approval covers them


def test_recalls_cancel_or_ask_the_beneficiary_bank(db: Session) -> None:
    staff = make_staff(db)
    account = _payer(db, staff, balance=2_000_000)
    pending = _pay(db, staff, account)
    recall = clearing.request_recall(db, pending, "DUPL", staff.employee.id)
    with pytest.raises(ConflictError, match="already open"):
        clearing.request_recall(db, pending, "TECH", staff.employee.id)
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        clearing.approve_recall(db, recall, staff.employee.id)
    clearing.approve_recall(db, recall, staff.manager.id)
    assert recall.status == "accepted" and pending.status == "recalled"
    # Two settled payments: a duplicate recalled in time, a fraud recall too late.
    duplicate, fraud = _pay(db, staff, account), _pay(db, staff, account, amount=300_000)
    clearing.run_cycle(db, account.currency, staff.manager.id, today=TODAY)
    assert duplicate.status == fraud.status == "settled"
    before = _balance(db, account)
    in_time = clearing.request_recall(db, duplicate, "DUPL", staff.employee.id)
    clearing.approve_recall(db, in_time, staff.manager.id)
    assert in_time.status == "sent"
    clearing.resolve_recall(db, in_time, staff.manager.id, today=TODAY + timedelta(days=7))
    assert in_time.status == "accepted" and duplicate.status == "recalled"
    assert _balance(db, account) == before + 100_000
    late = clearing.request_recall(db, fraud, "FRAD", staff.employee.id)
    clearing.approve_recall(db, late, staff.manager.id)
    clearing.resolve_recall(db, late, staff.manager.id, today=TODAY + timedelta(days=5))
    assert late.status == "refused" and "3-day window" in late.outcome_note
    assert fraud.status == "settled"


def test_the_payments_operations_api(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    account = _payer(db, staff)
    teller, manager = auth(staff.employee), auth(staff.manager)
    db.commit()
    assert len(client.get("/api/v1/payment-ops/banks", headers=teller).json()) == 6
    body = {"account_number": account.account_number, "beneficiary_name": "Supplier",
            "beneficiary_bank": "RIVRUS33", "beneficiary_account": OPEN,
            "amount": 100_000}  # fmt: skip
    created = client.post("/api/v1/payment-ops/payments", json=body, headers=teller)
    assert created.status_code == 201 and created.json()["status"] == "pending"
    cycle = {"currency": account.currency}
    assert client.post("/api/v1/payment-ops/cycles", json=cycle, headers=teller).status_code == 403
    batch = client.post("/api/v1/payment-ops/cycles", json=cycle, headers=manager).json()["batch"]
    assert batch["settled_count"] == 1
    listed = client.get("/api/v1/payment-ops/payments", headers=teller).json()["items"]
    assert (
        listed[0]["status"] == "settled" and listed[0]["account_number"] == account.account_number
    )
    asked = {"payment_number": listed[0]["payment_number"], "reason_code": "TECH"}
    recall = client.post("/api/v1/payment-ops/recalls", headers=teller, json=asked)
    assert recall.status_code == 201
    url = f"/api/v1/payment-ops/recalls/{recall.json()['id']}"
    assert client.post(f"{url}/approve", headers=teller).status_code == 403
    assert client.post(f"{url}/approve", headers=manager).json()["status"] == "sent"
    assert client.post(f"{url}/resolve", headers=manager).json()["status"] == "accepted"
    assert (
        client.get("/api/v1/payment-ops/summary/counts", headers=teller).json()["open_recalls"] == 0
    )


def test_pr32_review_fixes(db: Session) -> None:
    """Settlement posts one entry per payment, so a batch above the ledger's line limit
    settles; an account cannot be closed while a payment could still come back to it."""
    from app.modules.accounts.models import AccountStatus
    from app.modules.accounts.service import change_status

    staff = make_staff(db)
    account = _payer(db, staff, balance=0)
    big = 600_000_000_000_000  # each within the line limit, together above it
    for n in range(2):
        deposit(db, account.id, amount=big, memo="Synthetic", actor_id=staff.employee.id,
                idempotency_key=f"big-{account.id}-{n}")  # fmt: skip
    first, second = _pay(db, staff, account), _pay(db, staff, account)
    first.amount = second.amount = big  # as if the country's limits allowed it
    db.flush()
    # Settled today (the real date the closure check uses), so within the recall windows.
    today = datetime.now(UTC).date()
    batch = clearing.run_cycle(db, account.currency, staff.manager.id, today=today)
    assert batch.settled_count == 2 and batch.total == 2 * big
    with pytest.raises(BusinessRuleViolation, match="could still come back"):
        change_status(db, account.id, AccountStatus.CLOSED, staff.manager.id, "Closing")


def test_pr33_review_fixes(db: Session) -> None:
    """The recall profile identifies a beneficiary by bank and account, dates an unsettled
    candidate by when it was entered, and a cycle can be limited to some payments."""
    staff = make_staff(db)
    account = _payer(db, staff, balance=50_000_000)
    # The same account number at two banks: not a duplicate, not payee history.
    elsewhere = _pay(db, staff, account, bank="RIVRUS33")
    clearing.run_cycle(db, account.currency, None, today=TODAY, only=[elsewhere.id])
    recalled = _pay(db, staff, account)
    clearing.run_cycle(db, account.currency, None, today=TODAY, only=[recalled.id])
    recall = clearing.request_recall(db, recalled, "DUPL", staff.employee.id)
    profile = clearing.recall_profile(db, recall, TODAY + timedelta(days=1))
    assert profile["duplicate_matches"] == 0 and profile["payee_history"] == 0
    # A pending payment to the same beneficiary, entered months after the recalled one
    # settled: not a duplicate either. A cycle limited to another payment leaves it pending.
    later = _pay(db, staff, account)
    assert later.created_at.date() - TODAY > timedelta(days=3)
    other = _pay(db, staff, account, beneficiary=clearing.account_number("223456789012"))
    batch = clearing.run_cycle(db, account.currency, None, today=TODAY, only=[other.id])
    assert batch.payments == 1 and later.status == "pending"
    assert clearing.recall_profile(db, recall, TODAY)["duplicate_matches"] == 0
