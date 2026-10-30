"""Phase 29: retail banking — products, overdrafts, standing orders, month end, statements."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation
from app.core.permissions import RoleCode
from app.jobs.handlers import SCHEDULER_USERNAME
from app.modules.accounts.models import Account, AccountType
from app.modules.accounts.service import available, withdraw
from app.modules.identity.models import User
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction
from app.modules.payments import service as payments
from app.modules.retail import service as retail
from app.modules.retail.models import (
    AccountStatement,
    StandingOrder,
    StandingOrderFrequency,
    StandingOrderStatus,
)
from tests.factories import (
    auth,
    funded_account,
    make_customer,
    make_staff,
    open_account,
)

TODAY = date(2026, 3, 15)


def _move(db: Session, account: Account, amount: int, day: date, key: str) -> None:
    """Post a cash movement to the customer's account effective on `day` (+ in, - out)."""
    cash = ledger.cash_account(db, account.currency)
    inbound = amount > 0
    ledger.post_entry(
        db,
        idempotency_key=f"test:{key}",
        currency=account.currency,
        description="Test movement",
        source="test",
        lines=[
            ledger.LineSpec(cash.id, Direction.DEBIT if inbound else Direction.CREDIT, abs(amount)),
            ledger.LineSpec(
                account.ledger_account_id,
                Direction.CREDIT if inbound else Direction.DEBIT,
                abs(amount),
            ),
        ],
        actor_id=None,
        effective_date=day,
    )


def _backdate(db: Session, account: Account, day: date) -> None:
    account.opened_at = datetime.combine(day, datetime.min.time(), UTC)
    db.flush()


def _balance(db: Session, account: Account) -> int:
    return ledger.balance(db, ledger.get_ledger_account(db, account.ledger_account_id))


def test_products_convert_their_dollar_terms_to_each_currency(db: Session) -> None:
    current = retail.get_product(db, "current")
    assert (current.overdraft_rate_bps, current.monthly_fee_usd_cents) == (1990, 500)
    assert retail.monthly_fee(current, "USD") == 500
    assert retail.max_overdraft(current, "USD") == 250_000
    assert retail.monthly_fee(current, "JPY") > 500  # yen have no minor units
    savings = retail.get_product(db, "savings")
    assert savings.credit_rate_bps == 250 and retail.max_overdraft(savings, "USD") == 0


def test_an_arranged_overdraft_extends_what_an_account_can_pay(db: Session) -> None:
    staff = make_staff(db)
    account = funded_account(db, staff, balance=10_000)
    with pytest.raises(BusinessRuleViolation, match="at most"):
        retail.set_overdraft(db, account, 300_000, staff.manager.id)
    retail.set_overdraft(db, account, 50_000, staff.manager.id)
    assert available(db, account) == 60_000
    withdraw(
        db, account.id, amount=40_000, memo=None, idempotency_key="w1", actor_id=staff.employee.id
    )
    assert _balance(db, account) == -30_000
    with pytest.raises(BusinessRuleViolation, match="Insufficient"):
        withdraw(db, account.id, amount=30_001, memo=None, idempotency_key="w2",
                 actor_id=staff.employee.id)  # fmt: skip
    # The limit cannot go below what is already owed.
    with pytest.raises(BusinessRuleViolation, match="overdrawn by more"):
        retail.set_overdraft(db, account, 20_000, staff.manager.id)
    # Payments count the overdraft as well.
    payee = funded_account(db, staff)
    payment = payments.create_payment(
        db, debtor=account, creditor=payee, amount=15_000, reference="Rent",
        initiated_by=staff.employee.id,
    )  # fmt: skip
    payments.release(db, payment.id, approver=None)
    assert _balance(db, account) == -45_000
    savings = open_account(db, staff, make_customer(db), AccountType.SAVINGS)
    with pytest.raises(BusinessRuleViolation, match="at most 0"):
        retail.set_overdraft(db, savings, 100, staff.manager.id)


def test_standing_orders_pay_on_business_days_and_stop_after_missed_payments(
    db: Session,
) -> None:
    staff = make_staff(db)
    payer = funded_account(db, staff, balance=30_000, country_code="GB")
    payee = funded_account(db, staff, country_code="GB")
    scheduler = db.execute(select(User).where(User.username == SCHEDULER_USERNAME)).scalar_one()
    with pytest.raises(BusinessRuleViolation, match="high-value threshold"):
        retail.create_standing_order(
            db, debtor=payer, creditor=payee, amount=1_000_000,
            frequency=StandingOrderFrequency.MONTHLY, first_date=TODAY, end_date=None,
            reference="Too much", actor_id=staff.employee.id, today=TODAY,
        )  # fmt: skip
    # Due on Saturday 31 January 2026: paid on Monday 2 February; February has no 31st.
    order = retail.create_standing_order(
        db, debtor=payer, creditor=payee, amount=10_000,
        frequency=StandingOrderFrequency.MONTHLY, first_date=date(2026, 1, 31), end_date=None,
        reference="Rent", actor_id=staff.employee.id, today=date(2026, 1, 20),
    )  # fmt: skip
    assert order.order_number.startswith("SO-") and order.day_of_month == 31
    assert retail.run_standing_orders(db, date(2026, 1, 31), scheduler.id)["waiting"] == 1
    paid = retail.run_standing_orders(db, date(2026, 2, 2), scheduler.id)
    assert paid["paid"] == 1 and order.next_date == date(2026, 2, 28)
    assert order.payments_made == 1 and _balance(db, payee) == 10_000
    # Two more paid, then the money runs out: three misses in a row stop the order.
    for day in (date(2026, 3, 2), date(2026, 3, 31)):
        retail.run_standing_orders(db, day, scheduler.id)
    assert order.payments_made == 3 and _balance(db, payer) == 0
    for day in (date(2026, 4, 30), date(2026, 6, 1), date(2026, 6, 30)):
        retail.run_standing_orders(db, day, scheduler.id)
    assert order.status == StandingOrderStatus.FAILED and order.failures == 3
    assert "Insufficient" in order.last_error


