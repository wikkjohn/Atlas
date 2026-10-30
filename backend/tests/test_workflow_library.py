"""Phase 18: the step-handler library's domain handlers, run by stored definitions —
customers, accounts and fees, screening, AI advice — and the rule that money moves only
behind an approval."""

import copy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.accounts.service import charge_fee, fee_income_account
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.customers.models import Customer, CustomerNotification
from app.modules.ledger import service as ledger
from app.modules.workflows import authoring, engine, examples, library, validation
from app.modules.workflows.models import WorkflowStepRun
from app.seed import DEMO_AI_TOOLS
from tests.factories import application, auth, funded_account, make_staff, make_user, principal


def example(workflow_id: str, version: int = 1, as_id: str | None = None) -> dict:
    (found,) = [
        d for d in examples.documents()
        if d["workflow_id"] == workflow_id and d["version"] == version
    ]  # fmt: skip
    doc = copy.deepcopy(found)
    if as_id:
        doc["workflow_id"] = as_id
    return doc


def steps(doc: dict) -> dict[str, dict]:
    return {s["id"]: s for s in doc["steps"]}


def errors(doc: dict, db: Session | None = None) -> set[tuple[str, str]]:
    return {(e["location"], e["code"]) for e in validation.validate(db, doc).errors}


def test_the_library_declares_effects_and_approvals() -> None:
    effects = {name: (h.effect, h.requires_approval) for name, h in library.LIBRARY.items()}
    assert effects["accounts.charge_fee"] == ("moves_money", True)
    assert effects["customers.notify"] == ("writes", False)
    assert effects["customers.lookup"] == ("reads", False)
    assert effects["ai.review"] == ("advisory", False)
    assert library.LIBRARY["ai.review"].step_type == "ai_task"
    # Nothing but a fee moves money, and every such handler demands an approval.
    assert all(h.requires_approval for h in library.LIBRARY.values() if h.effect == "moves_money")


def test_the_examples_validate_and_report_their_effects() -> None:
    for doc in examples.documents():
        report = validation.validate(None, doc)
        assert report.valid and report.warnings == [], (doc["workflow_id"], report.errors)
    report = validation.validate(None, example("WF-1002"))
    assert [s for s, e in report.effects.items() if e == "moves_money"] == ["charge_fee"]


def test_money_moves_only_through_an_approval_s_approve_route() -> None:
    # Skipping the approval: post deliveries go straight to the fee.
    direct = example("WF-1002", as_id="WF-1902")
    steps(direct)["route_delivery"]["next"] = "charge_fee"
    assert ("steps.charge_fee", "approval_required") in errors(direct)
    # Through the approval, but on its reject route.
    rejected = example("WF-1002", as_id="WF-1902")
    steps(rejected)["fee_approval"]["next"] = "charge_fee"
    assert ("steps.charge_fee", "approval_required") in errors(rejected)
    # A condition that does not depend on the approval's decision does not count.
    unrelated = example("WF-1002", as_id="WF-1902")
    steps(unrelated)["fee_approval"]["transitions"][0]["when"] = {
        "path": "input.delivery", "op": "eq", "value": "post"
    }  # fmt: skip
    assert ("steps.charge_fee", "approval_required") in errors(unrelated)
    # decision == "approve" is an approve route too.
    explicit = example("WF-1002", as_id="WF-1902")
    steps(explicit)["fee_approval"]["transitions"][0]["when"] = {
        "path": "fee_approval.decision", "op": "eq", "value": "approve"
    }  # fmt: skip
    assert errors(explicit) == set()


def test_handler_kinds_params_and_tools_are_checked(db: Session) -> None:
    doc = example("WF-1002", as_id="WF-1902")
    by_id = steps(doc)
    by_id["charge_fee"]["params"]["amount_path"] = "input.months"  # both amount and a path
    by_id["produce"].update(type="ai_task")  # a service handler on an AI step
    by_id["find_customer"]["handler"] = "ai.review"  # an AI handler on a service step
    found = errors(doc)
    assert ("steps.charge_fee.params", "value_error") in found
    assert ("steps.produce.handler", "handler_type_mismatch") in found
    assert ("steps.find_customer.handler", "handler_type_mismatch") in found

    ai = _ai_document("no-such-tool")
    assert ("steps.advice.params", "handler_check") in errors(ai, db)
    assert ("steps.advice.params", "handler_check") not in errors(ai)  # no database: skipped
    _kyc_tool(db)
    assert errors(_ai_document("agb-intelligent-kyc-assistant"), db) == set()
    wrong_action = _ai_document("agb-intelligent-kyc-assistant")
    steps(wrong_action)["advice"]["params"]["action"] = "analyze_payment"
    assert ("steps.advice.params", "handler_check") in errors(wrong_action, db)


