"""WF-0003 Personal Loan Origination: credit policy, underwriting, committee, disbursement."""

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import PermissionDeniedError
from app.core.permissions import RoleCode
from app.modules.ledger import service as ledger
from app.modules.lending import service as lending
from app.modules.lending.models import Loan
from tests.factories import (
    applicant_with_score,
    auth,
    funded_account,
    loan_application,
    make_staff,
    make_user,
    principal,
)

START = "/api/v1/workflows/WF-0003/executions"
TASKS = "/api/v1/workflow-tasks"
BORN = date(1980, 3, 9)


def _start(client: TestClient, user, payload: dict) -> dict:
    response = client.post(START, json={"input": payload}, headers=auth(user))
    assert response.status_code == 201, response.text
    return response.json()


def _task(client: TestClient, user, execution_id: str) -> dict | None:
    tasks = client.get(f"{TASKS}?actionable=false", headers=auth(user)).json()
    return next((t for t in tasks["items"] if t["execution_id"] == execution_id), None)


def _decide(client: TestClient, user, run_id: str, decision: str):
    return client.post(
        f"{TASKS}/{run_id}/complete", json={"decision": decision, "note": "ok"}, headers=auth(user)
    )


def _borrower(db: Session, staff, low: int = 720, high: int = 850):
    account = funded_account(db, staff, name=applicant_with_score(low, high, BORN), born=BORN)
    return account.customer, account


def _balance(db: Session, ledger_account_id) -> int:
    return ledger.balance(db, ledger.get_ledger_account(db, ledger_account_id))


def test_bureau_reports_and_pricing_are_deterministic() -> None:
    report = lending.bureau_report("Ada  LOVELACE", date(1815, 12, 10))
    assert report == lending.bureau_report("ada lovelace", date(1815, 12, 10))
    assert 300 <= report["score"] <= 850
    assert lending.rate_for(800) == 690 and lending.rate_for(600) == 1590
    assert lending.rate_for(500) is None
    # 10,000.00 over 12 months at 12 %: the textbook instalment of 888.49.
    assert lending.monthly_payment(1_000_000, 1200, 12) == 88_849


def test_a_good_application_is_underwritten_and_paid_out(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    customer, account = _borrower(db, staff)

    waiting = _start(client, staff.employee, loan_application(customer, account, 1_000_000))

    assert waiting["current_steps"] == ["underwriting_review"]
    assert waiting["context"]["credit_policy"]["decision"] == "refer"
    assert waiting["context"]["affordability"]["committee_required"] is False
    task = _task(client, staff.manager, waiting["id"])
    assert task["subject"] == customer.name and task["can_act"] is True
    assert _task(client, staff.employee, waiting["id"])["can_act"] is False

    done = _decide(client, staff.manager, task["run_id"], "approve").json()

    assert (done["status"], done["outcome"]) == ("completed", "approved")
    loan = db.get(Loan, uuid.UUID(done["context"]["disburse_loan"]["loan_id"]))
    assert (loan.principal, loan.underwritten_by, loan.committee_approved_by) == (
        1_000_000,
        staff.manager.id,
        None,
    )
    assert _balance(db, account.ledger_account_id) == 1_000_000
    assert _balance(db, loan.ledger_account_id) == 1_000_000  # the bank's receivable
    listed = client.get(
        "/api/v1/loans", params={"customer_id": str(customer.id)}, headers=auth(staff.employee)
    ).json()
    assert listed["items"][0]["outstanding"] == 1_000_000
    assert listed["items"][0]["underwritten_by_username"] == staff.manager.username


def test_large_loans_also_need_the_credit_committee(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    customer, account = _borrower(db, staff)
    waiting = _start(
        client,
        staff.employee,
        loan_application(customer, account, 4_000_000, monthly_income=2_000_000),
    )
    first = _task(client, staff.manager, waiting["id"])
    after = _decide(client, staff.manager, first["run_id"], "approve").json()
    assert after["current_steps"] == ["credit_committee"]

    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    assert _task(client, staff.manager, waiting["id"])["can_act"] is False
    task = _task(client, executive, waiting["id"])
    done = _decide(client, executive, task["run_id"], "approve").json()

    assert done["outcome"] == "approved"
    loan = db.get(Loan, uuid.UUID(done["context"]["disburse_loan"]["loan_id"]))
    assert loan.committee_approved_by == executive.id


@pytest.mark.parametrize(
    ("score_band", "overrides", "reason"),
    [
        ((300, 560), {}, "below the minimum"),
        ((720, 850), {"monthly_income": 100_000, "monthly_debt_payments": 60_000}, "Debt-to"),
        ((720, 850), {"employment_status": "unemployed"}, "No income"),
    ],
)
def test_credit_policy_declines_without_a_person(
    client: TestClient, db: Session, score_band, overrides, reason
) -> None:
    staff = make_staff(db)
    customer, account = _borrower(db, staff, *score_band)

    done = _start(client, staff.employee, loan_application(customer, account, 500_000, **overrides))

    assert (done["status"], done["outcome"]) == ("completed", "rejected")
    assert any(reason in r for r in done["context"]["decline_application"]["reasons"])
    assert "underwriting_review" not in done["context"]


def test_someone_elses_account_and_out_of_range_amounts_are_invalid(
    client: TestClient, db: Session
) -> None:
    staff = make_staff(db)
    customer, _ = _borrower(db, staff)
    stranger = funded_account(db, staff)

    done = _start(client, staff.employee, loan_application(customer, stranger, 500_000))
    assert done["outcome"] == "rejected"
    assert "belongs to someone else" in " ".join(done["context"]["validate_application"]["reasons"])

    _, own = _borrower(db, staff)
    tiny = _start(client, staff.employee, loan_application(own.customer, own, 5_000))
    assert tiny["outcome"] == "rejected"


def test_lending_service_enforces_four_eyes_and_the_committee(db: Session) -> None:
    staff = make_staff(db)
    customer, account = _borrower(db, staff)
    common = dict(
        customer_id=customer.id,
        account_id=account.id,
        annual_rate_bps=690,
        term_months=24,
        purpose="vehicle",
    )
    with pytest.raises(PermissionDeniedError) as own:
        lending.originate(
            db,
            principal=500_000,
            requested_by=staff.manager.id,
            underwriter=principal(staff.manager),
            committee=None,
            **common,
        )
    assert own.value.details == {"rule": "four_eyes"}
    with pytest.raises(PermissionDeniedError) as teller:
        lending.originate(
            db,
            principal=500_000,
            requested_by=staff.manager.id,
            underwriter=principal(staff.employee),
            committee=None,
            **common,
        )
    assert teller.value.details == {"rule": "underwriter_without_authority"}
    with pytest.raises(PermissionDeniedError) as large:
        lending.originate(
            db,
            principal=3_000_000,
            requested_by=staff.employee.id,
            underwriter=principal(staff.manager),
            committee=None,
            **common,
        )
    assert large.value.details == {"rule": "committee_required"}
