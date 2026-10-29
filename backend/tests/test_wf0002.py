"""WF-0002 Domestic Payment: straight-through, held, high-value and refused payments."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, PermissionDeniedError
from app.core.permissions import RoleCode
from app.modules.accounts.models import AccountStatus
from app.modules.accounts.service import change_status, withdraw
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.customers.models import CustomerNotification
from app.modules.identity.models import User
from app.modules.ledger import service as ledger
from app.modules.payments import service as payments
from app.modules.payments.models import Payment
from app.modules.workflows import engine
from app.modules.workflows.principals import POLICY_ENGINE_USERNAME
from app.seed import DEMO_AI_TOOLS
from tests.factories import (
    auth,
    funded_account,
    make_staff,
    make_user,
    payment,
    principal,
)

START = "/api/v1/workflows/WF-0002/executions"
TASKS = "/api/v1/workflow-tasks"


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


def _balance(db: Session, account) -> int:
    return ledger.balance(db, ledger.get_ledger_account(db, account.ledger_account_id))


def _payment(db: Session, execution: dict) -> Payment:
    payment_id = execution["context"]["validate_payment"]["payment_id"]
    return db.get(Payment, uuid.UUID(payment_id))


def test_an_ordinary_payment_goes_straight_through(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    debtor = funded_account(db, staff, balance=500_000)
    creditor = funded_account(db, staff)

    done = _start(client, staff.employee, payment(debtor, creditor, 12_500))

    assert (done["status"], done["outcome"]) == ("completed", "approved")
    assert done["context"]["screen_payment"]["flags"] == ["new_payee"]
    assert done["context"]["release_payment"]["straight_through"] is True
    assert _balance(db, debtor) == 487_500
    assert _balance(db, creditor) == 12_500
    record = _payment(db, done)
    assert (record.status, record.approved_by) == ("released", None)
    assert done["business_key"] == record.payment_number
    note = db.execute(
        select(CustomerNotification).where(
            CustomerNotification.workflow_execution_id == uuid.UUID(done["id"])
        )
    ).scalar_one()
    assert note.subject == "Payment sent" and note.customer_id == debtor.customer_id
    listed = client.get(
        "/api/v1/payments", params={"q": record.payment_number}, headers=auth(staff.employee)
    ).json()
    assert listed["items"][0]["status"] == "released"
    assert listed["items"][0]["debtor_account_number"] == debtor.account_number


def test_high_value_payment_needs_a_second_person(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    debtor = funded_account(db, staff, balance=5_000_000)
    creditor = funded_account(db, staff)

    held = _start(client, staff.manager, payment(debtor, creditor, 1_500_000))

    assert held["status"] == "waiting" and held["current_steps"] == ["payment_approval"]
    assert _balance(db, debtor) == 5_000_000  # nothing moves before approval
    own = _task(client, staff.manager, held["id"])
    assert own["can_act"] is False  # the manager started it: four-eyes
    assert _decide(client, staff.manager, own["run_id"], "approve").status_code == 403
    teller = _task(client, staff.employee, held["id"])
    assert _decide(client, staff.employee, teller["run_id"], "approve").status_code == 403

    other_manager = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    done = _decide(client, other_manager, own["run_id"], "approve").json()

    assert (done["status"], done["outcome"]) == ("completed", "approved")
    assert _balance(db, creditor) == 1_500_000
    assert _payment(db, done).approved_by == other_manager.id


def test_scam_payment_is_held_for_fraud_review_and_can_be_stopped(
    client: TestClient, db: Session
) -> None:
    staff = make_staff(db)
    debtor = funded_account(db, staff, balance=300_000)
    creditor = funded_account(db, staff)

    held = _start(
        client,
        staff.employee,
        payment(debtor, creditor, 50_000, reference="Gift card codes for the tax office"),
    )

    screen = held["context"]["screen_payment"]
    assert screen["hold"] is True and set(screen["flags"]) == {"scam_reference", "new_payee"}
    assert held["current_steps"] == ["fraud_review"]
    # Approvers of high-value payments cannot clear fraud holds.
    assert _task(client, staff.manager, held["id"])["can_act"] is False
    task = _task(client, staff.compliance, held["id"])
    done = _decide(client, staff.compliance, task["run_id"], "reject").json()

    assert (done["status"], done["outcome"]) == ("completed", "rejected")
    assert _balance(db, debtor) == 300_000
    record = _payment(db, done)
    assert record.status == "rejected" and "fraud review" in record.rejection_reason


def test_fraud_reviewer_can_clear_a_held_payment(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    debtor = funded_account(db, staff, balance=100_000)
    creditor = funded_account(db, staff)

    # 90 % of the balance to a new payee: held, but legitimate.
    held = _start(client, staff.employee, payment(debtor, creditor, 90_000))
    assert set(held["context"]["screen_payment"]["flags"]) == {"drains_account", "new_payee"}
    task = _task(client, staff.compliance, held["id"])
    done = _decide(client, staff.compliance, task["run_id"], "approve").json()

    assert done["outcome"] == "approved"
    assert _payment(db, done).approved_by == staff.compliance.id
    assert _balance(db, creditor) == 90_000


def test_payee_on_the_synthetic_watchlist_is_high_risk(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    debtor = funded_account(db, staff, balance=100_000)
    creditor = funded_account(db, staff, name="Silas Offshore")

    held = _start(client, staff.employee, payment(debtor, creditor, 1_000))

    screen = held["context"]["screen_payment"]
    assert (screen["risk"], screen["hold"]) == ("high", True)
    assert "sanctions_hit" in screen["flags"]
    task = _task(client, staff.compliance, held["id"])
    assert task["subject"].startswith("10.00 USD to ")
    assert task["risk_rating"] == "high"


def test_insufficient_funds_and_invalid_accounts_are_refused(
    client: TestClient, db: Session
) -> None:
    staff = make_staff(db)
    debtor = funded_account(db, staff, balance=1_000)
    creditor = funded_account(db, staff)

    poor = _start(client, staff.employee, payment(debtor, creditor, 5_000))
    assert poor["outcome"] == "rejected"
    assert poor["context"]["reject_payment"]["reasons"] == ["Insufficient funds."]
    assert _payment(db, poor).status == "rejected"

    change_status(db, creditor.id, AccountStatus.FROZEN, staff.admin.id, "test")
    frozen = _start(client, staff.employee, payment(debtor, creditor, 100))
    assert frozen["outcome"] == "rejected"
    assert "The payee account is frozen." in frozen["context"]["reject_payment"]["reasons"]
    assert "payment_id" not in frozen["context"]["validate_payment"]  # nothing was created

    same = _start(client, staff.employee, payment(debtor, debtor, 100))
    assert same["outcome"] == "rejected"


def test_release_rechecks_funds_under_the_lock(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    debtor = funded_account(db, staff, balance=5_000_000)
    creditor = funded_account(db, staff)
    held = _start(client, staff.employee, payment(debtor, creditor, 2_000_000))
    assert held["current_steps"] == ["payment_approval"]
    # The money leaves the account while the payment waits for approval.
    withdraw(
        db,
        debtor.id,
        amount=4_000_000,
        memo=None,
        idempotency_key=str(uuid.uuid4()),
        actor_id=staff.employee.id,
    )

    task = _task(client, staff.manager, held["id"])
    done = _decide(client, staff.manager, task["run_id"], "approve").json()

    assert (done["status"], done["outcome"]) == ("completed", "rejected")
    assert any("Insufficient funds" in r for r in done["context"]["reject_payment"]["reasons"])
    assert _balance(db, creditor) == 0


def test_payment_service_enforces_its_controls_for_every_caller(db: Session) -> None:
    staff = make_staff(db)
    debtor = funded_account(db, staff, balance=5_000_000)
    creditor = funded_account(db, staff)
    big = payments.create_payment(
        db,
        debtor=debtor,
        creditor=creditor,
        amount=1_000_000,
        reference="x",
        initiated_by=staff.employee.id,
    )
    with pytest.raises(PermissionDeniedError) as nobody:
        payments.release(db, big.id, approver=None)
    assert nobody.value.details == {"rule": "high_value_requires_approval"}
    with pytest.raises(PermissionDeniedError) as reviewer:
        payments.release(db, big.id, approver=principal(staff.compliance))
    assert reviewer.value.details == {"rule": "high_value_requires_approval"}
    with pytest.raises(PermissionDeniedError) as own:
        payments.release(db, big.id, approver=principal(staff.employee))
    assert own.value.details == {"rule": "four_eyes"}
    engine_user = db.execute(
        select(User).where(User.username == POLICY_ENGINE_USERNAME)
    ).scalar_one()
    with pytest.raises(PermissionDeniedError):
        payments.release(db, big.id, approver=principal(engine_user))
    with pytest.raises(BusinessRuleViolation):
        payments.create_payment(
            db,
            debtor=debtor,
            creditor=creditor,
            amount=10**12,
            reference="x",
            initiated_by=staff.employee.id,
        )
    released = payments.release(db, big.id, approver=principal(staff.manager))
    assert released.status == "released"


def _register_screener(db: Session):
    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-payment-fraud-screener")
    return register_tool(db, ToolCreate.model_validate(spec), actor_id=None)


def test_automated_mode_releases_low_risk_holds_but_never_scams(db: Session) -> None:
    staff = make_staff(db)
    tool = _register_screener(db)
    settings = {"ai_mode": "automated", "ai_tool_id": str(tool.id)}

    def run(amount: int, reference: str) -> dict:
        debtor = funded_account(db, staff, balance=100_000)
        creditor = funded_account(db, staff)
        execution, _ = engine.start(
            db,
            workflow_id="WF-0002",
            payload=payment(debtor, creditor, amount, reference=reference),
            initiator=principal(staff.employee),
            settings=settings,
        )
        return execution.context | {"_status": execution.status, "_outcome": execution.outcome}

    legit = run(90_000, "Rent October")  # held: drains the account, new payee
    assert legit["ai_fraud_review"]["recommendation"] == "approve"
    assert legit["policy_release"]["approved"] is True
    assert legit["_outcome"] == "approved"

    scam = run(50_000, "Crypto investment opportunity")
    assert scam["ai_fraud_review"]["recommendation"] == "reject"
    assert scam["_status"] == "waiting" and "policy_release" not in scam  # to a person

    # Switching the policy engine off sends every held payment to a person.
    db.execute(
        select(User).where(User.username == POLICY_ENGINE_USERNAME)
    ).scalar_one().is_active = False
    off = run(90_000, "Rent November")
    assert off["policy_release"]["failed_checks"] == ["policy_engine_unavailable"]
    assert off["_status"] == "waiting"


def test_cancelling_a_held_payment_rejects_it(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    debtor = funded_account(db, staff, balance=5_000_000)
    creditor = funded_account(db, staff)
    held = _start(client, staff.employee, payment(debtor, creditor, 1_500_000))
    assert held["current_steps"] == ["payment_approval"]

    response = client.post(
        f"/api/v1/workflow-executions/{held['id']}/cancel",
        json={"reason": "Customer withdrew the instruction"},
        headers=auth(staff.admin),
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    record = _payment(db, held)
    assert record.status == "rejected"
    assert record.rejection_reason == "Workflow cancelled: Customer withdrew the instruction"
    assert _balance(db, debtor) == 5_000_000