def _kyc_tool(db: Session):
    return register_tool(db, ToolCreate.model_validate(DEMO_AI_TOOLS[0]), actor_id=None)


def _ai_document(tool_id: str) -> dict:
    return {
        "workflow_id": "WF-1903",
        "name": "AI second opinion",
        "version": 1,
        "description": "Asks the KYC assistant about an application; a person decides.",
        "business_owner": "AI Innovation Lab",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["application", "as_of"],
            "properties": {"application": {"type": "object"}, "as_of": {"type": "string"}},
        },
        "presentation": {"subject_path": "input.application.applicant_name"},
        "start": "advice",
        "steps": [
            {
                "id": "advice",
                "type": "ai_task",
                "name": "Ask the KYC assistant",
                "handler": "ai.review",
                "params": {
                    "tool_id": tool_id,
                    "action": "analyze_application",
                    "payload": {"application": "input.application", "as_of": "input.as_of"},
                },
                "transitions": [
                    {
                        "to": "auto_ok",
                        "when": {"path": "advice.recommendation", "op": "eq", "value": "approve"},
                    }  # fmt: skip
                ],
                "next": "escalated",
            },
            {"id": "auto_ok", "type": "completion", "name": "Advised", "outcome": "advised"},
            {"id": "escalated", "type": "completion", "name": "Escalated", "outcome": "escalated"},
        ],
    }


def test_ai_review_advises_and_escalates_safely(db: Session) -> None:
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    _kyc_tool(db)
    authoring.import_definition(db, _ai_document("agb-intelligent-kyc-assistant"), admin.id)
    clerk = principal(make_user(db, RoleCode.BANKING_EMPLOYEE))
    clean = {"application": application(name="Ada Lovelace"), "as_of": "2026-01-05"}

    advised, _ = engine.start(db, workflow_id="WF-1903", payload=clean, initiator=clerk)
    assert (advised.outcome, advised.context["advice"]["available"]) == ("advised", True)
    assert advised.context["advice"]["tool_id"] == "agb-intelligent-kyc-assistant"
    # An input the tool rejects is not an error for the case: it escalates to people.
    broken = {"application": {"applicant_name": "Ada"}, "as_of": "2026-01-05"}
    escalated, _ = engine.start(db, workflow_id="WF-1903", payload=broken, initiator=clerk)
    assert escalated.outcome == "escalated"
    assert escalated.context["advice"] | {"error": None} == {
        "available": False, "recommendation": "escalate", "error": None,
        "invocation_status": escalated.context["advice"]["invocation_status"],
        "tool_id": "agb-intelligent-kyc-assistant",
        "tool_version": DEMO_AI_TOOLS[0]["tool_version"],
        "invocation_id": escalated.context["advice"]["invocation_id"],
    }  # fmt: skip


@pytest.fixture
def statements(db: Session):
    """WF-1002 imported under a test id, a funded account and the people who act."""
    staff = make_staff(db)
    authoring.import_definition(db, example("WF-1002", as_id="WF-1902"), staff.admin.id)
    account = funded_account(db, staff, balance=10_000)
    customer = db.get(Customer, account.customer_id)
    request = {
        "customer_number": customer.customer_number,
        "account_number": account.account_number,
        "months": 3,
        "delivery": "post",
    }
    return staff, account, customer, request


def _waiting(db: Session, execution) -> WorkflowStepRun:
    db.flush()
    return db.execute(
        select(WorkflowStepRun).where(
            WorkflowStepRun.execution_id == execution.id, WorkflowStepRun.status == "waiting"
        )
    ).scalar_one()


