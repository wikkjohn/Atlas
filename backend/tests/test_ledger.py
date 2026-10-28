"""Double-entry ledger: balance rules, idempotency, immutability, reversals, reconciliation."""

import random
import uuid
from collections import defaultdict

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError
from app.core.permissions import RoleCode
from app.modules.ledger import service as ledger
from app.modules.ledger.models import (
    Direction,
    EntryStatus,
    JournalEntry,
    JournalLine,
    LedgerAccountType,
)
from tests.factories import auth, make_customer, make_staff, make_user, open_account

ENTRIES = "/api/v1/ledger/journal-entries"


def _gl(db: Session, code: str, account_type: LedgerAccountType, currency: str = "USD"):
    return ledger.ensure_ledger_account(
        db,
        code=f"{code}-{currency}",
        name=f"Test {code}",
        account_type=account_type,
        currency=currency,
    )


def _lines(*pairs: tuple) -> list[dict]:
    return [
        {"ledger_account_id": str(account.id), "direction": direction, "amount": amount}
        for account, direction, amount in pairs
    ]


@pytest.fixture
def admin_headers(db: Session) -> dict[str, str]:
    return auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))


def test_balanced_entry_posts_and_moves_balances(
    client: TestClient, db: Session, admin_headers: dict
) -> None:
    cash = ledger.cash_account(db, "USD")
    equity = _gl(db, "3000", LedgerAccountType.EQUITY)

    response = client.post(
        ENTRIES,
        json={
            "currency": "USD",
            "description": "Initial synthetic capital",
            "lines": _lines((cash, "debit", 1_000_000), (equity, "credit", 1_000_000)),
        },
        headers={**admin_headers, "Idempotency-Key": "capital-1"},
    )

    assert response.status_code == 201
    entry = response.json()
    assert entry["entry_number"].startswith("JE-")
    assert entry["status"] == "posted"
    assert entry["total"] == 1_000_000
    assert [line["ledger_account_code"] for line in entry["lines"]] == ["1000-USD", "3000-USD"]
    # Asset balances are debit-normal, equity balances credit-normal: both read +1,000,000.
    assert ledger.balance(db, cash) == 1_000_000
    assert ledger.balance(db, equity) == 1_000_000


def test_unbalanced_and_invalid_entries_are_rejected(
    client: TestClient, db: Session, admin_headers: dict
) -> None:
    cash = ledger.cash_account(db, "USD")
    equity = _gl(db, "3000", LedgerAccountType.EQUITY)
    euro = _gl(db, "3000", LedgerAccountType.EQUITY, "EUR")

    def post(lines: list[dict], key: str):
        return client.post(
            ENTRIES,
            json={"currency": "USD", "description": "Test entry", "lines": lines},
            headers={**admin_headers, "Idempotency-Key": key},
        )

    unbalanced = post(_lines((cash, "debit", 100), (equity, "credit", 99)), "u1")
    single = post(_lines((cash, "debit", 100)), "u2")
    other_currency = post(_lines((cash, "debit", 100), (euro, "credit", 100)), "u3")
    zero = post(_lines((cash, "debit", 0), (equity, "credit", 0)), "u4")
    unknown = post(
        [
            {"ledger_account_id": str(uuid.uuid4()), "direction": "debit", "amount": 5},
            {"ledger_account_id": str(equity.id), "direction": "credit", "amount": 5},
        ],
        "u5",
    )

    assert unbalanced.status_code == 422
    assert unbalanced.json()["error"]["details"] == {
        "debits": 100,
        "credits": 99,
        "difference": 1,
    }
    assert single.status_code == 422
    assert other_currency.status_code == 422
    assert other_currency.json()["error"]["details"] == {"accounts": ["3000-EUR"]}
    assert zero.status_code == 422
    assert unknown.status_code == 422
    assert db.execute(select(func.count()).select_from(JournalEntry)).scalar_one() == 0


def test_duplicate_posting_requests_are_safe(
    client: TestClient, db: Session, admin_headers: dict
) -> None:
    cash = ledger.cash_account(db, "USD")
    equity = _gl(db, "3000", LedgerAccountType.EQUITY)
    body = {
        "currency": "USD",
        "description": "Capital injection",
        "lines": _lines((cash, "debit", 500), (equity, "credit", 500)),
    }
    headers = {**admin_headers, "Idempotency-Key": "inject-2026-10"}

    first = client.post(ENTRIES, json=body, headers=headers)
    retry = client.post(ENTRIES, json=body, headers=headers)
    changed = client.post(ENTRIES, json={**body, "description": "Other"}, headers=headers)
    no_key = client.post(ENTRIES, json=body, headers=admin_headers)

    assert first.status_code == 201
    assert retry.status_code == 200
    assert retry.headers["Idempotent-Replayed"] == "true"
    assert retry.json()["id"] == first.json()["id"]
    assert changed.status_code == 409
    assert no_key.status_code == 422
    assert ledger.balance(db, cash) == 500


