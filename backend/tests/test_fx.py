"""Phase 24: multi-currency — synthetic rates, conversions through currency positions,
revaluation, and cross-currency payments through WF-0002."""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation
from app.core.permissions import RoleCode
from app.modules.customers.models import CustomerNotification
from app.modules.fx import rates
from app.modules.fx import service as fx
from app.modules.fx.models import FxDeal, FxRate
from app.modules.ledger import service as ledger
from app.modules.ledger.models import JournalEntry, ReconciliationMode
from app.modules.payments.models import Payment
from tests.factories import auth, funded_account, make_staff, make_user, payment

DAY = date(2026, 3, 2)


def balance_of(db: Session, account) -> int:
    return ledger.balance(db, ledger.get_ledger_account(db, account.ledger_account_id))


# --- Rates ------------------------------------------------------------------------------------


def test_synthetic_rates_are_deterministic_and_pegs_hold() -> None:
    eur = rates.units_per_usd("EUR", DAY)
    rates._PATHS.clear()  # a fresh process computes the same walk
    assert rates.units_per_usd("EUR", DAY) == eur
    assert rates.units_per_usd("EUR", rates.ANCHOR_DATE) == Decimal("0.86")
    assert rates.units_per_usd("AED", DAY) == Decimal("3.6725")
    assert rates.units_per_usd("XOF", DAY) == (eur * Decimal("655.957")).quantize(rates.RATE_PLACES)
    assert rates.units_per_usd("USD", DAY) == 1
    # Rates move from day to day, within the currency's volatility.
    later = rates.units_per_usd("EUR", date(2026, 3, 3))
    assert later != eur and abs(later / eur - 1) < Decimal("0.05")


def test_publishing_is_idempotent_and_covers_every_currency(db: Session) -> None:
    first = fx.publish_rates(db, DAY)
    assert first >= 93
    assert fx.publish_rates(db, DAY) == 0
    stored = db.execute(select(FxRate).where(FxRate.rate_date == DAY)).scalars().all()
    assert {r.currency for r in stored} >= {"USD", "EUR", "JPY", "KWD", "XOF"}


# --- Quotes and conversions -------------------------------------------------------------------


def test_quotes_apply_the_margin_and_round_down_in_minor_units(db: Session) -> None:
    terms = fx.quote(db, "USD", "JPY", 100_000, DAY)  # 1,000.00 USD
    jpy = fx.rate(db, "JPY", DAY)
    assert terms["mid_rate"] == jpy.quantize(fx.RATE_PLACES)
    assert terms["customer_rate"] < terms["mid_rate"]
    assert terms["buy_amount"] == int(1000 * terms["customer_rate"])  # yen have no decimals
    assert terms["base_amount"] == 100_000
    to_kwd = fx.quote(db, "JPY", "KWD", 1_000_000, DAY)  # three decimals
    # Yen have no decimals, dinars three: 1,000,000 yen is about 2,000 dinars, in fils.
    assert to_kwd["buy_amount"] == int(1_000_000 * to_kwd["customer_rate"] * 1000)
    no_margin = fx.quote(db, "USD", "EUR", 100_000, DAY, margin_bps=0)
    assert no_margin["customer_rate"] == no_margin["mid_rate"]
    with pytest.raises(BusinessRuleViolation):
        fx.quote(db, "USD", "USD", 100, DAY)
    with pytest.raises(BusinessRuleViolation):
        fx.quote(db, "KRW", "KWD", 1, DAY)  # 1 won is a fifth of a fils: nothing


def test_a_conversion_posts_one_balanced_entry_per_currency(db: Session) -> None:
    staff = make_staff(db)
    usd = funded_account(db, staff, balance=1_000_000)
    eur = funded_account(db, staff, country_code="DE")
    assert eur.currency == "EUR"
    from_account = ledger.get_ledger_account(db, usd.ledger_account_id)
    to_account = ledger.get_ledger_account(db, eur.ledger_account_id)

    deal, replayed = fx.convert(
        db, from_account=from_account, to_account=to_account, sell_amount=250_000, day=DAY,
        idempotency_key="test:conversion", purpose="conversion", reference="test",
        actor_id=staff.employee.id,
    )  # fmt: skip
    assert not replayed
    assert (balance_of(db, usd), balance_of(db, eur)) == (750_000, deal.buy_amount)
    for entry_id, currency in ((deal.sell_entry_id, "USD"), (deal.buy_entry_id, "EUR")):
        entry = db.get(JournalEntry, entry_id)
        assert entry.currency == currency and entry.source == "fx"
        assert all(line.ledger_account.currency == currency for line in entry.lines)
    again, replayed = fx.convert(
        db, from_account=from_account, to_account=to_account, sell_amount=250_000, day=DAY,
        idempotency_key="test:conversion", purpose="conversion", reference="test",
        actor_id=staff.employee.id,
    )  # fmt: skip
    assert replayed and again.id == deal.id and balance_of(db, usd) == 750_000
    # Every entry balances in its own currency; the ledger still reconciles.
    assert ledger.reconcile(db, None, ReconciliationMode.FULL).ok


