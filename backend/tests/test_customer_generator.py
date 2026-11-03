"""Phase 72: the customer generator — segments, products and transaction history."""

from collections import Counter
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation
from app.core.permissions import RoleCode
from app.modules.accounts.models import Account, AccountRequest
from app.modules.accounts.service import accounts_out
from app.modules.customers.models import Customer
from app.modules.ledger import service as ledger
from app.modules.ledger.models import JournalEntry, ReconciliationMode
from app.simulation import customers as generator
from tests.factories import auth, make_user


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


@pytest.fixture
def staff(db: Session):
    teller = make_user(db, RoleCode.BANKING_EMPLOYEE)
    manager = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    db.commit()
    return {"requested_by": teller.username, "decided_by": manager.username}


def _generated(db: Session, seed: int) -> list[Customer]:
    return list(
        db.execute(
            select(Customer).where(Customer.generated_from == f"{generator.GENERATOR}:{seed}")
        ).scalars()
    )


def test_plans_follow_their_segment_and_repeat() -> None:
    countries = [(None, "US", "USD"), (None, "JP", "JPY")]
    per_usd = {"USD": 1, "JPY": 150}
    from decimal import Decimal

    per_usd = {k: Decimal(v) for k, v in per_usd.items()}
    today, start = date(2026, 11, 3), date(2026, 8, 1)
    plans = [generator.plan(7, i, countries, per_usd, today, start) for i in range(3_000)]
    again = [generator.plan(7, i, countries, per_usd, today, start) for i in range(50)]
    assert [(p.name, p.segment, p.products) for p in plans[:50]] == [
        (p.name, p.segment, p.products) for p in again
    ]
    share = Counter(p.segment for p in plans)
    assert share["mass"] > share["affluent"] > share["private"] > 0
    for p in plans:
        seg = generator.SEGMENTS[p.segment]
        age = (today - p.born).days // 365
        assert seg.ages[0] <= age <= seg.ages[1] + 1
        assert p.customer_type == seg.customer_type
        assert ("business_current" in p.products) == (p.segment == "sme")
        assert "current" in p.products or p.segment == "sme"
        assert p.opened_at.date() <= start  # open before the history starts
    # JPY has no minor unit: amounts in yen are larger than in dollars by about the rate.
    usd = [p.yearly_minor / 100 for p in plans if p.currency == "USD" and p.segment == "mass"]
    jpy = [p.yearly_minor for p in plans if p.currency == "JPY" and p.segment == "mass"]
    assert 100 < (sum(jpy) / len(jpy)) / (sum(usd) / len(usd)) < 225


def test_history_never_overdraws_and_has_each_kind_of_movement() -> None:
    from decimal import Decimal

    countries = [(None, "US", "USD")]
    months = generator._months(date(2026, 11, 3), 3)
    assert months == [date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)]
    seen: Counter = Counter()
    for i in range(400):
        p = generator.plan(3, i, countries, {"USD": Decimal(1)}, date(2026, 11, 3), months[0])
        balance = dict(p.opening)
        moves = generator.history(3, p, months)
        assert moves == generator.history(3, p, months)
        assert [m[0] for m in moves] == sorted(m[0] for m in moves)
        for day, category, src, dst, amount in moves:
            assert amount > 0 and months[0] <= day < date(2026, 11, 1)
            seen[category] += 1
            if src != "bank":
                balance[src] -= amount
                assert balance[src] >= 0
            if dst != "bank":
                balance[dst] += amount
    assert {
        "salary",
        "pension",
        "housing",
        "bills",
        "card",
        "savings",
        "receipt",
        "supplier",
        "payroll",
    } <= set(seen)


def test_generated_customers_are_complete_and_balances_match(db: Session, factory, staff) -> None:
    result = generator.generate(factory, count=60, seed=41, history_months=2, batch=25, **staff)
    assert (result["created"], result["existing"]) == (60, 0)
    db.expire_all()
    made = _generated(db, 41)
    assert len(made) == 60 and sum(result["by_segment"].values()) == 60
    assert {c.kyc_status for c in made} == {"verified"}
    assert all(c.segment in generator.SEGMENTS for c in made)
    accounts = list(
        db.execute(select(Account).where(Account.customer_id.in_([c.id for c in made]))).scalars()
    )
    assert len(accounts) == result["accounts"] >= 60
    # Every account came through an approved four-eyes request.
    requests = db.execute(
        select(func.count())
        .select_from(AccountRequest)
        .where(
            AccountRequest.account_id.in_([a.id for a in accounts]),
            AccountRequest.status == "approved",
        )
    ).scalar_one()
    assert requests == len(accounts)
    # The ledger holds the history: balances never negative, the books reconcile.
    assert all(out.balance >= 0 for out in accounts_out(db, accounts))
    assert ledger.reconcile(db, None, ReconciliationMode.FULL).ok
    entries = db.execute(
        select(func.count()).select_from(JournalEntry).where(JournalEntry.source.like("history.%"))
    ).scalar_one()
    assert entries == result["entries"] > 60 * 2
    # History is dated in its months.
    first = db.execute(
        select(func.min(JournalEntry.effective_date)).where(JournalEntry.source.like("history.%"))
    ).scalar_one()
    assert first == generator._months(datetime.now(UTC).date(), 2)[0]

    # The same seed again: nothing new. A larger count continues where it stopped.
    again = generator.generate(factory, count=60, seed=41, history_months=2, **staff)
    assert (again["created"], again["existing"]) == (0, 60)
    more = generator.generate(factory, count=70, seed=41, history_months=2, **staff)
    assert (more["created"], more["existing"]) == (10, 60)
    db.expire_all()
    assert len(_generated(db, 41)) == 70

    summary = generator.summary(db)
    assert summary["generated"] >= 70
    assert sum(summary["accounts_per_customer"].values()) >= 70
    assert summary["history"]["opening"] >= 70


def test_the_rules(factory, staff) -> None:
    for kwargs, rule in [
        ({"count": 0}, "count_invalid"),
        ({"count": 5, "history_months": 25}, "history_invalid"),
        ({"count": 5, "requested_by": "x", "decided_by": "x"}, "four_eyes"),
        ({"count": 5, "requested_by": "nobody-a", "decided_by": "nobody-b"}, "users_missing"),
    ]:
        with pytest.raises(BusinessRuleViolation) as refused:
            generator.generate(factory, **{**staff, **kwargs})
        assert refused.value.details["rule"] == rule


def test_the_api(client: TestClient, db: Session) -> None:
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    make_user(db, RoleCode.DEPARTMENT_MANAGER, username="manager")  # approves (four-eyes)
    auditor = make_user(db, RoleCode.AUDITOR)
    db.commit()
    body = {"count": 30, "seed": 5, "history_months": 1}
    refused = client.post("/api/v1/customers/population/generate", headers=auth(auditor), json=body)
    assert refused.status_code == 403
    too_many = client.post(
        "/api/v1/customers/population/generate", headers=auth(admin), json={**body, "count": 50_001}
    )
    assert too_many.status_code == 422
    made = client.post("/api/v1/customers/population/generate", headers=auth(admin), json=body)
    assert made.status_code == 200, made.text
    assert made.json()["created"] == 30
    summary = client.get("/api/v1/customers/population/summary", headers=auth(auditor))
    assert summary.status_code == 200, summary.text
    assert summary.json()["generated"] >= 30
    listed = client.get("/api/v1/customers?limit=200", headers=auth(admin)).json()["items"]
    assert any(c.get("segment") for c in listed)