def test_database_rejects_unbalanced_entries_even_from_raw_sql(db: Session) -> None:
    cash = ledger.cash_account(db, "USD")
    equity = _gl(db, "3000", LedgerAccountType.EQUITY)
    entry_id = uuid.uuid4()

    with pytest.raises(DBAPIError, match="unbalanced"), db.begin_nested():
        db.execute(
            text(
                "INSERT INTO journal_entries (id, entry_number, idempotency_key, request_hash, "
                "currency, description, source, status, effective_date) VALUES "
                "(:id, 'JE-RAW', 'raw', 'x', 'USD', 'raw', 'manual', 'posted', current_date)"
            ),
            {"id": entry_id},
        )
        for account, direction, amount in ((cash, "debit", 100), (equity, "credit", 90)):
            db.execute(
                text(
                    "INSERT INTO journal_lines (id, journal_entry_id, line_number, "
                    "ledger_account_id, direction, amount) VALUES "
                    "(gen_random_uuid(), :entry, :n, :account, :direction, :amount)"
                ),
                {
                    "entry": entry_id,
                    "n": amount,
                    "account": account.id,
                    "direction": direction,
                    "amount": amount,
                },
            )
        # Deferred constraints normally run at COMMIT; force them now.
        db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_posted_entries_are_immutable(db: Session) -> None:
    cash = ledger.cash_account(db, "USD")
    equity = _gl(db, "3000", LedgerAccountType.EQUITY)
    entry, _ = ledger.post_entry(
        db,
        idempotency_key="immutable-1",
        currency="USD",
        description="Original",
        source="manual",
        lines=[
            ledger.LineSpec(cash.id, Direction.DEBIT, 700),
            ledger.LineSpec(equity.id, Direction.CREDIT, 700),
        ],
        actor_id=None,
    )

    for statement in (
        f"UPDATE journal_lines SET amount = 1 WHERE journal_entry_id = '{entry.id}'",
        f"DELETE FROM journal_lines WHERE journal_entry_id = '{entry.id}'",
        f"UPDATE journal_entries SET description = 'edited' WHERE id = '{entry.id}'",
        f"UPDATE journal_entries SET status = 'reversed', currency = 'EUR' WHERE id = '{entry.id}'",
        f"DELETE FROM journal_entries WHERE id = '{entry.id}'",
        "TRUNCATE journal_lines CASCADE",
    ):
        with pytest.raises(DBAPIError, match="immutable|cannot be deleted"), db.begin_nested():
            db.execute(text(statement))

    db.expire_all()
    assert [line.amount for line in db.get(JournalEntry, entry.id).lines] == [700, 700]


def test_reversal_offsets_the_original(
    client: TestClient, db: Session, admin_headers: dict
) -> None:
    cash = ledger.cash_account(db, "USD")
    equity = _gl(db, "3000", LedgerAccountType.EQUITY)
    original = client.post(
        ENTRIES,
        json={
            "currency": "USD",
            "description": "Posted in error",
            "lines": _lines((cash, "debit", 4_200), (equity, "credit", 4_200)),
        },
        headers={**admin_headers, "Idempotency-Key": "error-1"},
    ).json()
    url = f"{ENTRIES}/{original['id']}/reverse"

    reversal = client.post(
        url,
        json={"reason": "Duplicate capture"},
        headers={**admin_headers, "Idempotency-Key": "r1"},
    )
    retry = client.post(
        url,
        json={"reason": "Duplicate capture"},
        headers={**admin_headers, "Idempotency-Key": "r1"},
    )
    twice = client.post(
        url, json={"reason": "Again"}, headers={**admin_headers, "Idempotency-Key": "r2"}
    )
    of_reversal = client.post(
        f"{ENTRIES}/{reversal.json()['id']}/reverse",
        json={"reason": "Undo"},
        headers={**admin_headers, "Idempotency-Key": "r3"},
    )
    refreshed = client.get(f"{ENTRIES}/{original['id']}", headers=admin_headers).json()

    assert reversal.status_code == 201
    assert reversal.json()["reversal_of_id"] == original["id"]
    assert [
        (line["ledger_account_code"], line["direction"]) for line in reversal.json()["lines"]
    ] == [
        ("1000-USD", "credit"),
        ("3000-USD", "debit"),
    ]
    assert retry.status_code == 200
    assert twice.status_code == 409
    assert of_reversal.status_code == 422
    assert refreshed["status"] == EntryStatus.REVERSED
    assert refreshed["reversed_by_id"] == reversal.json()["id"]
    assert ledger.balance(db, cash) == ledger.balance(db, equity) == 0