def _balance(db: Session, account) -> int:
    return ledger.balance(db, ledger.get_ledger_account(db, account.ledger_account_id))


def test_a_fee_is_charged_once_after_approval_and_the_customer_is_told(
    db: Session, statements
) -> None:
    staff, account, customer, request = statements
    clerk, manager = principal(staff.employee), principal(staff.manager)
    income = fee_income_account(db, account.currency)
    income_before = ledger.balance(db, income)

    execution, _ = engine.start(db, workflow_id="WF-1902", payload=request, initiator=clerk)
    assert execution.current_steps == ["fee_approval"]
    assert execution.context["find_account"]["balance"] == 10_000
    assert _balance(db, account) == 10_000  # nothing moves before the approval
    engine.complete_task(db, _waiting(db, execution).id, manager, decision="approve")

    assert (execution.status, execution.outcome) == ("completed", "sent")
    fee = execution.context["charge_fee"]
    assert (fee["amount"], fee["currency"]) == (500, account.currency)
    assert _balance(db, account) == 9_500
    assert ledger.balance(db, income) - income_before == 500
    letter = db.execute(
        select(CustomerNotification).where(
            CustomerNotification.workflow_execution_id == execution.id
        )
    ).scalar_one()
    assert letter.customer_id == customer.id
    assert letter.body == (
        f"Dear {customer.name}, 3 months of statements for account {account.account_number} "
        "are on their way by post."
    )
    # Replaying the step's posting (a retry) posts nothing new.
    charge_run = db.execute(
        select(WorkflowStepRun).where(
            WorkflowStepRun.execution_id == execution.id, WorkflowStepRun.step_id == "charge_fee"
        )
    ).scalar_one()
    _, number, replayed = charge_fee(
        db, account.id, amount=500, fee_code="paper_statement", memo="Paper statements",
        idempotency_key=f"workflow:{charge_run.id}", actor_id=None,
    )  # fmt: skip
    assert (number, replayed) == (fee["entry_number"], True)
    assert _balance(db, account) == 9_500


def test_statement_paths_without_a_fee(db: Session, statements) -> None:
    staff, account, customer, request = statements
    clerk, manager = principal(staff.employee), principal(staff.manager)

    by_email, _ = engine.start(
        db, workflow_id="WF-1902", payload={**request, "delivery": "email"}, initiator=clerk
    )
    assert (by_email.outcome, "charge_fee" in by_email.context) == ("sent", False)

    declined, _ = engine.start(db, workflow_id="WF-1902", payload=request, initiator=clerk)
    engine.complete_task(db, _waiting(db, declined).id, manager, decision="reject")
    assert declined.outcome == "declined"

    stranger = funded_account(db, staff, balance=10_000)
    theirs = {**request, "account_number": stranger.account_number}
    refused, _ = engine.start(db, workflow_id="WF-1902", payload=theirs, initiator=clerk)
    assert refused.outcome == "refused"
    assert refused.context["_failure"]["code"] == "account_not_owned"

    unknown, _ = engine.start(
        db, workflow_id="WF-1902", payload={**request, "customer_number": "CUS-0999999999"},
        initiator=clerk,
    )  # fmt: skip
    assert unknown.outcome == "rejected"
    assert _balance(db, account) == 10_000


def test_insufficient_funds_fail_the_fee_and_explain_it(db: Session, statements) -> None:
    staff, _, _, request = statements
    poor = funded_account(db, staff, balance=200)
    owner = db.get(Customer, poor.customer_id)
    mine = {**request, "account_number": poor.account_number,
            "customer_number": owner.customer_number}  # fmt: skip
    execution, _ = engine.start(
        db, workflow_id="WF-1902", payload=mine, initiator=principal(staff.employee)
    )
    engine.complete_task(
        db, _waiting(db, execution).id, principal(staff.manager), decision="approve"
    )
    assert execution.outcome == "refused"
    assert _balance(db, poor) == 200
    letter = db.execute(
        select(CustomerNotification.body).where(
            CustomerNotification.workflow_execution_id == execution.id
        )
    ).scalar_one()
    assert letter.endswith("Insufficient funds for the fee.")


