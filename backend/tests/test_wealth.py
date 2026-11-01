"""Phase 43: wealth and investments — securities, suitability, portfolios, orders, income."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError
from app.modules.accounts.models import AccountStatus, AccountType
from app.modules.accounts.service import change_status, deposit
from app.modules.ledger import service as ledger
from app.modules.wealth import service as wealth
from tests.factories import auth, make_customer, make_staff, open_account

TODAY = date(2026, 7, 1)


def _balance(db, account) -> int:
    return ledger.balance(db, ledger.get_ledger_account(db, account.ledger_account_id))


def _investor(db: Session, staff, *, cash: int = 10_000_000, profile: tuple | None = None):
    """A US customer with a USD account holding `cash` (minor units), a profile (balanced,
    10 years, basic knowledge, high capacity for loss: risk 4) and a portfolio."""
    wealth.ensure_securities(db)
    customer = make_customer(db)
    account = open_account(db, staff, customer, AccountType.CURRENT)
    deposit(db, account.id, amount=cash, memo="Synthetic", actor_id=staff.employee.id,
            idempotency_key=f"wealth-{account.id}")  # fmt: skip
    objective, horizon, knowledge, loss = profile or ("balanced", 10, "basic", "high")
    wealth.record_profile(db, customer, objective=objective, horizon_years=horizon,
                          knowledge=knowledge, loss_capacity=loss, assessed_by=staff.employee.id,
                          today=TODAY)  # fmt: skip
    return customer, account, wealth.open_portfolio(db, account, staff.employee.id)


def _order(db, staff, portfolio, code: str, units: int, side: str = "buy", **kwargs):
    return wealth.place_order(db, portfolio=portfolio, security=wealth.find_security(db, code),
                              side=side, units=units, placed_by=staff.employee.id, today=TODAY,
                              **kwargs)  # fmt: skip


def test_risk_profiles_prices_and_fees() -> None:
    assert wealth.risk_profile("preservation", 10, "basic", "high") == 2
    assert wealth.risk_profile("growth", 20, "basic", "high") == 6
    assert wealth.risk_profile("growth", 10, "expert", "high") == 7
    assert wealth.risk_profile("growth", 4, "expert", "high") == 5  # a short horizon
    assert wealth.risk_profile("growth", 10, "informed", "low") == 3  # little capacity for loss
    assert wealth.risk_profile("balanced", 10, "none", "high") == 4
    assert wealth.risk_profile("growth", 10, "none", "high") == 4  # no knowledge
    from app.modules.wealth.models import Security

    fund = Security(code="AGB-BAL-FUND", base_price=25_000, drift_bps=500, volatility_bps=600,
                    income_bps=200, currency="GBP")  # fmt: skip
    assert wealth.price_on(fund, TODAY) == wealth.price_on(fund, TODAY)  # deterministic
    assert wealth.price_on(fund, TODAY) != wealth.price_on(fund, TODAY + timedelta(days=30))
    assert wealth.income_per_unit(fund, TODAY) == wealth.price_on(fund, TODAY) * 200 // 20_000
    assert wealth.fee_for(1_000_000, "USD") == 2_500  # 25 basis points
    assert wealth.fee_for(10_000, "USD") == 100  # at least one major unit
    assert wealth.fee_for(10_000, "JPY") == 25


def test_suitable_orders_execute_and_move_the_cash(db: Session) -> None:
    staff = make_staff(db)
    _, account, portfolio = _investor(db, staff)
    assert portfolio.portfolio_number.startswith("INV-") and portfolio.currency == "USD"
    buy = _order(db, staff, portfolio, "AGB-GOVT-2031", 100)
    assert buy.order_number.startswith("ORD-") and buy.status == "executed" and buy.suitable
    assert buy.amount == 100 * buy.price and buy.fee == wealth.fee_for(buy.amount, "USD")
    assert _balance(db, account) == 10_000_000 - buy.amount - buy.fee
    fees = wealth.fees_account(db, "USD")
    assert ledger.balance(db, fees) >= buy.fee
    sell = _order(db, staff, portfolio, "AGB-GOVT-2031", 40, side="sell")
    assert sell.status == "executed"
    assert _balance(db, account) == 10_000_000 - buy.amount - buy.fee + sell.amount - sell.fee
    value = wealth.valuation(db, portfolio, TODAY)
    [line] = value["holdings"]
    assert line["units"] == 60 and line["cost"] == buy.amount - buy.amount * 40 // 100
    assert value["value"] == 60 * buy.price and value["gain"] == value["value"] - line["cost"]
    with pytest.raises(BusinessRuleViolation, match="Only 60 units"):
        _order(db, staff, portfolio, "AGB-GOVT-2031", 61, side="sell")
    with pytest.raises(BusinessRuleViolation, match="Not enough cash"):
        _order(db, staff, portfolio, "AGB-MMF-USD", 1_000_000)


def test_unsuitable_orders_wait_for_a_second_person(db: Session) -> None:
    staff = make_staff(db)
    customer, account, portfolio = _investor(db, staff)
    start = _balance(db, account)
    # Risk 6 against a profile of 4: waits, and the adviser cannot decide it.
    helios = _order(db, staff, portfolio, "EQ-HELIOS", 10)
    assert helios.status == "awaiting_approval" and not helios.suitable
    assert [r["code"] for r in helios.reasons] == ["risk_above_profile"]
    assert _balance(db, account) == start  # nothing moved yet
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        wealth.reject_order(db, helios, staff.employee.id, "No")
    wealth.reject_order(db, helios, staff.manager.id, "Unsuitable")
    assert helios.status == "rejected" and _balance(db, account) == start
    # A complex product without the knowledge: approved at the client's insistence.
    note = _order(db, staff, portfolio, "SN-AUTOCALL-28", 5)
    assert {r["code"] for r in note.reasons} == {"risk_above_profile", "complex_product"}
    wealth.approve_order(db, note, staff.manager.id, "Insistent client", today=TODAY)
    assert note.status == "executed" and note.approved_by == staff.manager.id
    assert _balance(db, account) == start - note.amount - note.fee
    with pytest.raises(ConflictError):
        wealth.approve_order(db, note, staff.manager.id, "Again", today=TODAY)
    # Within the profile, but too much of the customer's assets in one fund.
    fund = wealth.find_security(db, "AGB-BAL-FUND")
    units = _balance(db, account) // wealth.convert(db, wealth.price_on(fund, TODAY), "GBP",
                                                    "USD", TODAY) // 2  # fmt: skip
    big = _order(db, staff, portfolio, "AGB-BAL-FUND", units)
    assert [r["code"] for r in big.reasons] == ["concentration"]
    # Placed for the dealing desk (workflows): released by someone else.
    placed = _order(db, staff, portfolio, "AGB-MMF-USD", 10, execute=False)
    assert placed.status == "placed"
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        wealth.release_order(db, placed, staff.employee.id, today=TODAY)
    wealth.release_order(db, placed, staff.manager.id, today=TODAY)
    assert placed.status == "executed"
    # Without a current profile nothing can be bought.
    stale = make_customer(db)
    stale_account = open_account(db, staff, stale, AccountType.CURRENT)
    wealth.record_profile(db, stale, objective="growth", horizon_years=20, knowledge="expert",
                          loss_capacity="high", assessed_by=staff.employee.id,
                          today=TODAY - timedelta(days=400))  # fmt: skip
    stale_portfolio = wealth.open_portfolio(db, stale_account, staff.employee.id)
    with pytest.raises(BusinessRuleViolation, match="no current investment profile"):
        _order(db, staff, stale_portfolio, "AGB-MMF-USD", 1)
    assert customer.id != stale.id


def test_income_is_paid_to_holders_and_closures_wait_for_the_portfolio(db: Session) -> None:
    staff = make_staff(db)
    _, account, portfolio = _investor(db, staff)
    buy = _order(db, staff, portfolio, "AGB-CORP-2029", 50)  # a EUR bond in a USD portfolio
    assert buy.status == "executed"
    before = _balance(db, account)
    bond = wealth.find_security(db, "AGB-CORP-2029")
    paid = wealth.distribute_income(db, bond, staff.manager.id, today=TODAY)
    assert paid.distribution_number.startswith("DIS-") and paid.holders >= 1
    expected = wealth.convert(db, 50 * paid.income_per_unit, "EUR", "USD", TODAY)
    assert expected > 0 and _balance(db, account) == before + expected
    with pytest.raises(ConflictError, match="was paid"):
        wealth.distribute_income(db, bond, staff.manager.id, today=TODAY)
    with pytest.raises(BusinessRuleViolation, match="pays no income"):
        wealth.distribute_income(db, wealth.find_security(db, "SN-DIGITAL-TRK"), None,
                                 today=TODAY)  # fmt: skip
    # The account cannot be closed while it pays for an open portfolio.
    with pytest.raises(BusinessRuleViolation, match="pays for portfolio"):
        change_status(db, account.id, AccountStatus.CLOSED, staff.manager.id, "Closing")
    with pytest.raises(BusinessRuleViolation, match="Sell every holding"):
        wealth.close_portfolio(db, portfolio, staff.employee.id)
    _order(db, staff, portfolio, "AGB-CORP-2029", 50, side="sell")
    assert wealth.close_portfolio(db, portfolio, staff.employee.id).status == "closed"
    with pytest.raises(BusinessRuleViolation, match="CLOSED|closed"):
        _order(db, staff, portfolio, "AGB-MMF-USD", 1)


def test_the_wealth_api(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    wealth.ensure_securities(db)
    customer = make_customer(db)
    account = open_account(db, staff, customer, AccountType.CURRENT)
    deposit(db, account.id, amount=10_000_000, memo="Synthetic", actor_id=staff.employee.id,
            idempotency_key=f"wealth-api-{account.id}")  # fmt: skip
    teller, manager, auditor = auth(staff.employee), auth(staff.manager), auth(staff.compliance)
    db.commit()
    securities = client.get("/api/v1/wealth/securities", headers=teller).json()
    assert len(securities) == 10 and all(s["price"] > 0 for s in securities)
    answers = {"customer_number": customer.customer_number, "objective": "balanced",
               "horizon_years": 10, "knowledge": "basic", "loss_capacity": "high"}  # fmt: skip
    assert client.post("/api/v1/wealth/profiles", json=answers, headers=auditor).status_code == 403
    profile = client.post("/api/v1/wealth/profiles", json=answers, headers=teller)
    assert profile.status_code == 201 and profile.json()["risk_profile"] == 4
    opened = client.post("/api/v1/wealth/portfolios", headers=teller,
                         json={"account_number": account.account_number})  # fmt: skip
    assert opened.status_code == 201 and opened.json()["risk_profile"] == 4
    number = opened.json()["portfolio_number"]
    order = {"portfolio_number": number, "security_code": "AGB-GOVT-2031", "side": "buy",
             "units": 10}  # fmt: skip
    done = client.post("/api/v1/wealth/orders", json=order, headers=teller).json()
    assert done["status"] == "executed" and done["currency"] == "USD"
    risky = client.post("/api/v1/wealth/orders", headers=teller,
                        json={**order, "security_code": "EQ-NORTHWIND"}).json()  # fmt: skip
    assert risky["status"] == "awaiting_approval" and risky["reasons"][0]["code"] == (
        "risk_above_profile"
    )
    url = f"/api/v1/wealth/orders/{risky['id']}"
    assert client.post(f"{url}/approve", json={}, headers=teller).status_code == 403
    approved = client.post(f"{url}/approve", json={"note": "Insistent"}, headers=manager).json()
    assert approved["status"] == "executed"
    valuation = client.get(f"/api/v1/wealth/portfolios/{number}/valuation", headers=teller)
    assert {h["security_code"] for h in valuation.json()["holdings"]} == {
        "AGB-GOVT-2031", "EQ-NORTHWIND"
    }  # fmt: skip
    pay = {"security_code": "AGB-GOVT-2031"}
    assert client.post("/api/v1/wealth/distributions", json=pay, headers=teller).status_code == 403
    paid = client.post("/api/v1/wealth/distributions", json=pay, headers=manager)
    assert paid.status_code == 201 and paid.json()["holders"] >= 1
    counts = client.get("/api/v1/wealth/summary/counts", headers=teller).json()
    assert counts["executed"] >= 2 and counts["awaiting_approval"] == 0