def test_reconciliation_passes_after_real_activity(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    for country_code in ("US", "JP", "DE"):
        account = open_account(db, staff, make_customer(db, country_code=country_code))
        from app.modules.accounts.service import deposit, withdraw

        deposit(
            db,
            account.id,
            amount=50_000,
            memo=None,
            idempotency_key=f"d-{country_code}",
            actor_id=staff.employee.id,
        )
        withdraw(
            db,
            account.id,
            amount=20_000,
            memo=None,
            idempotency_key=f"w-{country_code}",
            actor_id=staff.employee.id,
        )

    response = client.post(
        "/api/v1/ledger/reconciliation", headers=auth(make_user(db, RoleCode.AUDITOR))
    )
    forbidden = client.post("/api/v1/ledger/reconciliation", headers=auth(staff.employee))

    assert response.status_code == 200
    report = response.json()
    assert report["ok"] is True, report
    assert report["entries_checked"] == 6
    assert report["lines_checked"] == 12
    assert all(check["passed"] for check in report["checks"])
    assert "USD: 70,000 = 70,000" in report["checks"][2]["detail"]
    assert forbidden.status_code == 403


def test_ledger_invariants_hold_under_random_postings(db: Session) -> None:
    """Property test: many random balanced postings keep the accounting equation true."""
    rng = random.Random(20261027)
    currencies = ["USD", "EUR", "JPY"]
    accounts = {
        ccy: [
            _gl(db, code, kind, ccy)
            for code, kind in (
                ("1000", LedgerAccountType.ASSET),
                ("1200", LedgerAccountType.ASSET),
                ("2000", LedgerAccountType.LIABILITY),
                ("3000", LedgerAccountType.EQUITY),
                ("4000", LedgerAccountType.INCOME),
                ("5000", LedgerAccountType.EXPENSE),
            )
        ]
        for ccy in currencies
    }
    for i in range(300):
        ccy = rng.choice(currencies)
        debit_account, credit_account = rng.sample(accounts[ccy], 2)
        amounts = [rng.randint(1, 10**9) for _ in range(rng.randint(1, 3))]
        lines = [ledger.LineSpec(debit_account.id, Direction.DEBIT, a) for a in amounts]
        lines.append(ledger.LineSpec(credit_account.id, Direction.CREDIT, sum(amounts)))
        ledger.post_entry(
            db,
            idempotency_key=f"prop-{i}",
            currency=ccy,
            description="Random posting",
            source="manual",
            lines=lines,
            actor_id=None,
        )
    # Unbalanced attempts are always refused and leave no trace.
    for i in range(20):
        ccy = rng.choice(currencies)
        a, b = rng.sample(accounts[ccy], 2)
        with pytest.raises(BusinessRuleViolation):
            ledger.post_entry(
                db,
                idempotency_key=f"bad-{i}",
                currency=ccy,
                description="Broken",
                source="manual",
                lines=[
                    ledger.LineSpec(a.id, Direction.DEBIT, 10),
                    ledger.LineSpec(b.id, Direction.CREDIT, 9),
                ],
                actor_id=None,
            )

    balances = ledger.balances(db, [acc for group in accounts.values() for acc in group])
    for ccy, group in accounts.items():
        totals: dict[str, int] = defaultdict(int)
        for account in group:
            totals[account.account_type] += balances[account.id]
        # Assets + Expenses = Liabilities + Equity + Income, in every currency.
        assert totals["asset"] + totals["expense"] == (
            totals["liability"] + totals["equity"] + totals["income"]
        ), ccy
    assert db.execute(select(func.count()).select_from(JournalEntry)).scalar_one() == 300
    assert ledger.reconcile(db, None).ok


def test_idempotency_key_conflict_at_service_level(db: Session) -> None:
    cash = ledger.cash_account(db, "USD")
    equity = _gl(db, "3000", LedgerAccountType.EQUITY)
    lines = [
        ledger.LineSpec(cash.id, Direction.DEBIT, 1),
        ledger.LineSpec(equity.id, Direction.CREDIT, 1),
    ]
    first, replayed_first = ledger.post_entry(
        db,
        idempotency_key="svc-1",
        currency="USD",
        description="A",
        source="manual",
        lines=lines,
        actor_id=None,
    )
    second, replayed_second = ledger.post_entry(
        db,
        idempotency_key="svc-1",
        currency="USD",
        description="A",
        source="manual",
        lines=lines,
        actor_id=None,
    )

    assert (replayed_first, replayed_second) == (False, True)
    assert first.id == second.id
    with pytest.raises(ConflictError):
        ledger.post_entry(
            db,
            idempotency_key="svc-1",
            currency="USD",
            description="B",
            source="manual",
            lines=lines,
            actor_id=None,
        )
    assert db.execute(select(func.count()).select_from(JournalLine)).scalar_one() == 2


def test_idempotency_key_reused_with_another_effective_date_conflicts(db: Session) -> None:
    from datetime import date

    cash = ledger.cash_account(db, "USD")
    equity = _gl(db, "3000", LedgerAccountType.EQUITY)
    lines = [
        ledger.LineSpec(cash.id, Direction.DEBIT, 1),
        ledger.LineSpec(equity.id, Direction.CREDIT, 1),
    ]
    post = lambda day: ledger.post_entry(  # noqa: E731
        db,
        idempotency_key="dated-1",
        currency="USD",
        description="Dated",
        source="manual",
        lines=lines,
        actor_id=None,
        effective_date=day,
    )
    first, _ = post(date(2026, 1, 31))
    again, replayed = post(date(2026, 1, 31))
    assert replayed and again.id == first.id
    with pytest.raises(ConflictError):
        post(date(2026, 2, 1))