def test_address_change_v2_finds_screens_and_writes_to_the_customer(db: Session) -> None:
    staff = make_staff(db)
    authoring.import_definition(db, example("WF-1001", 1, as_id="WF-1901"), staff.admin.id)
    authoring.import_definition(db, example("WF-1001", 2, as_id="WF-1901"), staff.admin.id)
    account = funded_account(db, staff)
    customer = db.get(Customer, account.customer_id)
    move = {"customer_number": customer.customer_number, "street": "1 Synthetic Way",
            "city": "Testville", "postal_code": "TS1 1AA", "country_code": "GB",
            "reason": "moved"}  # fmt: skip
    clerk = principal(staff.employee)

    execution, _ = engine.start(db, workflow_id="WF-1901", payload=move, initiator=clerk)
    assert execution.workflow_version == 2
    assert execution.current_steps == ["colleague_review"]
    engine.complete_task(db, _waiting(db, execution).id, principal(staff.manager),
                         decision="approve")  # fmt: skip
    assert execution.outcome == "updated"
    letter = db.execute(
        select(CustomerNotification).where(
            CustomerNotification.workflow_execution_id == execution.id
        )
    ).scalar_one()
    assert letter.channel == "simulated_letter"
    assert "1 Synthetic Way, Testville TS1 1AA" in letter.body

    # A watchlisted name goes to compliance whatever the reason.
    listed = funded_account(db, staff, name="Silas Offshore")
    flagged = db.get(Customer, listed.customer_id)
    screened, _ = engine.start(
        db, workflow_id="WF-1901", initiator=clerk,
        payload={**move, "customer_number": flagged.customer_number, "reason": "correction"},
    )  # fmt: skip
    assert screened.current_steps == ["compliance_review"]
    assert screened.context["screen_name"]["hit"] is True

    nobody, _ = engine.start(
        db, workflow_id="WF-1901", initiator=clerk,
        payload={**move, "customer_number": "CUS-0999999999"},
    )  # fmt: skip
    assert (nobody.outcome, nobody.context["_failure"]["code"]) == (
        "rejected", "customer_not_found")  # fmt: skip


def test_set_risk_rating_and_the_handlers_api(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    account = funded_account(db, staff)
    doc = {
        "workflow_id": "WF-1904",
        "name": "Re-rate a customer",
        "version": 1,
        "description": "Records a reviewer's risk rating.",
        "business_owner": "Compliance",
        "input_schema": {"type": "object", "additionalProperties": False,
                         "required": ["customer_number"],
                         "properties": {"customer_number": {"type": "string"}}},  # fmt: skip
        "presentation": {"subject_path": "find.name"},
        "start": "find",
        "steps": [
            {"id": "find", "type": "service_task", "name": "Find", "handler": "customers.lookup",
             "params": {"customer_number_path": "input.customer_number"}, "next": "rate"},
            {"id": "rate", "type": "service_task", "name": "Rate",
             "handler": "customers.set_risk_rating",
             "params": {"customer_id_path": "find.customer_id", "rating": "high"},
             "next": "done"},
            {"id": "done", "type": "completion", "name": "Done", "outcome": "rated"},
        ],
    }  # fmt: skip
    authoring.import_definition(db, doc, staff.admin.id)
    customer = db.get(Customer, account.customer_id)
    execution, _ = engine.start(db, workflow_id="WF-1904", initiator=principal(staff.employee),
                                payload={"customer_number": customer.customer_number})  # fmt: skip
    assert execution.context["rate"] == {
        "customer_id": str(customer.id), "rating": "high", "previous": "low"
    }  # fmt: skip
    db.refresh(customer)
    assert customer.risk_rating == "high"

    handlers = {h["name"]: h for h in client.get(
        "/api/v1/workflow-definitions/handlers", headers=auth(staff.employee)).json()}  # fmt: skip
    assert handlers["accounts.charge_fee"]["effect"] == "moves_money"
    assert handlers["accounts.charge_fee"]["requires_approval"] is True
    assert handlers["ai.review"]["step_type"] == "ai_task"
    body = {"definition": example("WF-1002", as_id="WF-1902")}
    report = client.post(
        "/api/v1/workflow-definitions/validate", headers=auth(staff.admin), json=body
    ).json()
    assert report["effects"]["charge_fee"] == "moves_money"
