"""Phase 39: treasury — counterparties, money-market deals, liquidity and the FX desk."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation
from app.core.permissions import RoleCode
from app.modules.accounts.service import deposit
from app.modules.fx import service as fx
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction, LedgerAccountType
from app.modules.treasury import service as treasury
from tests.factories import auth, make_customer, make_staff, make_user, open_account

TODAY = date(2026, 7, 1)
NOW = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)


def _funded(db: Session, staff, amount: int = 1_000_000_000) -> str:
    """A customer deposit of `amount`: cash and deposits in the account's currency."""
    customer = make_customer(db)
    account = open_account(db, staff, customer)
    deposit(db, account.id, amount=amount, memo="Synthetic", actor_id=staff.employee.id,
            idempotency_key=f"treasury-{account.id}")  # fmt: skip
    return account.currency


def _book(db, staff, currency, *, kind="placement", principal=100_000_000, tenor=30,
          code="CP-NORTHGATE", rate=450):  # fmt: skip
    return treasury.book_deal(
        db, counterparty=treasury.find_counterparty(db, code), kind=kind, currency=currency,
        principal=principal, rate_bps=rate, tenor_days=tenor, booked_by=staff.employee.id,
        today=TODAY,
    )  # fmt: skip


def _cash(db, currency: str) -> int:
    return ledger.balance(db, ledger.cash_account(db, currency))


def test_booking_rules(db: Session) -> None:
    staff = make_staff(db)
    assert treasury.ensure_counterparties(db) == 8 and treasury.ensure_counterparties(db) == 0
    currency = _funded(db, staff)
    with pytest.raises(BusinessRuleViolation, match="principal must be between"):
        _book(db, staff, currency, principal=1_000)
    with pytest.raises(BusinessRuleViolation, match="tenor"):
        _book(db, staff, currency, tenor=400)
    with pytest.raises(BusinessRuleViolation, match="rated BB\\+"):
        _book(db, staff, currency, code="CP-SAVANNA")
    # Borrowing from a sub-investment-grade bank is allowed: the bank owes, not the reverse.
    assert _book(db, staff, currency, kind="borrowing", code="CP-SAVANNA").status == "booked"
    northgate = treasury.find_counterparty(db, "CP-NORTHGATE")
    first = _book(db, staff, currency, principal=50_000_000)
    assert first.deal_number.startswith("MM-") and first.maturity_date == TODAY + timedelta(30)
    # A limit just above what is placed: the same placement again would exceed it.
    used = treasury.exposure_usd(db, northgate, TODAY)
    treasury.set_counterparty_limit(db, northgate, used + 1_000, staff.admin.id)
    with pytest.raises(BusinessRuleViolation, match=f"above its US\\${used + 1_000:,} limit"):
        _book(db, staff, currency, principal=50_000_000)
    treasury.cancel_deal(db, first, staff.employee.id)  # cancelled deals use no limit
    assert _book(db, staff, currency, principal=50_000_000).status == "booked"


def test_a_placement_settles_and_matures_with_interest(db: Session) -> None:
    staff = make_staff(db)
    treasury.ensure_counterparties(db)
    currency = _funded(db, staff)
    deal = _book(db, staff, currency)
    basis = 365 if currency in treasury.ACT_365 else 360
    assert deal.day_basis == basis
    assert deal.interest == 100_000_000 * 450 * 30 // (10_000 * basis)
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        treasury.confirm_deal(db, deal, staff.employee.id, now=NOW)
    treasury.confirm_deal(db, deal, staff.manager.id, now=NOW)
    assert deal.status == "settled" and _cash(db, currency) == 900_000_000
    placements = treasury.treasury_account(db, "PLACEMENTS", currency)
    assert ledger.balance(db, placements) == 100_000_000
    row = treasury.liquidity(db, TODAY, currency)["currencies"][0]
    # Cash 900m plus the placement back within 30 days, against 10 % of 1,000m deposits.
    assert row["inflows"] == 100_000_000 + deal.interest
    assert row["stressed_outflow"] == 100_000_000 and row["coverage_bps"] > 100_000
    with pytest.raises(BusinessRuleViolation, match="matures on"):
        treasury.mature_deal(db, deal, staff.manager.id, now=NOW + timedelta(days=29))
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        treasury.mature_deal(db, deal, staff.employee.id, now=NOW + timedelta(days=30))
    treasury.mature_deal(db, deal, staff.manager.id, now=NOW + timedelta(days=30))
    assert deal.status == "matured" and ledger.balance(db, placements) == 0
    assert _cash(db, currency) == 1_000_000_000 + deal.interest
    income = treasury.treasury_account(db, "INTEREST-INCOME", currency)
    assert ledger.balance(db, income) == deal.interest