def test_month_end_posts_interest_and_fees_and_issues_statements(db: Session) -> None:
    staff = make_staff(db)
    actor = staff.manager.id
    savings = open_account(db, staff, make_customer(db), AccountType.SAVINGS)
    current = funded_account(db, staff)
    for account in (savings, current):
        _backdate(db, account, date(2025, 12, 1))
    # Savings: 365,000.00 all of January at 2.5 %: 25.00 a year per 1,000 → 31 days' worth.
    _move(db, savings, 36_500_000, date(2025, 12, 20), "s1")
    # Current: overdrawn by 1,000.00 from 16 January (16 days) at 19.9 %.
    retail.set_overdraft(db, current, 200_000, actor)
    _move(db, current, -100_000, date(2026, 1, 16), "c1")

    with pytest.raises(BusinessRuleViolation, match="not over yet"):
        retail.month_end(db, date(2026, 3, 1), actor, today=TODAY)
    run, created = retail.month_end(db, date(2026, 1, 10), actor, today=TODAY)
    assert created and run.period_start == date(2026, 1, 1) and run.period_end == date(2026, 1, 31)
    earned = round(36_500_000 * 0.025 * 31 / 365)
    owed = round(100_000 * 0.199 * 16 / 365)
    assert _balance(db, savings) == 36_500_000 + earned  # 77,500 = 775.00
    assert _balance(db, current) == -100_000 - owed - 500  # overdraft interest and the fee
    usd = run.totals["USD"]
    assert usd["interest_paid"] >= earned and usd["interest_charged"] >= owed
    assert usd["fees"] >= 500

    statement = db.execute(
        select(AccountStatement).where(AccountStatement.account_id == current.id)
    ).scalar_one()
    assert (statement.opening_balance, statement.closing_balance) == (0, -100_000 - owed - 500)
    assert statement.total_debits == 100_000 + owed + 500 and statement.lines == 3
    lines = retail.statement_lines(db, statement)
    assert [line["source"] for line in lines] == ["test", "interest", "fee"]
    assert lines[-1]["balance"] == statement.closing_balance
    # Once only: asking again changes nothing.
    again, created = retail.month_end(db, date(2026, 1, 1), actor, today=TODAY)
    assert again.id == run.id and not created
    assert _balance(db, savings) == 36_500_000 + earned


def test_the_retail_api(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    teller = auth(staff.employee)
    manager = auth(staff.manager)
    payer = funded_account(db, staff, balance=50_000, country_code="GB")
    payee = funded_account(db, staff, country_code="GB")
    db.commit()

    products = client.get("/api/v1/retail/products", headers=teller).json()
    assert {p["account_type"] for p in products} == {"current", "savings", "business_current"}
    assert (
        client.patch(
            "/api/v1/retail/products/savings", json={"credit_rate_bps": 300}, headers=teller
        ).status_code
        == 403
    )
    changed = client.patch(
        "/api/v1/retail/products/savings", json={"credit_rate_bps": 300}, headers=manager
    )
    assert changed.status_code == 200 and changed.json()["credit_rate_bps"] == 300

    overdraft = client.put(
        f"/api/v1/retail/accounts/{payer.id}/overdraft", json={"limit": 20_000}, headers=manager
    )
    assert overdraft.status_code == 200, overdraft.text
    assert overdraft.json()["overdraft_limit"] == 20_000
    account = client.get(f"/api/v1/accounts/{payer.id}", headers=teller).json()
    assert (account["overdraft_limit"], account["available"]) == (20_000, 70_000)

    tomorrow = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
    body = {
        "debtor_account_number": payer.account_number,
        "creditor_account_number": payee.account_number,
        "amount": 12_500,
        "frequency": "weekly",
        "first_date": tomorrow,
        "reference": "Pocket money",
    }
    created = client.post("/api/v1/retail/standing-orders", json=body, headers=teller)
    assert created.status_code == 201, created.text
    order = created.json()
    assert order["status"] == "active" and order["next_date"] == tomorrow
    listed = client.get(
        "/api/v1/retail/standing-orders", params={"account_id": str(payer.id)}, headers=teller
    ).json()
    assert listed["total"] == 1
    cancelled = client.post(f"/api/v1/retail/standing-orders/{order['id']}/cancel", headers=teller)
    assert cancelled.json()["status"] == "cancelled"
    assert db.get(StandingOrder, order["id"]) is not None

    assert client.post("/api/v1/retail/month-ends", json={}, headers=teller).status_code == 403
    summary = client.get("/api/v1/retail/summary", headers=teller).json()
    assert summary["overdrafts"] >= 1


def test_the_scheduler_may_run_retail_jobs() -> None:
    from app.core.permissions import Permission, permissions_for

    assert Permission.RETAIL_MANAGE in permissions_for(RoleCode.SYSTEM_SCHEDULER)
    assert Permission.RETAIL_MANAGE in permissions_for(RoleCode.DEPARTMENT_MANAGER)
    assert Permission.RETAIL_MANAGE not in permissions_for(RoleCode.BANKING_EMPLOYEE)