def test_revaluation_books_the_margin_then_rate_moves(db: Session) -> None:
    staff = make_staff(db)
    usd = funded_account(db, staff, balance=10_000_000)
    gbp = funded_account(db, staff, country_code="GB")
    fx.revalue(db, DAY, None)  # book whatever earlier tests left open
    before = fx.positions(db, DAY)
    assert before["unbooked_usd"] == 0

    deal, _ = fx.convert(
        db,
        from_account=ledger.get_ledger_account(db, usd.ledger_account_id),
        to_account=ledger.get_ledger_account(db, gbp.ledger_account_id),
        sell_amount=5_000_000, day=DAY, idempotency_key="test:reval", purpose="conversion",
        reference="test", actor_id=None,
    )  # fmt: skip
    after = fx.positions(db, DAY)
    # The bank took $50,000 and paid out pounds worth 0.5 % less: about $250 of FX income.
    assert after["unbooked_usd"] == pytest.approx(25_000, abs=2)
    run = fx.revalue(db, DAY, None)
    assert run.posted == after["unbooked_usd"] and run.journal_entry_id is not None
    assert fx.revalue(db, DAY, None).posted == 0  # nothing new the same day
    # The next day's rates move the open position's value; revaluation books the change.
    nxt = fx.positions(db, date(2026, 3, 3))
    moved = fx.revalue(db, date(2026, 3, 3), None)
    assert moved.posted == nxt["unbooked_usd"] != 0
    assert fx.positions(db, date(2026, 3, 3))["unbooked_usd"] == 0
    assert deal.margin_bps == fx.DEFAULT_MARGIN_BPS


# --- Cross-currency payments ------------------------------------------------------------------


def test_a_payment_to_an_account_in_another_currency_is_converted(
    client: TestClient, db: Session
) -> None:
    staff = make_staff(db)
    debtor = funded_account(db, staff, balance=500_000)  # USD
    creditor = funded_account(db, staff, country_code="JP")  # JPY
    started = client.post(
        "/api/v1/workflows/WF-0002/executions",
        json={"input": payment(debtor, creditor, 20_000)},  # 200.00 USD
        headers=auth(staff.employee),
    )
    assert started.status_code == 201, started.text
    done = started.json()
    assert (done["status"], done["outcome"]) == ("completed", "approved")
    assert done["context"]["validate_payment"]["cross_currency"] is True

    record = db.get(Payment, uuid.UUID(done["context"]["validate_payment"]["payment_id"]))
    deal = db.get(FxDeal, record.fx_deal_id)
    assert (record.currency, record.creditor_currency) == ("USD", "JPY")
    assert (deal.sell_amount, deal.buy_amount) == (20_000, record.creditor_amount)
    assert record.journal_entry_id == deal.sell_entry_id and deal.purpose == "payment"
    assert balance_of(db, debtor) == 480_000
    assert balance_of(db, creditor) == record.creditor_amount > 0
    note = db.execute(
        select(CustomerNotification).where(
            CustomerNotification.workflow_execution_id == uuid.UUID(done["id"])
        )
    ).scalar_one()
    assert "JPY after conversion" in note.body

    listed = client.get(
        "/api/v1/payments", params={"q": record.payment_number}, headers=auth(staff.employee)
    ).json()["items"][0]
    assert listed["creditor_currency"] == "JPY"
    assert listed["creditor_amount"] == record.creditor_amount
    assert listed["fx_deal_number"] == deal.deal_number


def test_the_payer_account_must_match_the_payment_currency(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    debtor = funded_account(db, staff, balance=500_000)
    creditor = funded_account(db, staff, country_code="DE")
    done = client.post(
        "/api/v1/workflows/WF-0002/executions",
        json={"input": payment(debtor, creditor, 1_000, currency="EUR")},
        headers=auth(staff.employee),
    ).json()
    assert done["outcome"] == "rejected"
    assert "The paying account is not held in EUR." in done["context"]["reject_payment"]["reasons"]


# --- API --------------------------------------------------------------------------------------


def test_the_fx_api(client: TestClient, db: Session) -> None:
    employee = auth(make_user(db, RoleCode.BANKING_EMPLOYEE))
    admin = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))
    listed = client.get("/api/v1/fx/rates", params={"on": "2026-03-02"}, headers=employee).json()
    by_code = {r["currency"]: r for r in listed}
    assert Decimal(by_code["AED"]["units_per_usd"]) == Decimal("3.6725")
    hist = client.get(
        "/api/v1/fx/rates/eur", params={"from": "2026-03-01", "to": "2026-03-07"}, headers=employee
    ).json()
    assert len(hist) == 7
    quote = client.post(
        "/api/v1/fx/quote",
        json={"sell_currency": "USD", "buy_currency": "EUR", "sell_amount": 10_000,
              "rate_date": "2026-03-02"},
        headers=employee,
    ).json()  # fmt: skip
    assert quote["margin_bps"] == 50 and quote["buy_amount"] > 0

    assert client.get("/api/v1/fx/positions", headers=employee).status_code == 403
    assert client.post("/api/v1/fx/revaluations", json={}, headers=employee).status_code == 403
    run = client.post("/api/v1/fx/revaluations", json={"as_of": "2026-03-02"}, headers=admin)
    assert run.status_code == 201, run.text
    positions = client.get(
        "/api/v1/fx/positions", params={"as_of": "2026-03-02"}, headers=admin
    ).json()
    assert positions["unbooked_usd"] == 0
    assert client.get("/api/v1/fx/revaluations", headers=admin).json()["total"] >= 1
    assert "items" in client.get("/api/v1/fx/deals", headers=admin).json()
