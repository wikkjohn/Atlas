"""Phase 35: commercial lending — facilities, drawdowns, covenants, annual reviews."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError
from app.core.permissions import RoleCode
from app.modules.accounts.models import AccountType
from app.modules.accounts.service import deposit
from app.modules.commercial import service as commercial
from app.modules.customers.models import CustomerType
from app.modules.ledger import service as ledger
from tests.factories import auth, make_customer, make_staff, make_user, open_account

NOW = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
USD_250K = 25_000_000


def _business(db: Session, staff, balance: int = 0):
    customer = make_customer(db, customer_type=CustomerType.BUSINESS, name="Harbour Tools Ltd",
                             born=date(2004, 2, 1))  # fmt: skip
    account = open_account(db, staff, customer, AccountType.BUSINESS_CURRENT)
    if balance:
        deposit(db, account.id, amount=balance, memo="Synthetic", actor_id=staff.employee.id,
                idempotency_key=f"biz-{account.id}")  # fmt: skip
    return customer, account


def _propose(db, staff, customer, account, *, kind="revolving", limit=USD_250K, **kw):
    return commercial.propose_facility(
        db, customer=customer, account=account, facility_type=kind, credit_limit=limit,
        term_months=kw.pop("term", 36), purpose="Working capital",
        requested_by=staff.employee.id, **kw,
    )  # fmt: skip


def _balance(db, ledger_account_id) -> int:
    return ledger.balance(db, ledger.get_ledger_account(db, ledger_account_id))


def test_proposal_rules_and_approval_with_four_eyes(db: Session) -> None:
    staff = make_staff(db)
    customer, account = _business(db, staff)
    person = make_customer(db)
    current = open_account(db, staff, person)
    with pytest.raises(BusinessRuleViolation, match="business customers"):
        _propose(db, staff, person, current)
    with pytest.raises(BusinessRuleViolation, match="limit must be between"):
        _propose(db, staff, customer, account, limit=1_000_000)  # US$10,000
    with pytest.raises(BusinessRuleViolation, match="at most 60"):
        _propose(db, staff, customer, account, term=84)
    facility = _propose(db, staff, customer, account, covenant_thresholds={"min_dscr": 140})
    assert facility.status == "proposed" and facility.annual_rate_bps == 750
    assert {c.kind: c.threshold_centi for c in commercial.covenants(db, facility)} == {
        "min_dscr": 140, "max_leverage": 350,
    }  # fmt: skip
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        commercial.approve_facility(db, facility, staff.employee.id, now=NOW)
    commercial.approve_facility(db, facility, staff.manager.id, now=NOW)
    assert facility.status == "active" and facility.ledger_account_id is not None
    assert facility.review_due_on == NOW.date() + timedelta(days=365)
    assert facility.matures_on == date(2029, 7, 1)


def test_large_facilities_need_the_committee(db: Session) -> None:
    staff = make_staff(db)
    customer, account = _business(db, staff)
    executive = make_user(db, RoleCode.GLOBAL_EXECUTIVE)
    big = _propose(db, staff, customer, account, kind="term_loan", limit=200_000_000, term=60)
    assert commercial.needs_committee(big)
    with pytest.raises(BusinessRuleViolation, match="credit approval comes before"):
        commercial.committee_approve(db, big, executive.id, now=NOW)
    commercial.approve_facility(db, big, staff.manager.id, now=NOW)
    assert big.status == "proposed"  # still waiting for the committee
    with pytest.raises(BusinessRuleViolation, match="third person"):
        commercial.committee_approve(db, big, staff.manager.id, now=NOW)
    commercial.committee_approve(db, big, executive.id, now=NOW)
    assert big.status == "active"
    small = _propose(db, staff, customer, account)
    with pytest.raises(BusinessRuleViolation, match="within the credit approver"):
        commercial.committee_approve(db, small, executive.id, now=NOW)


def test_drawdowns_and_repayments_through_the_ledger(db: Session) -> None:
    staff = make_staff(db)
    customer, account = _business(db, staff, balance=1_000_000)
    revolving = _propose(db, staff, customer, account)
    commercial.approve_facility(db, revolving, staff.manager.id, now=NOW)
    commercial.draw(db, revolving, 10_000_000, staff.employee.id, now=NOW)
    assert _balance(db, account.ledger_account_id) == 11_000_000
    assert _balance(db, revolving.ledger_account_id) == 10_000_000
    with pytest.raises(BusinessRuleViolation, match="Only 15000000 is available"):
        commercial.draw(db, revolving, 20_000_000, None, now=NOW)
    commercial.repay(db, revolving, 6_000_000, staff.employee.id, now=NOW)
    assert revolving.drawn == 4_000_000 and commercial.available(revolving) == 21_000_000
    # A term loan cannot redraw what was repaid.
    term = _propose(db, staff, customer, account, kind="term_loan", term=60)
    commercial.approve_facility(db, term, staff.manager.id, now=NOW)
    commercial.draw(db, term, USD_250K, None, now=NOW)
    commercial.repay(db, term, 5_000_000, None, now=NOW)
    assert commercial.available(term) == 0
    with pytest.raises(BusinessRuleViolation, match="Repay between 1 and"):
        commercial.repay(db, term, 30_000_000, None, now=NOW)  # more than is drawn
    # An overdue annual review stops drawdowns.
    late = NOW + timedelta(days=366)
    with pytest.raises(BusinessRuleViolation, match="review overdue"):
        commercial.draw(db, revolving, 1_000, None, now=late)


def test_a_covenant_breach_freezes_until_the_committee_waives(db: Session) -> None:
    staff = make_staff(db)
    customer, account = _business(db, staff)
    executive = make_user(db, RoleCode.GLOBAL_EXECUTIVE)
    facility = _propose(db, staff, customer, account)
    commercial.approve_facility(db, facility, staff.manager.id, now=NOW)
    healthy = commercial.run_covenant_test(
        db, facility, period_end=date(2026, 3, 31), ebitda=50_000_000, debt_service=20_000_000,
        total_debt=100_000_000, actor_id=staff.employee.id,
    )  # fmt: skip
    assert not healthy.breached
    assert [r["actual_centi"] for r in healthy.results] == [200, 250]  # leverage 2.00×, DSCR 2.50×
    with pytest.raises(ConflictError, match="already tested"):
        commercial.run_covenant_test(db, facility, period_end=date(2026, 3, 31), ebitda=1,
                                     debt_service=1, total_debt=0, actor_id=None)  # fmt: skip
    # DSCR 1.10× (below 1.25×): breached, frozen, no drawdowns.
    breach = commercial.run_covenant_test(
        db, facility, period_end=date(2026, 6, 30), ebitda=22_000_000, debt_service=20_000_000,
        total_debt=60_000_000, actor_id=staff.employee.id,
    )  # fmt: skip
    assert breach.breached and facility.status == "frozen"
    assert "min_dscr" in facility.frozen_reason
    with pytest.raises(BusinessRuleViolation, match="frozen"):
        commercial.draw(db, facility, 1_000, None, now=NOW)
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        commercial.waive_breach(db, breach, staff.employee.id, now=NOW)
    commercial.waive_breach(db, breach, executive.id, now=NOW)
    assert facility.status == "active" and facility.frozen_reason is None
    commercial.draw(db, facility, 1_000, None, now=NOW)


def test_annual_reviews_renew_or_terminate(db: Session) -> None:
    staff = make_staff(db)
    customer, account = _business(db, staff)
    facility = _propose(db, staff, customer, account)
    commercial.approve_facility(db, facility, staff.manager.id, now=NOW)
    with pytest.raises(BusinessRuleViolation, match="opens 60 days before"):
        commercial.open_review(db, facility, staff.employee.id, today=NOW.date())
    due = facility.review_due_on
    review = commercial.open_review(db, facility, staff.employee.id, today=due - timedelta(days=30))
    with pytest.raises(ConflictError, match="open review"):
        commercial.open_review(db, facility, staff.employee.id, today=due)
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        commercial.decide_review(db, review, True, staff.employee.id)
    commercial.decide_review(db, review, True, staff.manager.id, new_limit=30_000_000, now=NOW)
    assert review.outcome == "renewed" and facility.credit_limit == 30_000_000
    assert facility.review_due_on == due + timedelta(days=365)
    second = commercial.open_review(db, facility, staff.employee.id,
                                    today=facility.review_due_on)  # fmt: skip
    commercial.decide_review(db, second, False, staff.manager.id, now=NOW)
    assert facility.status == "terminated"
    with pytest.raises(BusinessRuleViolation, match="terminated"):
        commercial.draw(db, facility, 1_000, None, now=NOW)


def test_the_commercial_api(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    customer, account = _business(db, staff)
    teller, manager = auth(staff.employee), auth(staff.manager)
    executive = auth(make_user(db, RoleCode.GLOBAL_EXECUTIVE))
    db.commit()
    body = {"customer_number": customer.customer_number, "account_number": account.account_number,
            "facility_type": "revolving", "credit_limit": USD_250K, "term_months": 24}  # fmt: skip
    created = client.post("/api/v1/commercial/facilities", json=body, headers=teller)
    assert created.status_code == 201, created.text
    fid = created.json()["id"]
    url = f"/api/v1/commercial/facilities/{fid}"
    assert client.post(f"{url}/approve", headers=teller).status_code == 403
    approved = client.post(f"{url}/approve", headers=manager).json()
    assert approved["status"] == "active" and approved["available"] == USD_250K
    drawn = client.post(f"{url}/draw", json={"amount": 5_000_000}, headers=teller).json()
    assert drawn["drawn"] == 5_000_000 and drawn["available"] == 20_000_000
    figures = {"period_end": "2026-06-30", "ebitda": 10_000_000, "debt_service": 10_000_000,
               "total_debt": 50_000_000}  # fmt: skip
    test = client.post(f"{url}/tests", json=figures, headers=teller).json()
    assert test["breached"]
    listed = client.get("/api/v1/commercial/facilities", headers=teller).json()["items"]
    assert listed[0]["status"] == "frozen" and listed[0]["draw_block"].startswith("frozen")
    assert client.post(f"/api/v1/commercial/tests/{test['id']}/waive",
                       headers=manager).status_code == 403  # fmt: skip
    waived = client.post(f"/api/v1/commercial/tests/{test['id']}/waive", headers=executive)
    assert waived.json()["status"] == "active"
    counts = client.get("/api/v1/commercial/summary/counts", headers=teller).json()
    assert counts["active"] == 1 and counts["frozen"] == 0
