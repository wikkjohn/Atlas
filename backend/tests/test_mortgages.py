"""Phase 33: mortgages — properties, valuations, quotes, offers, completion."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError
from app.modules.ledger import service as ledger
from app.modules.lending import service as lending
from app.modules.lending.models import LoanInstalment
from app.modules.mortgages import service as mortgages
from tests.factories import auth, funded_account, make_staff, unique_surname

NOW = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
TODAY = NOW.date()
BORN = date(1982, 4, 2)
PRICE = 40_000_000  # US$400,000.00


def _applicant() -> str:
    """A synthetic name with a good bureau file and an income estimate of US$6,000+."""
    for _ in range(50_000):
        name = f"Mara {unique_surname()}"
        if (
            lending.bureau_report(name, BORN)["score"] >= 700
            and lending.bureau_report(name, BORN)["recent_defaults"] == 0
            and lending.income_estimate(name, BORN) >= 6_000
        ):
            return name
    raise AssertionError("No synthetic applicant found.")


def _setup(db: Session):
    staff = make_staff(db)
    account = funded_account(db, staff, name=_applicant(), born=BORN)
    customer = account.customer
    prop = mortgages.register_property(db, customer, "house", PRICE, staff.employee.id)
    income = mortgages.monthly_income_estimate(customer, "USD")
    return staff, account, customer, prop, income


def _quote(db, customer, prop, account, income, amount, product="home-75", years=25, **kw):
    return mortgages.quote(
        db, customer=customer, prop=prop, product=mortgages.get_product(db, product),
        account=account, loan_amount=amount, term_years=years,
        declared_monthly_income=kw.pop("declared", income), today=kw.pop("today", TODAY),
    )  # fmt: skip


def _failed(result) -> set[str]:
    return {c["rule"] for c in result["checks"] if not c["passed"]}


def test_properties_and_valuations(db: Session) -> None:
    staff, _, customer, prop, _ = _setup(db)
    assert prop.property_number.startswith("PRP-") and prop.currency == "USD"
    assert prop.country_code == "US" and prop.address
    desktop = mortgages.value_property(db, prop, "desktop", today=TODAY)
    assert desktop.valued_by is None and desktop.value == mortgages.desktop_value(prop)
    assert 0.85 * PRICE <= desktop.value <= 1.15 * PRICE
    with pytest.raises(BusinessRuleViolation, match="positive value"):
        mortgages.value_property(db, prop, "surveyor", actor_id=staff.manager.id)
    surveyed = mortgages.value_property(
        db, prop, "surveyor", value=39_000_000, actor_id=staff.manager.id,
        today=TODAY + timedelta(days=1),
    )  # fmt: skip
    assert mortgages.latest_valuation(db, prop).id == surveyed.id


def test_the_lending_rules(db: Session) -> None:
    staff, account, customer, prop, income = _setup(db)
    # No valuation yet.
    assert "valuation" in _failed(_quote(db, customer, prop, account, income, 10_000_000))
    mortgages.value_property(db, prop, "surveyor", value=PRICE, actor_id=staff.manager.id,
                             today=TODAY)  # fmt: skip
    # A loan the income supports at 25 % of the price passes every rule.
    amount = 10_000_000
    ok = _quote(db, customer, prop, account, income, amount)
    assert ok["eligible"], _failed(ok)
    assert ok["ltv_bps"] == 2500
    assert ok["monthly_payment"] == lending.monthly_payment(amount, 449, 300)
    # 80 % is above home-75's maximum but within home-90's (if affordable).
    big = _quote(db, customer, prop, account, income * 10, 32_000_000, declared=income * 10)
    assert "loan_to_value" in _failed(big)
    assert "loan_to_value" not in _failed(
        _quote(db, customer, prop, account, income, 32_000_000, product="home-90")
    )
    # Unaffordable on declared income; declared income far above the bureau's estimate.
    assert "affordability" in _failed(
        _quote(db, customer, prop, account, income, amount, declared=income // 10)
    )
    assert "income_supported" in _failed(
        _quote(db, customer, prop, account, income, amount, declared=income * 2)
    )
    # A stale valuation; a term too long.
    assert "valuation" in _failed(
        _quote(db, customer, prop, account, income, amount, today=TODAY + timedelta(days=181))
    )
    assert "term" in _failed(_quote(db, customer, prop, account, income, amount, years=36))


def test_a_desktop_valuation_supports_only_low_loan_to_value(db: Session) -> None:
    staff, account, customer, prop, income = _setup(db)
    desktop = mortgages.value_property(db, prop, "desktop", today=TODAY)
    basis = min(desktop.value, PRICE)
    high = _quote(db, customer, prop, account, income, basis * 8 // 10, product="home-90")
    assert "valuation_method" in _failed(high)
    low = _quote(db, customer, prop, account, income, basis // 2)
    assert "valuation_method" not in _failed(low)


def test_an_offer_from_application_to_completion(db: Session) -> None:
    staff, account, customer, prop, income = _setup(db)
    mortgages.value_property(db, prop, "surveyor", value=PRICE, actor_id=staff.manager.id,
                             today=TODAY)  # fmt: skip
    amount = 12_000_000
    apply = dict(customer=customer, prop=prop, product=mortgages.get_product(db, "home-75"),
                 account=account, loan_amount=amount, term_years=25,
                 declared_monthly_income=income, today=TODAY)  # fmt: skip
    with pytest.raises(BusinessRuleViolation, match="affordability"):
        mortgages.request_offer(db, **{**apply, "declared_monthly_income": 1},
                                requested_by=staff.employee.id)  # fmt: skip
    offer = mortgages.request_offer(db, **apply, requested_by=staff.employee.id)
    assert offer.status == "pending" and offer.offer_number.startswith("MOF-")
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        mortgages.decide_offer(db, offer, True, staff.employee.id, now=NOW)
    # One live offer per property.
    with pytest.raises(BusinessRuleViolation, match="unencumbered"):
        mortgages.request_offer(db, **apply, requested_by=staff.employee.id)
    mortgages.decide_offer(db, offer, True, staff.manager.id, now=NOW)
    assert offer.status == "offered" and offer.expires_on == TODAY + timedelta(days=90)
    mortgages.accept_offer(db, offer, staff.employee.id, now=NOW + timedelta(days=10))
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        mortgages.complete_offer(db, offer, staff.employee.id, now=NOW + timedelta(days=30))
    before = ledger.balance(db, ledger.get_ledger_account(db, account.ledger_account_id))
    loan = mortgages.complete_offer(db, offer, staff.manager.id, now=NOW + timedelta(days=30))
    assert offer.status == "completed" and offer.loan_id == loan.id
    assert loan.purpose == "mortgage" and loan.term_months == 300 and loan.property_id == prop.id
    assert loan.principal == amount and loan.underwritten_by == staff.manager.id
    after = ledger.balance(db, ledger.get_ledger_account(db, account.ledger_account_id))
    assert after - before == amount
    instalments = db.query(LoanInstalment).filter(LoanInstalment.loan_id == loan.id).count()
    assert instalments == 300
    assert mortgages.charged_loan(db, prop).id == loan.id
    assert "unencumbered" in _failed(_quote(db, customer, prop, account, income, amount))


def test_declined_withdrawn_and_expired_offers(db: Session) -> None:
    staff, account, customer, prop, income = _setup(db)
    mortgages.value_property(db, prop, "desktop", today=TODAY)
    apply = dict(customer=customer, prop=prop, product=mortgages.get_product(db, "home-75"),
                 account=account, loan_amount=8_000_000, term_years=20,
                 declared_monthly_income=income, today=TODAY)  # fmt: skip
    declined = mortgages.request_offer(db, **apply, requested_by=staff.employee.id)
    mortgages.decide_offer(db, declined, False, staff.manager.id, now=NOW)
    assert declined.status == "declined" and declined.expires_on is None
    with pytest.raises(ConflictError):
        mortgages.accept_offer(db, declined, None, now=NOW)
    expiring = mortgages.request_offer(db, **apply, requested_by=staff.employee.id)
    mortgages.decide_offer(db, expiring, True, staff.manager.id, now=NOW)
    with pytest.raises(BusinessRuleViolation, match="expired"):
        mortgages.accept_offer(db, expiring, None, now=NOW + timedelta(days=91))
    mortgages.withdraw_offer(db, expiring, staff.employee.id)
    assert expiring.status == "withdrawn"


def test_the_mortgages_api(client: TestClient, db: Session) -> None:
    staff, account, customer, _, income = _setup(db)
    teller, manager = auth(staff.employee), auth(staff.manager)
    db.commit()
    products = client.get("/api/v1/mortgages/products", headers=teller).json()
    assert [p["product_code"] for p in products] == ["home-75", "home-90"]
    created = client.post(
        "/api/v1/mortgages/properties",
        json={"customer_number": customer.customer_number, "property_type": "flat",
              "purchase_price": PRICE},
        headers=teller,
    )  # fmt: skip
    assert created.status_code == 201, created.text
    prop = created.json()
    url = f"/api/v1/mortgages/properties/{prop['id']}/valuations"
    surveyor = {"method": "surveyor", "value": PRICE}
    assert client.post(url, json=surveyor, headers=teller).status_code == 403
    assert client.post(url, json=surveyor, headers=manager).status_code == 201
    body = {"customer_number": customer.customer_number, "property_number": prop["property_number"],
            "product_code": "home-75", "account_number": account.account_number,
            "loan_amount": 10_000_000, "term_years": 25,
            "declared_monthly_income": income}  # fmt: skip
    quoted = client.post("/api/v1/mortgages/quote", json=body, headers=teller).json()
    assert quoted["eligible"] and quoted["ltv_bps"] == 2500
    offer = client.post("/api/v1/mortgages/offers", json=body, headers=teller)
    assert offer.status_code == 201, offer.text
    oid = offer.json()["id"]
    assert client.post(f"/api/v1/mortgages/offers/{oid}/decide", json={"approve": True},
                       headers=teller).status_code == 403  # fmt: skip
    decided = client.post(f"/api/v1/mortgages/offers/{oid}/decide", json={"approve": True},
                          headers=manager)  # fmt: skip
    assert decided.json()["status"] == "offered"
    assert client.post(f"/api/v1/mortgages/offers/{oid}/accept", headers=teller).status_code == 200
    completed = client.post(f"/api/v1/mortgages/offers/{oid}/complete", headers=manager).json()
    assert completed["status"] == "completed" and completed["loan_number"].startswith("LN-")
    listed = client.get("/api/v1/mortgages/properties", headers=teller).json()["items"]
    assert listed[0]["charged_loan_number"] == completed["loan_number"]
    counts = client.get("/api/v1/mortgages/summary/counts", headers=teller).json()
    assert counts["active_mortgages"] == 1
    # The mortgage is an ordinary loan to the lending API.
    loans = client.get("/api/v1/loans", headers=manager).json()["items"]
    mortgage = next(loan for loan in loans if loan["loan_number"] == completed["loan_number"])
    assert mortgage["purpose"] == "mortgage" and mortgage["term_months"] == 300
