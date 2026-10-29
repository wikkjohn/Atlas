"""Phase 12: stored ledger balances and incremental reconciliation."""

import random

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.ledger import service as ledger
from app.modules.ledger.models import (
    BALANCE_SHARDS,
    Direction,
    LedgerAccountType,
    LedgerBalance,
    ReconciliationMode,
)
from tests.factories import auth, make_user

RECONCILE = "/api/v1/ledger/reconciliation"
HISTORY = "/api/v1/ledger/reconciliations"


def _gl(db: Session, code: str, account_type: LedgerAccountType, currency: str = "USD"):
    return ledger.ensure_ledger_account(
        db,
        code=f"{code}-{currency}",
        name=f"Test {code}",
        account_type=account_type,
        currency=currency,
    )


def _post(db: Session, key: str, debit, credit, amount: int, currency: str = "USD"):
    entry, _ = ledger.post_entry(
        db,
        idempotency_key=key,
        currency=currency,
        description=key,
        source="test",
        lines=[
            ledger.LineSpec(debit.id, Direction.DEBIT, amount),
            ledger.LineSpec(credit.id, Direction.CREDIT, amount),
        ],
        actor_id=None,
    )
    return entry


def test_stored_balances_follow_every_posting_and_reversal(db: Session) -> None:
    cash = ledger.cash_account(db, "USD")
    equity = _gl(db, "3900", LedgerAccountType.EQUITY)
    expense = _gl(db, "5900", LedgerAccountType.EXPENSE)
    rng = random.Random(12)
    entries = []
    for i in range(40):
        amount = rng.randint(1, 10_000_00)
        if i % 3:
            entries.append(_post(db, f"stored-{i}", cash, equity, amount))
        else:
            entries.append(_post(db, f"stored-{i}", expense, cash, amount))
    ledger.reverse_entry(
        db, entries[0].id, reason="test", idempotency_key="stored-r", actor_id=None
    )

    accounts = [cash, equity, expense]
    assert ledger.balances(db, accounts) == ledger.line_balances(db, accounts)
    # Forty postings to one account spread across its shards.
    shards = db.execute(
        select(func.count()).where(LedgerBalance.ledger_account_id == equity.id)
    ).scalar_one()
    assert 1 < shards <= BALANCE_SHARDS


def test_stored_balances_cannot_be_written_directly(db: Session) -> None:
    equity = _gl(db, "3901", LedgerAccountType.EQUITY)
    _post(db, "guarded", ledger.cash_account(db, "USD"), equity, 500)
    db.flush()
    for statement in (
        "UPDATE ledger_balances SET debit_total = 0",
        "DELETE FROM ledger_balances",
        "TRUNCATE ledger_balances",
        f"INSERT INTO ledger_balances VALUES ('{equity.id}', 7, 1, 0, 1, now())",
    ):
        with pytest.raises(DBAPIError, match="maintained by journal line postings only"):
            with db.begin_nested():
                db.execute(text(statement))


def test_reconciliation_runs_are_recorded_and_incremental_runs_check_only_new_entries(
    client: TestClient, db: Session
) -> None:
    headers = auth(make_user(db, RoleCode.AUDITOR))
    equity = _gl(db, "3902", LedgerAccountType.EQUITY)
    _post(db, "before-full", ledger.cash_account(db, "USD"), equity, 1_000)

    full = client.post(RECONCILE, headers=headers)
    assert full.status_code == 200, full.text
    full = full.json()
    assert full["ok"] is True and full["mode"] == "full" and full["window_start"] is None
    names = {c["name"] for c in full["checks"]}
    assert "Stored balances match the lines" in names
    assert "Trial balance per currency" in names

    incremental = client.post(f"{RECONCILE}?mode=incremental", headers=headers).json()
    assert incremental["ok"] is True and incremental["mode"] == "incremental"
    assert incremental["window_start"] is not None
    assert incremental["run_number"] == full["run_number"] + 1
    # The window starts an overlap before the previous run ended, not at the beginning.
    assert incremental["entries_checked"] <= full["entries_checked"]

    history = client.get(HISTORY, headers=headers).json()
    assert [r["mode"] for r in history["items"][:2]] == ["incremental", "full"]
    assert history["items"][0]["failed_checks"] == []
    detail = client.get(f"{HISTORY}/{full['id']}", headers=headers).json()
    assert detail["run_number"] == full["run_number"] and len(detail["checks"]) == 6
    assert (
        client.post(RECONCILE, headers=auth(make_user(db, RoleCode.AI_RESEARCHER))).status_code
        == 403
    )


def test_reconciliation_catches_a_stored_balance_that_drifted(db: Session) -> None:
    equity = _gl(db, "3903", LedgerAccountType.EQUITY)
    _post(db, "drift", ledger.cash_account(db, "USD"), equity, 2_500)
    db.flush()
    # Simulate corruption the guard would normally refuse (inside this test's transaction).
    db.execute(text("ALTER TABLE ledger_balances DISABLE TRIGGER ledger_balances_guard"))
    db.execute(
        text(
            "UPDATE ledger_balances SET credit_total = credit_total + 1"
            " WHERE ledger_account_id = :a"
        ),
        {"a": equity.id},
    )
    db.execute(text("ALTER TABLE ledger_balances ENABLE TRIGGER ledger_balances_guard"))

    for mode in (ReconciliationMode.FULL, ReconciliationMode.INCREMENTAL):
        report = ledger.reconcile(db, None, mode)
        checks = {c.name: c for c in report.checks}
        assert report.ok is False
        stored = checks["Stored balances match the lines"]
        assert not stored.passed and stored.failures[0]["account"] == "3903-USD"
        assert not checks["Trial balance per currency"].passed
