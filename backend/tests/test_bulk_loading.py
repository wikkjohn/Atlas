"""Phase 13: bulk ledger posting (COPY) and the bulk population loader."""

import pytest
from sqlalchemy import Connection, func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.core.errors import BusinessRuleViolation, ConflictError
from app.core.permissions import RoleCode
from app.modules.accounts.models import Account, AccountRequest
from app.modules.accounts.numbers import is_valid_account_number
from app.modules.accounts.service import accounts_out
from app.modules.customers.models import Customer
from app.modules.ledger import service as ledger
from app.modules.ledger.models import (
    Direction,
    JournalEntry,
    LedgerAccountType,
    ReconciliationMode,
)
from app.simulation.population import PopulationError, _person, load
from tests.factories import make_user


def _gl(db: Session, code: str, account_type: LedgerAccountType, currency: str = "USD"):
    return ledger.ensure_ledger_account(
        db,
        code=f"{code}-{currency}",
        name=f"Test {code}",
        account_type=account_type,
        currency=currency,
    )


def _postings(debit, credit, n: int, *, tag: str = "bulk", amount: int = 100, currency="USD"):
    return [
        ledger.Posting(
            idempotency_key=f"{tag}-{i}",
            currency=currency,
            description=f"{tag} {i}",
            source="test_bulk",
            lines=[
                ledger.LineSpec(debit.id, Direction.DEBIT, amount + i),
                ledger.LineSpec(credit.id, Direction.CREDIT, amount + i),
            ],
        )
        for i in range(n)
    ]


def _bulk_entries(db: Session) -> int:
    return db.execute(select(func.count()).where(JournalEntry.source == "test_bulk")).scalar_one()


def test_bulk_posting_matches_single_postings_and_replays(db: Session) -> None:
    cash = ledger.cash_account(db, "USD")
    equity = _gl(db, "3950", LedgerAccountType.EQUITY)
    audits = db.execute(select(func.count()).select_from(AuditEvent)).scalar_one()

    ids = ledger.post_entries(db, _postings(cash, equity, 300), actor_id=None)

    assert len(set(ids)) == 300 and _bulk_entries(db) == 300
    assert ledger.balances(db, [cash, equity]) == ledger.line_balances(db, [cash, equity])
    assert ledger.balances(db, [equity])[equity.id] == sum(100 + i for i in range(300))
    entry = db.get(JournalEntry, ids[0])
    assert entry.entry_number.startswith("JE-") and len(entry.lines) == 2
    # One audit event for the whole batch.
    assert db.execute(select(func.count()).select_from(AuditEvent)).scalar_one() == audits + 1

    # The same batch again replays: same ids, nothing posted twice.
    assert ledger.post_entries(db, _postings(cash, equity, 300), actor_id=None) == ids
    assert _bulk_entries(db) == 300
    # A known key with a different request refuses the whole batch.
    changed = _postings(cash, equity, 2, tag="bulk", amount=999)
    with pytest.raises(ConflictError):
        ledger.post_entries(db, changed, actor_id=None)
    assert ledger.reconcile(db, None, ReconciliationMode.FULL).ok


def test_bulk_posting_applies_the_posting_rules_to_the_whole_batch(db: Session) -> None:
    cash = ledger.cash_account(db, "USD")
    equity = _gl(db, "3951", LedgerAccountType.EQUITY)
    euro = _gl(db, "3951", LedgerAccountType.EQUITY, "EUR")
    good = _postings(cash, equity, 5, tag="rules")

    unbalanced = ledger.Posting(
        idempotency_key="rules-bad",
        currency="USD",
        description="unbalanced",
        source="test_bulk",
        lines=[
            ledger.LineSpec(cash.id, Direction.DEBIT, 100),
            ledger.LineSpec(equity.id, Direction.CREDIT, 99),
        ],
    )
    with pytest.raises(BusinessRuleViolation, match="Unbalanced"):
        ledger.post_entries(db, [*good, unbalanced], actor_id=None)
    wrong_currency = _postings(cash, euro, 1, tag="rules-eur")
    with pytest.raises(BusinessRuleViolation, match="USD ledger account"):
        ledger.post_entries(db, [*good, *wrong_currency], actor_id=None)
    with pytest.raises(BusinessRuleViolation, match="unique"):
        ledger.post_entries(db, [*good, good[0]], actor_id=None)
    assert _bulk_entries(db) == 0  # all or nothing


def test_the_database_enforces_the_rules_on_copied_rows(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defence in depth: with the Python checks switched off, the ledger's constraint
    triggers still refuse an unbalanced entry written by COPY."""
    cash = ledger.cash_account(db, "USD")
    equity = _gl(db, "3952", LedgerAccountType.EQUITY)
    monkeypatch.setattr(ledger, "_check_lines", lambda *args: None)
    unbalanced = ledger.Posting(
        idempotency_key="copy-unbalanced",
        currency="USD",
        description="unbalanced",
        source="test_bulk",
        lines=[
            ledger.LineSpec(cash.id, Direction.DEBIT, 100),
            ledger.LineSpec(equity.id, Direction.CREDIT, 99),
        ],
    )
    with pytest.raises(BusinessRuleViolation, match="rejected the bulk posting"):
        ledger.post_entries(db, [unbalanced], actor_id=None)
    assert _bulk_entries(db) == 0


@pytest.fixture
def factory(db_connection: Connection):
    def make() -> Session:
        return Session(
            bind=db_connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
            expire_on_commit=False,
        )

    return make


def test_the_population_loader_creates_complete_verified_customers(db: Session, factory) -> None:
    teller = make_user(db, RoleCode.BANKING_EMPLOYEE)
    manager = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    db.commit()
    before = db.execute(select(func.count()).select_from(Customer)).scalar_one()

    report = load(
        factory,
        customers=45,
        seed=11,
        batch=20,
        requested_by=teller.username,
        decided_by=manager.username,
    )

    assert (report.customers, report.batches) == (45, 3)
    db.expire_all()
    assert db.execute(select(func.count()).select_from(Customer)).scalar_one() == before + 45
    requests = list(
        db.execute(select(AccountRequest).where(AccountRequest.decided_by == manager.id)).scalars()
    )
    assert len(requests) == 45
    assert all(r.requested_by == teller.id and r.status == "approved" for r in requests)
    accounts = [db.get(Account, r.account_id) for r in requests]
    assert all(is_valid_account_number(a.account_number) for a in accounts)
    assert all(a.customer.kyc_status == "verified" for a in accounts)
    balances = [out.balance for out in accounts_out(db, accounts)]
    assert all(b > 0 for b in balances)
    by_currency: dict[str, int] = {}
    for account, balance in zip(accounts, balances, strict=True):
        by_currency[account.currency] = by_currency.get(account.currency, 0) + balance
    assert by_currency == report.deposits
    assert ledger.reconcile(db, None, ReconciliationMode.FULL).ok
    # Names come from the seed: customer i of the load is _person(seed, i).
    loaded = sorted((a.customer.customer_number, a.customer.name) for a in accounts)
    today = accounts[0].opened_at.date()
    assert [name for _, name in loaded[:5]] == [_person(11, i, today)[0] for i in range(5)]


def test_the_population_loader_keeps_four_eyes_and_needs_its_people(factory) -> None:
    with pytest.raises(PopulationError, match="Four-eyes"):
        load(factory, customers=1, requested_by="same", decided_by="same")
    with pytest.raises(PopulationError, match="must exist"):
        load(factory, customers=1, requested_by="nobody-a", decided_by="nobody-b")
