"""Phase 51: customer service — cases, complaints, SLA timers and redress."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError
from app.modules.customer_service import service as cs
from app.modules.customers.models import Customer
from app.modules.ledger import service as ledger
from tests.factories import auth, funded_account, make_staff

T0 = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def _case(db: Session, staff, account, **overrides):
    values = {"category": "request", "channel": "phone", "topic": "card", "priority": "normal",
              "subject": "Replacement card", "description": "Card damaged"}  # fmt: skip
    return cs.open_case(db, db.get(Customer, account.customer_id), opened_by=staff.employee.id,
                        account=account, now=T0, **{**values, **overrides})  # fmt: skip


def test_sla_timers_breaches_and_escalation(db: Session) -> None:
    staff = make_staff(db)
    account = funded_account(db, staff)
    case = _case(db, staff, account)
    assert case.case_number.startswith("SRV-") and case.status == "open"
    assert case.first_response_due == T0 + timedelta(hours=8)
    assert case.resolve_due == T0 + timedelta(hours=72)
    urgent = _case(db, staff, account, priority="urgent", subject="Card stolen")
    assert urgent.first_response_due == T0 + timedelta(hours=1)
    complaint = _case(db, staff, account, category="complaint", subject="Fee charged twice")
    assert complaint.first_response_due == T0 + timedelta(hours=48)
    assert complaint.resolve_due == T0 + timedelta(days=56)
    cs.respond(
        db, urgent, staff.employee.id, "We have blocked the card.", now=T0 + timedelta(minutes=20)
    )
    # Nine hours on: the normal request missed its first response, the urgent one did not.
    result = cs.sweep(db, None, now=T0 + timedelta(hours=9))
    assert result["response_breached"] == 1 and result["resolution_breached"] == 1
    assert case.response_breached and case.priority == "high"  # escalated one priority
    assert urgent.resolution_breached and urgent.escalated and not urgent.response_breached
    assert cs.sweep(db, None, now=T0 + timedelta(hours=9))["checked"] == 0  # nothing new
    assert [e.kind for e in cs.events(db, case)] == ["opened", "response_breached"]


def test_waiting_on_the_customer_pauses_the_clock(db: Session) -> None:
    staff = make_staff(db)
    account = funded_account(db, staff)
    case = _case(db, staff, account)
    cs.respond(
        db, case, staff.employee.id, "Please confirm your address.", now=T0 + timedelta(hours=1)
    )
    cs.await_customer(db, case, staff.employee.id, now=T0 + timedelta(hours=2))
    with pytest.raises(ConflictError):
        cs.await_customer(db, case, staff.employee.id, now=T0 + timedelta(hours=3))
    # Paused past the resolution due time: not breached.
    assert cs.sweep(db, None, now=T0 + timedelta(hours=100))["resolution_breached"] == 0
    cs.resume(db, case, staff.employee.id, now=T0 + timedelta(hours=102))
    assert case.resolve_due == T0 + timedelta(hours=172) and case.paused_seconds == 100 * 3600
    cs.resolve(db, case, staff.employee.id, "Card sent", now=T0 + timedelta(hours=103))
    assert case.status == "resolved" and not case.resolution_breached
    with pytest.raises(ConflictError):
        cs.respond(db, case, staff.employee.id, "Late reply")


def test_complaints_and_redress(db: Session) -> None:
    staff = make_staff(db)
    account = funded_account(db, staff, balance=10_000)
    request = _case(db, staff, account)
    with pytest.raises(BusinessRuleViolation, match="Only complaints"):
        cs.propose_redress(db, request, 500, account, staff.employee.id)
    complaint = _case(db, staff, account, category="complaint", subject="Fee charged twice")
    with pytest.raises(BusinessRuleViolation, match="outcome"):
        cs.resolve(db, complaint, staff.employee.id, "Refunded")
    cs.propose_redress(db, complaint, 2_500, account, staff.employee.id)
    with pytest.raises(BusinessRuleViolation, match="redress first"):
        cs.resolve(db, complaint, staff.employee.id, "Refunded", "upheld")
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        cs.pay_redress(db, complaint, staff.employee.id)
    before = ledger.balance(db, ledger.get_ledger_account(db, account.ledger_account_id))
    cs.pay_redress(db, complaint, staff.manager.id)
    after = ledger.balance(db, ledger.get_ledger_account(db, account.ledger_account_id))
    assert after - before == 2_500 and complaint.redress_entry.startswith("JE-")
    assert ledger.balance(db, cs.redress_account(db, account.currency)) == 2_500
    cs.resolve(db, complaint, staff.employee.id, "Duplicate fee refunded", "upheld")
    assert complaint.outcome == "upheld" and complaint.first_responded_at is not None
    with pytest.raises(BusinessRuleViolation, match="Only complaints"):
        cs.resolve(db, _case(db, staff, account), staff.employee.id, "Done", "upheld")


def test_the_customer_service_api(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    account = funded_account(db, staff)
    customer = db.get(Customer, account.customer_id)
    db.commit()
    teller, manager = auth(staff.employee), auth(staff.manager)
    body = {
        "customer_number": customer.customer_number,
        "account_number": account.account_number,
        "category": "complaint",
        "channel": "email",
        "topic": "fees",
        "priority": "normal",
        "subject": "Overdraft fee",
        "description": "Charged a fee I was not told about",
    }
    made = client.post("/api/v1/customer-service/cases", json=body, headers=teller)
    assert made.status_code == 201 and made.json()["category"] == "complaint"
    url = f"/api/v1/customer-service/cases/{made.json()['id']}"
    assert client.post(f"{url}/respond", json={"message": "We are looking into it."},
                       headers=teller).json()["first_responded_at"]  # fmt: skip
    redress = {"amount": 1_500, "account_number": account.account_number}
    assert (
        client.post(f"{url}/redress", json=redress, headers=teller).json()["redress_status"]
        == "proposed"
    )
    assert client.post(f"{url}/redress/pay", headers=teller).status_code == 403  # service:approve
    assert client.post(f"{url}/redress/pay", headers=manager).json()["redress_status"] == "paid"
    final = {"resolution": "Fee refunded", "outcome": "upheld"}
    resolved = client.post(f"{url}/resolve", json=final, headers=teller)
    assert resolved.json()["status"] == "resolved"
    kinds = [e["kind"] for e in client.get(f"{url}/events", headers=teller).json()]
    assert kinds == ["opened", "responded", "redress_proposed", "redress_paid", "resolved"]
    listed = client.get("/api/v1/customer-service/cases?status=resolved", headers=teller).json()
    assert [c["case_number"] for c in listed["items"]] == [made.json()["case_number"]]
    counts = client.get("/api/v1/customer-service/summary/counts", headers=teller).json()
    assert counts["open"] == 0 and counts["redress_to_approve"] == 0
    assert client.post("/api/v1/customer-service/sweep", headers=teller).json()["checked"] == 0


def test_a_complaints_final_response_runs_while_paused(db: Session) -> None:
    staff = make_staff(db)
    account = funded_account(db, staff)
    complaint = _case(db, staff, account, category="complaint", subject="Branch closed early")
    cs.await_customer(db, complaint, staff.employee.id, now=T0 + timedelta(hours=10))
    cs.resume(db, complaint, staff.employee.id, now=T0 + timedelta(hours=34))
    # The acknowledgement moves by the pause; the eight-week final response does not.
    assert complaint.first_response_due == T0 + timedelta(hours=72)
    assert complaint.resolve_due == T0 + timedelta(days=56)
    cs.await_customer(db, complaint, staff.employee.id, now=T0 + timedelta(days=50))
    result = cs.sweep(db, None, now=T0 + timedelta(days=57))
    assert result["resolution_breached"] == 1 and complaint.escalated