def test_a_placement_cannot_breach_liquidity_coverage(db: Session) -> None:
    staff = make_staff(db)
    treasury.ensure_counterparties(db)
    currency = _funded(db, staff)  # cash 1,000m; stressed outflow 100m
    # 950m out for 60 days would leave 50m against 100m of outflow: 50 %.
    long = _book(db, staff, currency, principal=950_000_000, tenor=60, code="CP-RIDGELINE")
    with pytest.raises(BusinessRuleViolation, match="coverage to 50 %"):
        treasury.confirm_deal(db, long, staff.manager.id, now=NOW)
    # The same amount for 30 days comes back within the window, so coverage holds.
    short = _book(db, staff, currency, principal=950_000_000, tenor=30, code="CP-RHEINTAL")
    treasury.confirm_deal(db, short, staff.manager.id, now=NOW)
    assert short.status == "settled" and long.status == "booked"


def test_a_borrowing_brings_cash_in_and_repays_with_interest(db: Session) -> None:
    staff = make_staff(db)
    treasury.ensure_counterparties(db)
    deal = _book(db, staff, "EUR", kind="borrowing", principal=20_000_000, tenor=90, rate=360)
    assert deal.day_basis == 360 and deal.interest == 20_000_000 * 360 * 90 // 3_600_000
    before = _cash(db, "EUR")
    treasury.confirm_deal(db, deal, staff.manager.id, now=NOW)
    assert _cash(db, "EUR") == before + 20_000_000
    if before < deal.interest:  # only the borrowed cash: the interest cannot be paid
        with pytest.raises(BusinessRuleViolation, match="Not enough EUR cash"):
            treasury.mature_deal(db, deal, staff.manager.id, now=NOW + timedelta(days=90))
        equity = ledger.ensure_ledger_account(db, code="TEST-EQUITY-EUR", name="Test equity",
                                              account_type=LedgerAccountType.EQUITY,
                                              currency="EUR")  # fmt: skip
        ledger.post_entry(db, idempotency_key=f"test-eur-{deal.id}", currency="EUR",
                          description="Test funds", source="test",
                          lines=[ledger.LineSpec(ledger.cash_account(db, "EUR").id,
                                                 Direction.DEBIT, 1_000_000, "x"),
                                 ledger.LineSpec(equity.id, Direction.CREDIT, 1_000_000, "x")],
                          actor_id=None)  # fmt: skip
    cash = _cash(db, "EUR")
    treasury.mature_deal(db, deal, staff.manager.id, now=NOW + timedelta(days=90))
    assert _cash(db, "EUR") == cash - 20_000_000 - deal.interest
    expense = treasury.treasury_account(db, "INTEREST-EXPENSE", "EUR")
    assert ledger.balance(db, expense) == deal.interest
    assert ledger.balance(db, treasury.treasury_account(db, "BORROWINGS", "EUR")) == 0


def _long_eur(db, amount: int) -> None:
    """The bank bought EUR: cash in, the EUR position long."""
    ledger.post_entry(db, idempotency_key=f"test-long-eur-{amount}", currency="EUR",
                      description="Test position", source="test",
                      lines=[ledger.LineSpec(ledger.cash_account(db, "EUR").id, Direction.DEBIT,
                                             amount, "x"),
                             ledger.LineSpec(fx.position_account(db, "EUR").id, Direction.CREDIT,
                                             amount, "x")], actor_id=None)  # fmt: skip


def test_the_fx_desk_squares_a_position_over_its_limit(db: Session) -> None:
    staff = make_staff(db)
    treasury.ensure_counterparties(db)
    _long_eur(db, 300_000_000)  # EUR 3m, about US$3.2m
    eur = treasury.position(db, "EUR", TODAY)
    assert eur["over_limit"] and eur["limit_usd"] == 1_000_000 and eur["excess_usd"] > 2_000_000
    northgate = treasury.find_counterparty(db, "CP-NORTHGATE")
    with pytest.raises(BusinessRuleViolation, match="can only reduce the position"):
        treasury.book_fx_trade(db, counterparty=northgate, sell_currency="EUR",
                               buy_currency="USD", sell_amount=400_000_000,
                               booked_by=staff.employee.id, today=TODAY)  # fmt: skip
    trade = treasury.book_fx_trade(db, counterparty=northgate, sell_currency="EUR",
                                   buy_currency="USD", sell_amount=250_000_000,
                                   booked_by=staff.employee.id, today=TODAY)  # fmt: skip
    assert trade.trade_number.startswith("FXT-") and trade.buy_amount > 250_000_000
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        treasury.confirm_fx_trade(db, trade, staff.employee.id, now=NOW)
    treasury.confirm_fx_trade(db, trade, staff.manager.id, now=NOW)
    assert ledger.balance(db, fx.position_account(db, "EUR")) == 50_000_000
    assert not treasury.position(db, "EUR", TODAY)["over_limit"]  # EUR 0.5m is within
    treasury.set_fx_limit(db, "EUR", 100_000, staff.admin.id)
    assert treasury.position(db, "EUR", TODAY)["over_limit"]


