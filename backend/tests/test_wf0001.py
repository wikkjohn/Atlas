"""WF-0001 Retail Account Opening, end to end through the API."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.modules.accounts.models import Account
from app.modules.customers.models import Customer, CustomerNotification
from app.modules.workflows import engine
from app.modules.workflows.models import WorkflowExecution
from app.modules.workflows.wf0001 import document_number_valid, synthetic_document_number
from tests.factories import application, auth, country, make_staff

START = "/api/v1/workflows/WF-0001/executions"
TASKS = "/api/v1/workflow-tasks"


def _start(client: TestClient, user, payload: dict, **headers: str):
    return client.post(START, json={"input": payload}, headers={**auth(user), **headers})


def _task(client: TestClient, user, execution_id: str, actionable: bool = False) -> dict | None:
    tasks = client.get(f"{TASKS}?actionable={str(actionable).lower()}", headers=auth(user)).json()
    return next((t for t in tasks["items"] if t["execution_id"] == execution_id), None)


def _decide(client: TestClient, user, run_id: str, decision: str, note: str = "ok"):
    return client.post(
        f"{TASKS}/{run_id}/complete", json={"decision": decision, "note": note}, headers=auth(user)
    )


def _accounts(db: Session, customer_id: str) -> int:
    return db.execute(
        select(func.count()).where(Account.customer_id == uuid.UUID(customer_id))
    ).scalar_one()


def test_synthetic_document_numbers_carry_a_check_digit() -> None:
    number = synthetic_document_number("passport", 1234567)

    assert number == "P12345678"
    assert document_number_valid("passport", number)
    assert not document_number_valid("passport", "P12345670")
    assert not document_number_valid("national_id", number)


def test_normal_application_is_approved_and_opens_one_account(
    client: TestClient, db: Session
) -> None:
    staff = make_staff(db)
    started = _start(client, staff.employee, application(name="Ada Lovelace"))
    execution = started.json()

    assert started.status_code == 201
    assert execution["status"] == "waiting"
    assert execution["current_steps"] == ["account_approval"]
    assert execution["context"]["assign_risk_rating"]["rating"] == "low"
    customer_id = execution["context"]["register_customer"]["customer_id"]
    assert _accounts(db, customer_id) == 0  # nothing opens before approval

    # The teller who started it may not approve (no approval permission).
    own = _task(client, staff.employee, execution["id"])
    assert own["can_act"] is False
    assert _decide(client, staff.employee, own["run_id"], "approve").status_code == 403

    task = _task(client, staff.manager, execution["id"], actionable=True)
    done = _decide(client, staff.manager, task["run_id"], "approve").json()

    assert (done["status"], done["outcome"]) == ("completed", "approved")
    assert done["current_steps"] == []
    account_number = done["context"]["open_account"]["account_number"]
    assert _accounts(db, customer_id) == 1
    customer = db.get(Customer, uuid.UUID(customer_id))
    assert (customer.kyc_status, customer.risk_rating) == ("verified", "low")
    account = db.execute(
        select(Account).where(Account.account_number == account_number)
    ).scalar_one()
    assert account.currency == "GBP"
    note = db.execute(
        select(CustomerNotification).where(CustomerNotification.customer_id == customer.id)
    ).scalar_one()
    assert note.subject == "Your account is open" and account_number in note.body
    steps = [s["step_id"] for s in done["steps"]]
    assert steps == [
        "receive_application",
        "validate_application",
        "register_customer",
        "checks",
        "identity_verification",
        "sanctions_screening",
        "checks_complete",
        "assign_risk_rating",
        "evaluate_compliance",
        "ai_kyc_review",  # WF-0001 v2; AI is off unless an experiment turns it on
        "route_case",
        "account_approval",
        "open_account",
        "finalize_records",
        "notify_customer",
        "complete",
    ]
    approval = next(s for s in done["steps"] if s["step_id"] == "account_approval")
    assert approval["actor_username"] == staff.manager.username
    actions = set(
        db.execute(
            select(AuditEvent.action).where(AuditEvent.entity_id == execution["id"])
        ).scalars()
    )
    assert {
        "workflow.started",
        "workflow.task_completed",
        "workflow.account_opening_finalized",
        "workflow.completed",
    } <= actions


def test_rejected_application_creates_no_account(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    execution = _start(client, staff.employee, application()).json()
    task = _task(client, staff.manager, execution["id"])

    done = _decide(client, staff.manager, task["run_id"], "reject", "Income not evidenced").json()

    customer_id = execution["context"]["register_customer"]["customer_id"]
    assert (done["status"], done["outcome"]) == ("completed", "rejected")
    assert _accounts(db, customer_id) == 0
    assert db.get(Customer, uuid.UUID(customer_id)).kyc_status == "rejected"
    assert "Income not evidenced" in done["context"]["reject_application"]["reasons"][0]
    note = db.execute(
        select(CustomerNotification).where(
            CustomerNotification.customer_id == uuid.UUID(customer_id)
        )
    ).scalar_one()
    assert "Income not evidenced" in note.body


def test_high_risk_cases_go_to_compliance_review(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    execution = _start(
        client,
        staff.employee,
        application(politically_exposed=True, expected_monthly_deposits=90_000),
    ).json()

    assert execution["current_steps"] == ["compliance_review"]
    assert execution["context"]["assign_risk_rating"]["rating"] == "high"
    assert execution["context"]["evaluate_compliance"]["flags"] == ["politically_exposed"]
    # A department manager lacks customers:review.
    as_manager = _task(client, staff.manager, execution["id"])
    assert as_manager["can_act"] is False
    assert _decide(client, staff.manager, as_manager["run_id"], "approve").status_code == 403

    done = _decide(client, staff.compliance, as_manager["run_id"], "approve").json()

    assert done["outcome"] == "approved"
    assert done["context"]["open_account"]["approved_by"] == str(staff.compliance.id)


def test_sanctions_hits_are_flagged_for_review(client: TestClient, db: Session) -> None:
    staff = make_staff(db)

    execution = _start(client, staff.employee, application(name="Silas Offshore")).json()

    assert execution["context"]["sanctions_screening"]["hit"] is True
    assert "sanctions_hit" in execution["context"]["evaluate_compliance"]["flags"]
    assert execution["current_steps"] == ["compliance_review"]


def test_invalid_applications_are_rejected_without_a_customer(
    client: TestClient, db: Session
) -> None:
    staff = make_staff(db)
    teen_birthday = (datetime.now(UTC).date().replace(year=datetime.now(UTC).year - 16)).isoformat()
    before = db.execute(select(func.count()).select_from(Customer)).scalar_one()

    done = _start(client, staff.employee, application(born=teen_birthday)).json()

    assert (done["status"], done["outcome"]) == ("completed", "rejected")
    assert "age 18" in done["context"]["validate_application"]["reasons"][0]
    assert done["context"]["notify_customer"]["sent"] is False
    assert db.execute(select(func.count()).select_from(Customer)).scalar_one() == before


def test_forged_documents_are_rejected_without_human_review(
    client: TestClient, db: Session
) -> None:
    staff = make_staff(db)
    payload = application()
    payload["documents"][0]["document_number"] = "P12345670"  # bad check digit

    done = _start(client, staff.employee, payload).json()

    assert done["outcome"] == "rejected"
    assert done["context"]["identity_verification"]["hard_fail"] is True
    assert not any(s["step_type"] == "approval" for s in done["steps"])


def test_missing_documents_wait_then_resume_or_time_out(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    complete = application()
    waiting = _start(client, staff.employee, application(documents=["passport"])).json()
    abandoned = _start(client, staff.employee, application(documents=["passport"])).json()

    assert waiting["current_steps"] == ["await_documents"]
    assert waiting["context"]["validate_application"]["missing"] == ["proof_of_address"]
    resumed = client.post(
        f"/api/v1/workflow-executions/{waiting['id']}/signals",
        json={
            "signal": "documents_submitted",
            "payload": {
                "documents": [
                    complete["documents"][1]
                    | {"name_on_document": waiting["context"]["input"]["applicant_name"]}
                ]
            },
        },
        headers=auth(staff.employee),
    ).json()
    assert resumed["current_steps"] == ["account_approval"]

    execution = db.get(WorkflowExecution, uuid.UUID(abandoned["id"]))
    engine.process_timers(db, execution, datetime.now(UTC) + timedelta(hours=73))
    assert (execution.status, execution.outcome) == ("completed", "rejected")
    assert execution.context["reject_application"]["reasons"] == [
        "Required documents were not received in time."
    ]


def test_required_approvals_cannot_be_skipped(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    execution = _start(client, staff.employee, application()).json()
    task = _task(client, staff.manager, execution["id"])

    resumed = client.post(
        f"/api/v1/workflow-executions/{execution['id']}/resume", headers=auth(staff.admin)
    ).json()
    bad = client.post(f"{TASKS}/{task['run_id']}/complete", json={}, headers=auth(staff.manager))
    teller_resume = client.post(
        f"/api/v1/workflow-executions/{execution['id']}/resume", headers=auth(staff.employee)
    )

    assert resumed["current_steps"] == ["account_approval"]  # resuming does not pass a gate
    assert bad.status_code == 422
    assert teller_resume.status_code == 403
    assert _accounts(db, execution["context"]["register_customer"]["customer_id"]) == 0


def test_duplicate_starts_return_the_same_execution(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    payload = application()

    first = _start(client, staff.employee, payload, **{"Idempotency-Key": "branch-7-app-1"})
    retry = _start(client, staff.employee, payload, **{"Idempotency-Key": "branch-7-app-1"})

    assert first.status_code == 201 and retry.status_code == 200
    assert retry.json()["id"] == first.json()["id"]
    assert (
        db.execute(
            select(func.count()).where(Customer.name == payload["applicant_name"])
        ).scalar_one()
        == 1
    )


def test_a_failing_step_records_a_useful_error(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    execution = _start(client, staff.employee, application(country_code="DE")).json()
    # The country is suspended while the case waits for approval: opening must now fail.
    country(db, "DE").operational_status = "suspended"
    db.flush()
    task = _task(client, staff.manager, execution["id"])

    done = _decide(client, staff.manager, task["run_id"], "approve").json()

    assert (done["status"], done["outcome"]) == ("failed", "failed")
    assert done["error"]["step"] == "open_account"
    assert done["error"]["code"] == "business_rule_violation"
    assert "Germany is not an active country" in str(done["error"]["details"])
    failed = next(s for s in done["steps"] if s["step_id"] == "open_account")
    assert failed["status"] == "failed" and failed["error"]["details"]["reasons"]
    assert _accounts(db, execution["context"]["register_customer"]["customer_id"]) == 0


def test_history_metrics_and_definition_endpoints(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    execution = _start(client, staff.employee, application()).json()
    task = _task(client, staff.manager, execution["id"])
    _decide(client, staff.manager, task["run_id"], "approve")
    headers = auth(staff.employee)

    history = client.get(
        f"/api/v1/workflow-executions/{execution['id']}/history", headers=headers
    ).json()
    metrics = client.get("/api/v1/workflows/WF-0001/metrics", headers=headers).json()
    definition = client.get("/api/v1/workflows/WF-0001", headers=headers).json()
    listing = client.get("/api/v1/workflows?q=onboarding", headers=headers).json()
    executions = client.get(
        f"/api/v1/workflow-executions?business_key={execution['business_key']}", headers=headers
    ).json()

    kinds = [e["event_type"] for e in history]
    assert kinds[0] == "execution.started" and kinds[-1] == "execution.completed"
    assert "task.opened" in kinds and "task.completed" in kinds
    assert metrics["executions"] == {"completed": 1}
    approval = next(s for s in metrics["steps"] if s["step_id"] == "account_approval")
    assert approval["runs"] == 1 and approval["avg_ms"] is not None
    assert definition["approval_policies"][0]["step"] == "compliance_review"
    assert {p["step"] for p in definition["timeout_policies"]} == {
        "await_documents",
        "compliance_review",
        "account_approval",
    }
    assert "applicant_name" in definition["input_schema"]["properties"]
    assert [w["workflow_id"] for w in listing] == ["WF-0001"]
    assert executions["total"] == 1


def test_whoever_starts_a_case_cannot_approve_it(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    # Managers may both start cases and approve them — but never the same case.
    execution = _start(client, staff.manager, application()).json()
    task = _task(client, staff.manager, execution["id"])

    response = _decide(client, staff.manager, task["run_id"], "approve")

    assert task["can_act"] is False and "Four-eyes" in task["blocked_reason"]
    assert response.status_code == 403
    assert response.json()["error"]["details"] == {
        "rule": "four_eyes",
        "distinct_from": "initiator",
    }
    assert _task(client, staff.manager, execution["id"], actionable=True) is None
    assert (
        _decide(client, staff.compliance, task["run_id"], "approve").json()["outcome"] == "approved"
    )
