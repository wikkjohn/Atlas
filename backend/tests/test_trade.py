"""Phase 37: trade finance — letters of credit, guarantees, presentations and claims."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError
from app.core.permissions import RoleCode
from app.modules.accounts.models import AccountType
from app.modules.accounts.service import deposit
from app.modules.customers.models import CustomerType
from app.modules.ledger import service as ledger
from app.modules.trade import service as trade
from tests.factories import auth, make_customer, make_staff, make_user, open_account

NOW = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
TODAY = NOW.date()
EXPIRY = TODAY + timedelta(days=120)


def _business(db: Session, staff, balance: int = 10_000_000):
    customer = make_customer(db, customer_type=CustomerType.BUSINESS, name="Meridian Foods Ltd",
                             born=date(2006, 1, 1))  # fmt: skip
    account = open_account(db, staff, customer, AccountType.BUSINESS_CURRENT)
    if balance:
        deposit(db, account.id, amount=balance, memo="Synthetic", actor_id=staff.employee.id,
                idempotency_key=f"trade-{account.id}")  # fmt: skip
    return customer, account


def _request(db, staff, customer, account, *, kind="letter_of_credit", amount=5_000_000, **kw):
    return trade.request_instrument(
        db, customer=customer, account=account, kind=kind,
        beneficiary_name=kw.pop("beneficiary", "Saigon Coffee Exporters"),
        beneficiary_country="VN", amount=amount, expires_on=kw.pop("expires_on", EXPIRY),
        purpose="Green coffee, 18 tonnes", requested_by=staff.employee.id, today=TODAY,
    )  # fmt: skip


def _balance(db, ledger_account_id) -> int:
    return ledger.balance(db, ledger.get_ledger_account(db, ledger_account_id))


def test_request_rules_and_sanctions_screening(db: Session) -> None:
    staff = make_staff(db)
    customer, account = _business(db, staff)
    with pytest.raises(BusinessRuleViolation, match="sanctions list synthetic-un-v1"):
        _request(db, staff, customer, account, beneficiary="Ivan Ironvault")
    with pytest.raises(BusinessRuleViolation, match="amount must be between"):
        _request(db, staff, customer, account, amount=100_000)  # US$1,000
    with pytest.raises(BusinessRuleViolation, match="Expiry must be"):
        _request(db, staff, customer, account, expires_on=TODAY + timedelta(days=10))
    person = make_customer(db)
    with pytest.raises(BusinessRuleViolation, match="business customers"):
        _request(db, staff, person, open_account(db, staff, person))
    lc = _request(db, staff, customer, account)
    assert lc.instrument_number.startswith("LC-") and lc.status == "requested"
    assert lc.margin == 1_000_000 and lc.screening["hit"] is False  # 20 % margin
    bg = _request(db, staff, customer, account, kind="guarantee")
    assert bg.instrument_number.startswith("BG-") and bg.margin == 500_000  # 10 %


def test_issuing_takes_the_margin_with_four_eyes_and_the_committee(db: Session) -> None:
    staff = make_staff(db)
    customer, account = _business(db, staff, balance=60_000_000)
    lc = _request(db, staff, customer, account)
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        trade.approve_instrument(db, lc, staff.employee.id, now=NOW)
    trade.approve_instrument(db, lc, staff.manager.id, now=NOW)
    assert lc.status == "issued"
    assert _balance(db, account.ledger_account_id) == 59_000_000
    assert _balance(db, trade.margin_account(db, "USD").id) == 1_000_000
    big = _request(db, staff, customer, account, amount=200_000_000)  # US$2m
    trade.approve_instrument(db, big, staff.manager.id, now=NOW)
    assert big.status == "requested" and trade.needs_committee(big)
    with pytest.raises(BusinessRuleViolation, match="third person"):
        trade.committee_approve(db, big, staff.manager.id, now=NOW)
    executive = make_user(db, RoleCode.GLOBAL_EXECUTIVE)
    trade.committee_approve(db, big, executive.id, now=NOW)  # 20 % margin: 40,000,000
    assert big.status == "issued" and _balance(db, account.ledger_account_id) == 19_000_000
    # Another US$2m would need 40,000,000 of margin; 19,000,000 is left.
    again = _request(db, staff, customer, account, amount=200_000_000)
    trade.approve_instrument(db, again, staff.manager.id, now=NOW)
    with pytest.raises(BusinessRuleViolation, match="cannot provide"):
        trade.committee_approve(db, again, executive.id, now=NOW)


def test_documents_discrepancies_and_payment(db: Session) -> None:
    staff = make_staff(db)
    customer, account = _business(db, staff)
    lc = _request(db, staff, customer, account)
    trade.approve_instrument(db, lc, staff.manager.id, now=NOW)
    with pytest.raises(BusinessRuleViolation, match="Unknown discrepancies"):
        trade.receive_demand(db, lc, amount=1_000, presented_on=TODAY, discrepancies=["typo"],
                             received_by=staff.employee.id)  # fmt: skip
    first = trade.receive_demand(
        db, lc, amount=2_000_000, presented_on=TODAY, discrepancies=["late_shipment"],
        received_by=staff.employee.id,
    )  # fmt: skip
    with pytest.raises(ConflictError, match="still being checked"):
        trade.receive_demand(db, lc, amount=1_000, presented_on=TODAY, received_by=None)
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        trade.pay_demand(db, first, staff.employee.id, now=NOW)
    trade.pay_demand(db, first, staff.manager.id, now=NOW)  # the applicant waived it
    assert first.status == "paid" and first.decision_note.startswith("Discrepancies waived")
    # 40 % drawn: 40 % of the margin released: 10,000,000 - 1,000,000 + 400,000 - 2,000,000.
    assert lc.drawn == 2_000_000 and lc.margin == 600_000
    assert _balance(db, account.ledger_account_id) == 7_400_000
    assert _balance(db, trade.settlement_account(db, "USD").id) == 2_000_000
    rest = trade.receive_demand(db, lc, amount=3_000_000, presented_on=TODAY, received_by=None)
    trade.pay_demand(db, rest, staff.manager.id, now=NOW)
    assert lc.status == "paid" and lc.margin == 0
    assert _balance(db, trade.margin_account(db, "USD").id) == 0


def test_guarantee_claims_rejection_and_expiry(db: Session) -> None:
    staff = make_staff(db)
    customer, account = _business(db, staff)
    bg = _request(db, staff, customer, account, kind="guarantee")
    trade.approve_instrument(db, bg, staff.manager.id, now=NOW)
    with pytest.raises(BusinessRuleViolation, match="pays on demand"):
        trade.receive_demand(db, bg, amount=1_000, presented_on=TODAY,
                             discrepancies=["late_shipment"], received_by=None)  # fmt: skip
    claim = trade.receive_demand(db, bg, amount=5_000_000, presented_on=TODAY,
                                 received_by=staff.employee.id)  # fmt: skip
    trade.reject_demand(db, claim, staff.manager.id, "Claimed for the wrong contract")
    assert claim.status == "rejected" and bg.status == "issued"
    with pytest.raises(BusinessRuleViolation, match="expired"):
        trade.receive_demand(db, bg, amount=1_000, presented_on=EXPIRY + timedelta(days=1),
                             received_by=None)  # fmt: skip
    with pytest.raises(BusinessRuleViolation, match="valid until"):
        trade.expire_instrument(db, bg, staff.manager.id, today=EXPIRY)
    before = _balance(db, account.ledger_account_id)
    trade.expire_instrument(db, bg, staff.manager.id, today=EXPIRY + timedelta(days=1))
    assert bg.status == "expired" and bg.margin == 0
    assert _balance(db, account.ledger_account_id) == before + 500_000


def test_the_trade_api(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    customer, account = _business(db, staff)
    teller, manager = auth(staff.employee), auth(staff.manager)
    db.commit()
    body = {"kind": "letter_of_credit", "customer_number": customer.customer_number,
            "account_number": account.account_number, "beneficiary_name": "Saigon Coffee Exporters",
            "beneficiary_country": "VN", "amount": 5_000_000,
            "expires_on": (date.today() + timedelta(days=90)).isoformat()}  # fmt: skip
    sanctioned = {**body, "beneficiary_name": "Harriet Holdco"}
    listed = client.post("/api/v1/trade/instruments", json=sanctioned, headers=teller)
    assert listed.status_code == 422 and "sanctions" in listed.text
    created = client.post("/api/v1/trade/instruments", json=body, headers=teller)
    assert created.status_code == 201, created.text
    url = f"/api/v1/trade/instruments/{created.json()['id']}"
    assert client.post(f"{url}/approve", headers=teller).status_code == 403
    assert client.post(f"{url}/approve", headers=manager).json()["status"] == "issued"
    demand = client.post(f"{url}/demands", headers=teller, json={
        "amount": 5_000_000, "presented_on": date.today().isoformat(),
        "discrepancies": ["missing_document"]})  # fmt: skip
    assert demand.status_code == 201 and demand.json()["discrepancies"] == ["missing_document"]
    did = demand.json()["id"]
    assert client.post(f"/api/v1/trade/demands/{did}/pay", headers=teller).status_code == 403
    paid = client.post(f"/api/v1/trade/demands/{did}/pay", headers=manager).json()
    assert paid["status"] == "paid"
    instruments = client.get("/api/v1/trade/instruments", headers=teller).json()["items"]
    assert instruments[0]["status"] == "paid" and instruments[0]["margin"] == 0
    assert client.get("/api/v1/trade/summary/counts", headers=teller).json()["paid"] == 1


def test_pr28_review_fixes(db: Session) -> None:
    """An approval after expiry issues nothing; a live instrument's account cannot be closed;
    the workflows accept every supported currency's amounts."""
    import json

    from app.modules.accounts.models import AccountStatus
    from app.modules.accounts.service import change_status
    from app.modules.workflows.examples import HERE

    staff = make_staff(db)
    customer, account = _business(db, staff)
    lc = _request(db, staff, customer, account)
    late = datetime.combine(EXPIRY + timedelta(days=1), NOW.timetz())
    with pytest.raises(BusinessRuleViolation, match="expired on .* before it was approved"):
        trade.approve_instrument(db, lc, staff.manager.id, now=late)
    assert lc.status == "requested" and lc.approved_by is None
    assert _balance(db, account.ledger_account_id) == 10_000_000  # no margin taken
    # A requested (then issued) instrument keeps its account open until it is closed.
    with pytest.raises(
        BusinessRuleViolation, match=f"backs trade instrument {lc.instrument_number}"
    ):
        change_status(db, account.id, AccountStatus.CLOSED, staff.manager.id, "Closing")
    trade.decline_instrument(db, lc, staff.manager.id)
    with pytest.raises(BusinessRuleViolation, match="zero balance"):  # the next rule applies
        change_status(db, account.id, AccountStatus.CLOSED, staff.manager.id, "Closing")
    # US$5m in Lebanese pounds is the largest amount any supported currency reaches.
    assert trade.amount_range("LBP")[1] == 45_000_000_000_000
    for name in ("WF-1015-v2.json", "WF-1016-v2.json", "WF-1017-v2.json"):
        schema = json.loads((HERE / name).read_text())["input_schema"]["properties"]["amount"]
        assert schema["maximum"] >= trade.amount_range("LBP")[1], name
    committee = next(s for s in json.loads((HERE / "WF-1015-v2.json").read_text())["steps"]
                     if s["id"] == "committee")  # fmt: skip
    assert committee["approval"]["distinct_from"] == ["initiator", "credit_approval"]
