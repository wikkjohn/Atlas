"""Phase 45: compliance — transaction monitoring, alerts, cases, SARs and KYC reviews."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError
from app.core.permissions import RoleCode
from app.modules.accounts.models import AccountType
from app.modules.accounts.service import deposit, withdraw
from app.modules.compliance import service as compliance
from tests.factories import auth, make_customer, make_staff, make_user, open_account

D = date(2026, 10, 1)
LIMIT = compliance.threshold("USD")  # US$10,000 in cents


def _activity(deposits=(), credits=0, debits=0):
    return {"deposits": list(deposits), "credits": credits, "debits": debits}


def test_the_monitoring_rules() -> None:
    assert LIMIT == 1_000_000
    near = [(D, 900_000), (D + timedelta(days=3), 950_000), (D + timedelta(days=8), 920_000)]
    rules = [h["rule"] for h in compliance.evaluate(_activity(near, 2_770_000), "USD", "low")]
    assert rules == ["structuring"]
    spread = [(D, 900_000), (D + timedelta(days=6), 950_000), (D + timedelta(days=12), 920_000)]
    assert compliance.evaluate(_activity(spread, 2_770_000), "USD", "low") == []
    [large] = compliance.evaluate(_activity([(D, 1_500_000)], 1_500_000), "USD", "low")
    assert large["rule"] == "large_cash" and large["amount"] == 1_500_000
    through = compliance.evaluate(_activity(credits=3_000_000, debits=2_700_000), "USD", "low")
    assert [h["rule"] for h in through] == ["rapid_movement"]
    assert compliance.evaluate(_activity(credits=3_000_000, debits=1_000_000), "USD", "low") == []
    busy = compliance.evaluate(_activity(credits=6_000_000), "USD", "high")
    assert [h["rule"] for h in busy] == ["high_risk_turnover"]
    assert compliance.evaluate(_activity(credits=6_000_000), "USD", "medium") == []


def _structurer(db: Session, staff):
    customer = make_customer(db)
    account = open_account(db, staff, customer, AccountType.CURRENT)
    for n, amount in enumerate((900_000, 950_000, 920_000)):
        deposit(db, account.id, amount=amount, memo="Cash", actor_id=staff.employee.id,
                idempotency_key=f"aml-{account.id}-{n}")  # fmt: skip
    withdraw(db, account.id, amount=2_500_000, memo="Cash out", actor_id=staff.employee.id,
             idempotency_key=f"aml-out-{account.id}")  # fmt: skip
    return customer, account


def test_monitoring_raises_alerts_once(db: Session) -> None:
    staff = make_staff(db)
    customer, account = _structurer(db, staff)
    run = compliance.run_monitoring(db, account_ids=[account.id])
    assert run.run_number.startswith("MON-") and run.accounts_scanned == 1
    assert run.alerts_raised == 2
    again = compliance.run_monitoring(db, account_ids=[account.id])
    assert again.alerts_raised == 0  # the open alerts are not raised twice
    quiet = open_account(db, staff, make_customer(db), AccountType.CURRENT)
    deposit(db, quiet.id, amount=50_000, memo="Salary", actor_id=staff.employee.id,
            idempotency_key=f"aml-quiet-{quiet.id}")  # fmt: skip
    assert compliance.run_monitoring(db, account_ids=[quiet.id]).alerts_raised == 0
    assert customer.id


def test_cases_close_or_escalate_to_a_filed_report(db: Session) -> None:
    staff = make_staff(db)
    officer, mlro = (
        make_user(db, RoleCode.COMPLIANCE_OFFICER),
        make_user(db, RoleCode.COMPLIANCE_OFFICER),
    )
    customer, account = _structurer(db, staff)
    compliance.run_monitoring(db, account_ids=[account.id])
    from sqlalchemy import select

    from app.modules.compliance.models import AmlAlert

    first, second = db.execute(
        select(AmlAlert).where(AmlAlert.account_id == account.id).order_by(AmlAlert.alert_number)
    ).scalars().all()  # fmt: skip
    case_row = compliance.open_case(db, first, officer.id)
    assert case_row.case_number.startswith("CASE-")
    assert {a.alert_number for a in compliance.case_alerts(db, case_row)} == {
        first.alert_number, second.alert_number
    }  # fmt: skip
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        compliance.close_case(db, case_row, officer.id, "Nothing")
    sar = compliance.draft_sar(db, case_row, officer.id)
    assert sar.status == "draft" and customer.customer_number in sar.narrative
    assert sar.amount == first.amount + second.amount
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        compliance.file_sar(db, sar, officer.id)
    compliance.file_sar(db, sar, mlro.id, today=D)
    assert sar.status == "filed" and sar.filing_reference == f"FIU-2026-{sar.sar_number[4:]}"
    assert case_row.status == "sar_filed" and customer.risk_rating == "high"
    assert {a.status for a in compliance.case_alerts(db, case_row)} == {"escalated"}
    with pytest.raises(ConflictError):
        compliance.file_sar(db, sar, mlro.id)
    # Another customer: an alert dismissed, another closed with no action by a second officer.
    _, other = _structurer(db, staff)
    compliance.run_monitoring(db, account_ids=[other.id])
    a1, a2 = db.execute(
        select(AmlAlert).where(AmlAlert.account_id == other.id).order_by(AmlAlert.alert_number)
    ).scalars().all()  # fmt: skip
    assert compliance.dismiss_alert(db, a2, officer.id, "Payroll cash").status == "dismissed"
    closing = compliance.open_case(db, a1, officer.id)
    assert [a.alert_number for a in compliance.case_alerts(db, closing)] == [a1.alert_number]
    compliance.close_case(db, closing, mlro.id, "Explained by the business")
    assert closing.status == "closed" and a1.status == "closed"


def test_kyc_reviews_fall_due_by_risk_rating(db: Session) -> None:
    staff = make_staff(db)
    officer = make_user(db, RoleCode.COMPLIANCE_OFFICER)
    low = make_customer(db)  # rated low: every three years
    high = make_customer(db)
    from app.modules.customers.models import RiskRating
    from app.modules.customers.schemas import CustomerReview
    from app.modules.customers.service import review_customer

    review_customer(db, high, CustomerReview(risk_rating=RiskRating.HIGH), staff.admin.id)
    joined = datetime.now(UTC).date()
    compliance.schedule_reviews(db, joined + timedelta(days=340), horizon_days=30)
    review = compliance.open_review(db, high)
    assert review.due_on == joined + timedelta(days=365) and review.risk_before == "high"
    assert compliance.open_review(db, high).id == review.id  # one due at a time
    assert compliance.open_review(db, low).due_on == datetime.now(UTC).date()  # opened on demand
    done = compliance.complete_review(db, review, officer.id, "medium", "Activity explained")
    assert done.outcome == "lowered" and high.risk_rating == "medium"
    with pytest.raises(ConflictError):
        compliance.complete_review(db, review, officer.id, "medium")
    # The next review falls due by the new rating, two years after this one.
    later = done.completed_on + timedelta(days=700)
    compliance.schedule_reviews(db, later, horizon_days=30)
    assert compliance.open_review(db, high).due_on == done.completed_on + timedelta(days=730)


def test_the_compliance_api(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    officer, mlro = (
        make_user(db, RoleCode.COMPLIANCE_OFFICER),
        make_user(db, RoleCode.COMPLIANCE_OFFICER),
    )
    _, account = _structurer(db, staff)
    db.commit()
    teller, first, second = auth(staff.employee), auth(officer), auth(mlro)
    assert client.get("/api/v1/compliance/alerts", headers=teller).status_code == 403
    assert client.post("/api/v1/compliance/runs", json={}, headers=teller).status_code == 403
    run = client.post("/api/v1/compliance/runs", json={"days": 30}, headers=first)
    assert run.status_code == 201 and run.json()["alerts_raised"] >= 2
    url = f"/api/v1/compliance/alerts?status=open&account_number={account.account_number}"
    mine = client.get(url, headers=first).json()["items"]
    assert mine and all(a["account_number"] == account.account_number for a in mine)
    assert {a["rule"] for a in mine} == {"structuring", "rapid_movement"}
    case_row = client.post(f"/api/v1/compliance/alerts/{mine[0]['id']}/investigate",
                           headers=first).json()  # fmt: skip
    assert sorted(case_row["alerts"]) == sorted(a["alert_number"] for a in mine)
    sar = client.post(f"/api/v1/compliance/cases/{case_row['id']}/sar", json={}, headers=first)
    assert sar.status_code == 201
    url = f"/api/v1/compliance/sars/{sar.json()['id']}/file"
    assert client.post(url, headers=first).status_code == 422  # four-eyes
    filed = client.post(url, headers=second).json()
    assert filed["status"] == "filed" and filed["filing_reference"].startswith("FIU-")
    counts = client.get("/api/v1/compliance/summary/counts", headers=second).json()
    assert counts["filed_sars"] >= 1


def test_pr36_review_fixes(client: TestClient, db: Session) -> None:
    """A rerun skips a resolved alert's window; a customer's new alert waits while their
    report is drafted; compliance workflows need compliance permissions to start and read."""
    import json

    from app.modules.workflows import authoring
    from app.modules.workflows.examples import HERE

    staff = make_staff(db)
    officer = make_user(db, RoleCode.COMPLIANCE_OFFICER)
    customer, account = _structurer(db, staff)
    compliance.run_monitoring(db, account_ids=[account.id])
    structuring = compliance.find_open_alert(db, account.id, "structuring")
    compliance.dismiss_alert(db, structuring, officer.id, "Explained")
    # The same window again: the dismissed alert is not raised again, and nothing fails.
    assert compliance.run_monitoring(db, account_ids=[account.id]).alerts_raised == 0
    rapid = compliance.find_open_alert(db, account.id, "rapid_movement")
    case_row = compliance.open_case(db, rapid, officer.id)
    compliance.draft_sar(db, case_row, officer.id)
    other = open_account(db, staff, customer, AccountType.SAVINGS)
    for n in range(3):
        deposit(db, other.id, amount=950_000, memo="Cash", actor_id=staff.employee.id,
                idempotency_key=f"pr36-{other.id}-{n}")  # fmt: skip
    compliance.run_monitoring(db, account_ids=[other.id])
    late = compliance.find_open_alert(db, other.id, "structuring")
    with pytest.raises(BusinessRuleViolation, match="report is drafted"):
        compliance.open_case(db, late, officer.id)
    # Starting and reading WF-1027 through the API.
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    authoring.import_definition(db, json.loads((HERE / "WF-1027.json").read_text()), admin.id)
    db.commit()
    url = "/api/v1/workflows/WF-1027/executions"
    body = {"input": {"alert_number": late.alert_number}}
    assert client.post(url, json=body, headers=auth(staff.employee)).status_code == 403
    started = client.post(url, json=body, headers=auth(officer))
    assert started.status_code == 201
    execution = f"/api/v1/workflow-executions/{started.json()['id']}"
    assert client.get(execution, headers=auth(staff.employee)).status_code == 404
    assert client.get(execution, headers=auth(officer)).status_code == 200
    listed = client.get("/api/v1/workflow-executions?workflow_id=WF-1027",
                        headers=auth(staff.employee)).json()  # fmt: skip
    assert listed["total"] == 0
    assert client.get("/api/v1/workflow-executions?workflow_id=WF-1027",
                      headers=auth(officer)).json()["total"] == 1  # fmt: skip