def test_the_treasury_api(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    treasury.ensure_counterparties(db)
    currency = _funded(db, staff)
    executive = make_user(db, RoleCode.GLOBAL_EXECUTIVE)
    dealer, back_office = auth(staff.employee), auth(staff.manager)
    db.commit()
    parties = client.get("/api/v1/treasury/counterparties", headers=dealer).json()
    assert [p["code"] for p in parties][:2] == ["CP-ANDINO", "CP-GULFSTAR"]
    body = {"kind": "placement", "counterparty_code": "CP-MERLION", "currency": currency,
            "principal": 100_000_000, "rate_bps": 425, "tenor_days": 14}  # fmt: skip
    created = client.post("/api/v1/treasury/deals", json=body, headers=dealer)
    assert created.status_code == 201, created.text
    url = f"/api/v1/treasury/deals/{created.json()['id']}"
    assert client.post(f"{url}/confirm", headers=dealer).status_code == 403
    assert client.post(f"{url}/confirm", headers=back_office).json()["status"] == "settled"
    merlion = next(p for p in client.get("/api/v1/treasury/counterparties", headers=dealer).json()
                   if p["code"] == "CP-MERLION")  # fmt: skip
    assert merlion["exposure_usd"] > 0
    limit = {"limit_usd": 5_000_000}
    assert client.put("/api/v1/treasury/counterparties/CP-MERLION/limit", json=limit,
                      headers=back_office).status_code == 403  # fmt: skip
    changed = client.put("/api/v1/treasury/counterparties/CP-MERLION/limit", json=limit,
                         headers=auth(executive))  # fmt: skip
    assert changed.json()["limit_usd"] == 5_000_000
    liquidity = client.get("/api/v1/treasury/liquidity", headers=dealer).json()
    assert any(r["currency"] == currency for r in liquidity["currencies"])
    assert client.get("/api/v1/treasury/fx-desk", headers=dealer).status_code == 200
    assert client.get("/api/v1/treasury/summary/counts", headers=dealer).json()["placements"] == 1


def test_pr30_review_fixes(db: Session) -> None:
    """The bought side only closes a short (USD excepted); maturity cash lines stay within the
    ledger's line limit for the largest deal any currency allows."""
    staff = make_staff(db)
    treasury.ensure_counterparties(db)
    northgate = treasury.find_counterparty(db, "CP-NORTHGATE")
    _long_eur(db, 300_000_000)
    with pytest.raises(BusinessRuleViolation, match="buying .* would open or grow"):
        treasury.book_fx_trade(db, counterparty=northgate, sell_currency="EUR",
                               buy_currency="GBP", sell_amount=100_000_000,
                               booked_by=staff.employee.id, today=TODAY)  # fmt: skip
    usd = treasury.book_fx_trade(db, counterparty=northgate, sell_currency="EUR",
                                 buy_currency="USD", sell_amount=100_000_000,
                                 booked_by=staff.employee.id, today=TODAY)  # fmt: skip
    assert usd.status == "booked"
    # US$100m in Lebanese pounds at 50 % for 360 days: principal plus interest is above the
    # ledger's 10^15 line limit, so they settle on separate cash lines.
    principal = treasury._from_usd(treasury.MAX_PRINCIPAL_USD, "LBP")
    deal = _book(db, staff, "LBP", kind="borrowing", principal=principal, tenor=360, rate=5000)
    assert deal.principal + deal.interest > 10**15
    treasury.confirm_deal(db, deal, staff.manager.id, now=NOW)
    equity = ledger.ensure_ledger_account(
        db, code="TEST-EQUITY-LBP", name="Test equity", account_type=LedgerAccountType.EQUITY,
        currency="LBP",
    )  # fmt: skip
    ledger.post_entry(db, idempotency_key=f"test-lbp-{deal.id}", currency="LBP",
                      description="Test funds", source="test",
                      lines=[ledger.LineSpec(ledger.cash_account(db, "LBP").id, Direction.DEBIT,
                                             deal.interest, "x"),
                             ledger.LineSpec(equity.id, Direction.CREDIT, deal.interest, "x")],
                      actor_id=None)  # fmt: skip
    treasury.mature_deal(db, deal, staff.manager.id, now=NOW + timedelta(days=360))
    assert deal.status == "matured" and _cash(db, "LBP") == 0
