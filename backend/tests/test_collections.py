"""Phase 53: collections and recoveries — payment plans and recoveries on written-off loans."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError
from app.core.permissions import RoleCode
from app.modules.collections import service as collections
from app.modules.ledger import service as ledger
from app.modules.lending import servicing
from app.modules.workflows import wf0004
from tests.factories import auth, make_loan, make_staff, make_user, principal, top_up

ON = date(2040, 3, 25)  # two instalments missed: 44 days past due (see test_loan_servicing)
LATE = date(2040, 5, 15)  # four instalments missed: 95 days past due


def test_payment_plans(db: Session) -> None:
    staff = make_staff(db)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    loan = make_loan(db, staff)
    with pytest.raises(BusinessRuleViolation, match="not in arrears"):
        collections.propose_plan(db, loan, 14, staff.manager.id, today=date(2040, 1, 20))
    servicing.run(db, ON, principal(staff.manager))
    plan = collections.propose_plan(db, loan, 14, staff.manager.id, today=ON)
    assert plan.plan_number.startswith("PLN-") and plan.payments == 2
    assert plan.days_past_due == 44 and [p["due"] for p in plan.schedule] == [
        (ON + timedelta(days=14)).isoformat(),
        (ON + timedelta(days=28)).isoformat(),
    ]
    with pytest.raises(ConflictError):
        collections.propose_plan(db, loan, 14, staff.manager.id, today=ON)
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        collections.decide_plan(db, plan, staff.manager.id, approve=True)
    collections.decide_plan(db, plan, executive.id, approve=True)
    assert plan.status == "active"
    # While the plan is active the loan cannot be written off.
    with pytest.raises(BusinessRuleViolation, match="payment plan"):
        servicing.write_off(db, loan.id, principal(executive), ON)
    # The first payment finds an empty account; the second is covered.
    result = collections.collect(db, ON + timedelta(days=14), principal(staff.manager))
    assert result["missed"] == 1 and plan.missed == 1 and plan.status == "active"
    top_up(db, staff, loan, 2 * loan.monthly_payment)
    result = collections.collect(db, ON + timedelta(days=28), principal(staff.manager))
    assert result["paid"] == 1 and [p["status"] for p in plan.schedule] == ["missed", "paid"]
    # The schedule ran out with a payment missed: the plan is broken.
    assert plan.status == "broken" and result["broken"] == 1
    assert servicing.arrears(db, loan, ON).instalments == 1


def test_a_plan_kept_completes(db: Session) -> None:
    staff = make_staff(db)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    loan = make_loan(db, staff)
    servicing.run(db, ON, principal(staff.manager))
    plan = collections.propose_plan(db, loan, 7, staff.manager.id, today=ON)
    collections.decide_plan(db, plan, executive.id, approve=True)
    top_up(db, staff, loan, 3 * loan.monthly_payment)
    result = collections.collect(db, ON + timedelta(days=14), principal(staff.manager))
    assert result["paid"] == 2 and plan.status == "completed"
    assert servicing.arrears(db, loan, ON).instalments == 0


def test_wf0004_waits_on_a_payment_plan(db: Session) -> None:
    """The WF-0004 case of a loan on an active plan does not escalate to a write-off review;
    once the plan breaks, the next servicing run escalates it."""
    staff = make_staff(db)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    loan = make_loan(db, staff)
    servicing.run(db, ON, principal(staff.manager))
    case = wf0004.open_case_for(db, loan)
    assert case is not None and case.current_steps == ["await_resolution"]
    plan = collections.propose_plan(db, loan, 31, staff.manager.id, today=ON)
    collections.decide_plan(db, plan, executive.id, approve=True)
    servicing.run(db, LATE, principal(staff.manager))  # 95 days past due, plan still active
    assert servicing.arrears(db, loan, LATE).days_past_due >= servicing.WRITE_OFF_DAYS
    assert case.current_steps == ["await_resolution"]
    broke = ON + timedelta(days=62)  # the second payment's due date
    collections.collect(db, broke, principal(staff.manager))  # both payments missed
    assert plan.status == "broken" and plan.missed == 2
    servicing.run(db, broke, principal(staff.manager))
    assert case.current_steps == ["writeoff_review"]


def test_recoveries_on_written_off_loans(db: Session) -> None:
    staff = make_staff(db)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    loan = make_loan(db, staff)
    with pytest.raises(BusinessRuleViolation, match="not written off"):
        collections.record_recovery(db, loan, "payment", 100, staff.manager.id)
    servicing.run(db, LATE, principal(staff.manager))
    servicing.write_off(db, loan.id, principal(executive), LATE)
    written = collections.written_off_amount(db, loan)
    assert written > 0
    payment = collections.record_recovery(db, loan, "payment", 10_000, staff.manager.id)
    assert payment.status == "posted" and payment.entry_number.startswith("JE-")
    assert ledger.balance(db, collections.recoveries_account(db, loan.currency)) == 10_000
    with pytest.raises(BusinessRuleViolation, match="remain to recover"):
        collections.record_recovery(db, loan, "agency", written, staff.manager.id)
    sale = collections.record_recovery(db, loan, "debt_sale", written - 10_000, staff.manager.id)
    assert sale.status == "recorded"  # waits for the credit committee
    with pytest.raises(BusinessRuleViolation, match="remain to recover"):
        collections.record_recovery(db, loan, "payment", 1, staff.manager.id)
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        collections.decide_recovery(db, sale, staff.manager.id, approve=True)
    collections.decide_recovery(db, sale, executive.id, approve=True)
    assert ledger.balance(db, collections.recoveries_account(db, loan.currency)) == written
    book = collections.written_off_book(db)
    row = next(r for r in book if r["loan_number"] == loan.loan_number)
    assert row["recovered"] == written and row["remaining"] == 0


def test_the_collections_api(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    second = make_user(db, RoleCode.DEPARTMENT_MANAGER)  # plans: loans:approve
    loan = make_loan(db, staff)
    servicing.run(db, ON, principal(staff.manager))
    db.commit()
    manager, boss, teller = auth(staff.manager), auth(second), auth(staff.employee)
    book = client.get("/api/v1/collections/arrears", headers=teller).json()
    assert loan.loan_number in [r["loan_number"] for r in book]
    body = {"loan_number": loan.loan_number, "interval_days": 14}
    assert client.post("/api/v1/collections/plans", json=body, headers=teller).status_code == 403
    made = client.post("/api/v1/collections/plans", json=body, headers=manager)
    assert made.status_code == 201 and made.json()["payments"] == 2
    url = f"/api/v1/collections/plans/{made.json()['id']}/approve"
    assert client.post(url, headers=manager).status_code == 422  # four-eyes
    assert client.post(url, headers=boss).json()["status"] == "active"
    collected = client.post("/api/v1/collections/plans/collect",
                            json={"as_of": (ON + timedelta(days=14)).isoformat()},
                            headers=manager)  # fmt: skip
    assert collected.json()["missed"] == 1
    counts = client.get("/api/v1/collections/summary/counts", headers=teller).json()
    assert counts["plans_active"] == 1
