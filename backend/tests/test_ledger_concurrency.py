"""Concurrency guarantees, exercised with real commits from parallel sessions.

Unlike the rest of the suite these tests commit (concurrent transactions cannot share the
per-test rollback transaction). They only create uniquely named rows and never assert on
global counts, so the data they leave behind cannot affect other tests; the test database
schema is rebuilt at the start of every run.
"""

import threading
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.database import get_sessionmaker
from app.core.errors import BusinessRuleViolation
from app.modules.accounts.service import deposit, withdraw
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, JournalEntry, LedgerAccountType
from tests.factories import make_customer, make_staff, open_account


def _committed(work: Callable[[Session], object]) -> object:
    with get_sessionmaker()() as session, session.begin():
        return work(session)


def _race(*operations: Callable[[Session], object]) -> list[object]:
    """Run each operation in its own committed transaction, released at the same moment."""
    barrier = threading.Barrier(len(operations))
    results: list[object] = [None] * len(operations)

    def run(index: int, operation: Callable[[Session], object]) -> None:
        try:
            with get_sessionmaker()() as session, session.begin():
                barrier.wait(timeout=10)
                results[index] = operation(session)
        except Exception as exc:  # noqa: BLE001 - the outcome is what we assert on
            results[index] = exc

    threads = [threading.Thread(target=run, args=(i, op)) for i, op in enumerate(operations)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return results


@pytest.fixture
def funded_account():
    def setup(session: Session):
        staff = make_staff(session)
        account = open_account(session, staff, make_customer(session))
        deposit(
            session,
            account.id,
            amount=1_000,
            memo=None,
            idempotency_key="seed",
            actor_id=staff.employee.id,
        )
        return account.id, account.ledger_account_id, staff.employee.id

    return _committed(setup)


def test_concurrent_withdrawals_cannot_overdraw(funded_account) -> None:
    account_id, ledger_account_id, teller = funded_account

    # Six tellers each withdraw 300 from a balance of 1,000 at the same moment.
    results = _race(
        *[
            lambda s, key=f"race-{i}": withdraw(
                s, account_id, amount=300, memo=None, idempotency_key=key, actor_id=teller
            )
            for i in range(6)
        ]
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(successes) == 3, results
    assert all(
        isinstance(f, BusinessRuleViolation) and "Insufficient funds" in f.message for f in failures
    ), failures
    remaining = _committed(
        lambda s: ledger.balance(s, ledger.get_ledger_account(s, ledger_account_id))
    )
    assert remaining == 100


def test_concurrent_duplicate_postings_create_one_entry() -> None:
    suffix = uuid.uuid4().hex[:8].upper()

    def accounts(session: Session):
        cash = ledger.ensure_ledger_account(
            session,
            code=f"1999-{suffix}",
            name="Race cash",
            account_type=LedgerAccountType.ASSET,
            currency="USD",
        )
        equity = ledger.ensure_ledger_account(
            session,
            code=f"3999-{suffix}",
            name="Race equity",
            account_type=LedgerAccountType.EQUITY,
            currency="USD",
        )
        return cash.id, equity.id

    cash_id, equity_id = _committed(accounts)
    key = f"race-{suffix}"

    def post(session: Session):
        entry, replayed = ledger.post_entry(
            session,
            idempotency_key=key,
            currency="USD",
            description="Concurrent duplicate",
            source="manual",
            lines=[
                ledger.LineSpec(cash_id, Direction.DEBIT, 250),
                ledger.LineSpec(equity_id, Direction.CREDIT, 250),
            ],
            actor_id=None,
        )
        return entry.entry_number, replayed

    results = _race(post, post, post)

    assert all(not isinstance(r, Exception) for r in results), results
    assert len({number for number, _ in results}) == 1
    assert sorted(replayed for _, replayed in results) == [False, True, True]
    count = _committed(
        lambda s: s.execute(
            select(func.count()).where(JournalEntry.idempotency_key == key)
        ).scalar_one()
    )
    assert count == 1


def test_lines_cannot_be_added_to_an_entry_from_an_earlier_transaction(funded_account) -> None:
    _, ledger_account_id, _ = funded_account
    entry_id, cash_id = _committed(
        lambda s: (
            s.execute(
                select(JournalEntry.id)
                .join(JournalEntry.lines)
                .where(text("journal_lines.ledger_account_id = :id"))
                .params(id=ledger_account_id)
            ).scalar_one(),
            ledger.cash_account(s, "USD").id,
        )
    )

    def inject(session: Session) -> None:
        for direction, account in (("debit", cash_id), ("credit", ledger_account_id)):
            session.execute(
                text(
                    "INSERT INTO journal_lines (id, journal_entry_id, line_number, "
                    "ledger_account_id, direction, amount) VALUES "
                    "(gen_random_uuid(), :entry, :n, :account, :direction, 5)"
                ),
                {
                    "entry": entry_id,
                    "n": 90 + len(direction),
                    "account": account,
                    "direction": direction,
                },
            )

    with pytest.raises(DBAPIError, match="transaction that posts it"):
        _committed(inject)
