"""Phase 6: AI tool registry, invocation contract, WF-0001 v2 AI modes and experiments."""

import uuid
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.core.errors import PermissionDeniedError
from app.core.permissions import RoleCode, permissions_for
from app.modules.accounts.models import AccountRequest, AccountType
from app.modules.accounts.service import approve_request, submit_request
from app.modules.ai_tools.adapters import kyc_assistant
from app.modules.ai_tools.adapters.kyc_assistant import (
    KycAssistantConfig,
    KycAssistantInput,
    analyze,
)
from app.modules.ai_tools.models import AITool, AIToolInvocation
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import invoke, register_tool
from app.modules.customers.models import RiskRating
from app.modules.identity.models import User
from app.modules.identity.service import AuthenticatedUser
from app.modules.workflows import engine
from app.modules.workflows.wf0001 import POLICY_ENGINE_USERNAME, synthetic_document_number
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationCaseResult
from app.simulation.router import get_simulation_sessionmaker
from tests.factories import (
    application,
    auth,
    make_customer,
    make_org_tree,
    make_staff,
    make_user,
    principal,
)

KYC = DEMO_AI_TOOLS[0]
TODAY = date(2026, 1, 5)


def _kyc_tool(db: Session, **changes) -> AITool:
    spec = {**KYC, **changes}
    return register_tool(db, ToolCreate.model_validate(spec), actor_id=None)


def _payload(**app_changes) -> dict:
    app = application(name="Ada Lovelace")
    app.update(app_changes)
    return {"application": app, "screening": {"sanctions_hit": False}, "as_of": "2026-01-05"}


# --- The KYC assistant's rules ----------------------------------------------------------------


def _analyze(**changes):
    result, _ = analyze(KycAssistantInput.model_validate(_payload(**changes)), KycAssistantConfig())
    return result


def test_clean_application_is_recommended_for_approval() -> None:
    result = _analyze()
    assert (result.recommendation, result.risk_classification) == ("approve", "low")
    assert result.findings == [] and result.missing_fields == []
    assert "Recommend approve" in result.explanation


def test_assistant_flags_missing_inconsistent_and_risky_applications() -> None:
    clean = application(name="Ada Lovelace")
    identity, address = clean["documents"]

    forged = {**identity, "document_number": identity["document_number"][:-1] + "0"}
    if forged["document_number"] == identity["document_number"]:
        forged["document_number"] = identity["document_number"][:-1] + "1"
    result = _analyze(documents=[forged, address])
    assert result.recommendation == "reject"
    assert "passport.document_number" in result.inconsistencies

    typo = _analyze(documents=[identity, {**address, "name_on_document": "Ada Lovelacee"}])
    assert typo.recommendation == "approve"
    assert [f.code for f in typo.findings] == ["name_minor_variation"]

    other = _analyze(documents=[identity, {**address, "name_on_document": "Grace Hopper"}])
    assert other.recommendation == "escalate"

    missing = _analyze(documents=[identity])
    assert missing.missing_fields == ["proof_of_address"]
    assert missing.recommendation == "escalate"

    assert _analyze(politically_exposed=True).recommendation == "escalate"
    assert _analyze(date_of_birth="2010-01-01").recommendation == "reject"
    sanctioned = KycAssistantInput.model_validate(
        {**_payload(), "screening": {"sanctions_hit": True}}
    )
    assert analyze(sanctioned, KycAssistantConfig())[0].recommendation == "reject"


# --- Registry ---------------------------------------------------------------------------------


def test_researcher_registers_a_tool_with_validated_contracts(
    client: TestClient, db: Session
) -> None:
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    response = client.post("/api/v1/ai-tools", json=KYC, headers=headers)
    assert response.status_code == 201, response.text
    tool = response.json()
    assert tool["tool_id"] == "agb-intelligent-kyc-assistant"
    assert tool["status"] == "active"
    assert tool["input_schema"]["type"] == "object"  # defaulted from the adapter
    assert tool["configuration"]["timeout_seconds"] == 5.0
    assert db.execute(
        select(AuditEvent).where(AuditEvent.action == "ai_tool.registered")
    ).scalar_one()

    again = client.post("/api/v1/ai-tools", json=KYC, headers=headers)
    assert again.status_code == 409  # versions are immutable
    listing = client.get("/api/v1/ai-tools", params={"workflow_id": "WF-0001"}, headers=headers)
    assert listing.json()["total"] == 1


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"allowed_actions": ["approve_account"]}, "cannot be granted"),
        ({"allowed_actions": ["open_account", "recommend_decision"]}, "cannot be granted"),
        ({"allowed_actions": ["teleport"]}, "Unknown actions"),
        ({"adapter": "gpt-anything"}, "Unknown adapter"),
        ({"input_schema": {"type": "banana"}}, "not a valid JSON Schema"),
        ({"output_schema": {"type": "array"}}, "must describe a JSON object"),
        ({"configuration": {"timeout_seconds": -1}}, "configuration is invalid"),
        ({"compatible_workflows": ["WF-9999"]}, "Unknown workflows"),
        ({"permissions": ["root:everything"]}, "Unknown permissions"),
        ({"tool_version": "one"}, ""),
    ],
)
def test_invalid_registrations_are_rejected(
    client: TestClient, db: Session, changes: dict, message: str
) -> None:
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    response = client.post("/api/v1/ai-tools", json={**KYC, **changes}, headers=headers)
    assert response.status_code == 422, response.text
    assert message in response.text


def test_only_permitted_roles_manage_and_invoke_tools(client: TestClient, db: Session) -> None:
    tool = _kyc_tool(db)
    for role in (RoleCode.BANKING_EMPLOYEE, RoleCode.AUDITOR, RoleCode.COMPLIANCE_OFFICER):
        headers = auth(make_user(db, role))
        assert client.get("/api/v1/ai-tools", headers=headers).status_code == 200
        assert client.post("/api/v1/ai-tools", json=KYC, headers=headers).status_code == 403
        invoked = client.post(
            f"/api/v1/ai-tools/{tool.id}/invoke",
            json={"action": "analyze_application", "input": _payload()},
            headers=headers,
        )
        assert invoked.status_code == 403
        assert "ai_tools:invoke" in invoked.text


# --- Invocation -------------------------------------------------------------------------------


def test_invocation_returns_and_stores_a_structured_result(client: TestClient, db: Session) -> None:
    tool = _kyc_tool(db)
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    response = client.post(
        f"/api/v1/ai-tools/{tool.id}/invoke",
        json={"action": "recommend_decision", "input": _payload()},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    call = response.json()
    assert call["status"] == "succeeded"
    assert call["output"]["recommendation"] == "approve"
    assert call["usage"]["rules_evaluated"] > 0
    stored = db.get(AIToolInvocation, uuid.UUID(call["id"]))
    assert stored.output == call["output"] and stored.tool_version == "1.0.0"


def test_requests_that_break_the_input_schema_are_recorded_not_executed(
    client: TestClient, db: Session
) -> None:
    tool = _kyc_tool(db)
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    call = client.post(
        f"/api/v1/ai-tools/{tool.id}/invoke",
        json={"action": "analyze_application", "input": {"application": {"name": "x"}}},
        headers=headers,
    ).json()
    assert call["status"] == "invalid_input"
    assert call["output"] is None
    assert call["error"]["errors"]


def test_unauthorized_actions_are_blocked_and_recorded(client: TestClient, db: Session) -> None:
    tool = _kyc_tool(db, allowed_actions=["analyze_application"])
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    response = client.post(
        f"/api/v1/ai-tools/{tool.id}/invoke",
        json={"action": "complete_low_risk_review", "input": _payload()},
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["error"]["details"]["code"] == "action_not_allowed"
    # The refusal itself is kept (committed before the error response).
    blocked = db.execute(
        select(AIToolInvocation).where(AIToolInvocation.tool_record_id == tool.id)
    ).scalar_one()
    assert blocked.status == "blocked"

    disabled = client.patch(
        f"/api/v1/ai-tools/{tool.id}", json={"status": "disabled"}, headers=headers
    )
    assert disabled.json()["status"] == "disabled"
    again = client.post(
        f"/api/v1/ai-tools/{tool.id}/invoke",
        json={"action": "analyze_application", "input": _payload()},
        headers=headers,
    )
    assert again.status_code == 403
    assert again.json()["error"]["details"]["code"] == "tool_disabled"


def test_tool_permissions_apply_to_the_caller(client: TestClient, db: Session) -> None:
    tool = _kyc_tool(db, tool_version="1.0.1", permissions=["ledger:read"])
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))  # no ledger:read
    response = client.post(
        f"/api/v1/ai-tools/{tool.id}/invoke",
        json={"action": "analyze_application", "input": _payload()},
        headers=headers,
    )
    assert response.status_code == 403
    assert "ledger:read" in response.text


@pytest.mark.parametrize(
    ("configuration", "status", "code"),
    [
        (
            {"failure_rate": 1, "timeout_rate": 0, "invalid_output_rate": 0},
            "failed",
            "injected_failure",
        ),
        (
            {
                "failure_rate": 0,
                "timeout_rate": 1,
                "invalid_output_rate": 0,
                "timeout_seconds": 0.05,
            },
            "timeout",
            "timeout",
        ),
        (
            {"failure_rate": 0, "timeout_rate": 0, "invalid_output_rate": 1},
            "invalid_output",
            "invalid_output",
        ),
    ],
)
def test_tool_failures_are_captured(
    db: Session, configuration: dict, status: str, code: str
) -> None:
    tool = _kyc_tool(
        db,
        tool_id="kyc-fault-injector",
        adapter="fault_injection",
        allowed_actions=["analyze_application"],
        configuration=configuration,
    )
    call = invoke(db, tool, "analyze_application", _payload(), actor_id=None)
    assert (call.status, call.error["code"]) == (status, code)


def test_unexpected_adapter_errors_are_captured(db: Session, monkeypatch) -> None:
    tool = _kyc_tool(db)

    def explode(*_args, **_kwargs):
        raise RuntimeError("model server unreachable")

    monkeypatch.setattr(kyc_assistant, "analyze", explode)
    call = invoke(db, tool, "analyze_application", _payload(), actor_id=None)
    assert call.status == "failed"
    assert call.error == {
        "code": "adapter_error",
        "message": "RuntimeError: model server unreachable",
    }


# --- WF-0001 v2: AI modes and the policy engine ------------------------------------------------


def _start(db: Session, teller, mode: str, tool: AITool | None, **app_changes):
    payload = application(name="Ada Lovelace")
    payload.update(app_changes)
    execution, _ = engine.start(
        db,
        workflow_id="WF-0001",
        version=2,
        payload=payload,
        initiator=principal(teller),
        settings={"ai_mode": mode, "ai_tool_id": str(tool.id) if tool else None},
    )
    db.flush()
    return execution


def test_assisted_mode_adds_advice_but_keeps_human_approval(db: Session) -> None:
    staff = make_staff(db)
    tool = _kyc_tool(db)
    execution = _start(db, staff.employee, "assisted", tool)

    assert execution.status == "waiting"
    assert execution.current_steps == ["account_approval"]  # a person still decides
    review = execution.context["ai_kyc_review"]
    assert (review["recommendation"], review["available"]) == ("approve", True)
    assert review["automation_requested"] is False
    call = db.get(AIToolInvocation, uuid.UUID(review["invocation_id"]))
    assert call.execution_id == execution.id and call.action == "recommend_decision"


def test_automated_mode_approves_only_through_the_policy_engine(db: Session) -> None:
    staff = make_staff(db)
    tool = _kyc_tool(db)
    execution = _start(db, staff.employee, "automated", tool)

    assert (execution.status, execution.outcome) == ("completed", "approved")
    policy = execution.context["policy_approval"]
    assert policy["approved"] is True and policy["failed_checks"] == []
    engine_user = db.execute(
        select(User).where(User.username == POLICY_ENGINE_USERNAME)
    ).scalar_one()
    request = db.execute(
        select(AccountRequest).where(
            AccountRequest.customer_id
            == uuid.UUID(execution.context["register_customer"]["customer_id"])
        )
    ).scalar_one()
    # The account was approved by the policy engine principal, not by the tool.
    assert request.decided_by == engine_user.id
    assert request.requested_by == staff.employee.id


@pytest.mark.parametrize(
    ("changes", "expected_step"),
    [
        ({"politically_exposed": True}, "compliance_review"),  # never reaches the policy
        ({"expected_monthly_deposits": 30_000}, "account_approval"),  # a policy check fails
    ],
)
def test_automated_mode_keeps_people_in_the_loop_when_policy_requires(
    db: Session, changes: dict, expected_step: str
) -> None:
    staff = make_staff(db)
    tool = _kyc_tool(db)
    execution = _start(db, staff.employee, "automated", tool, **changes)
    assert execution.status == "waiting"
    assert execution.current_steps == [expected_step]


def test_tool_without_the_review_action_is_blocked_and_escalates(db: Session) -> None:
    staff = make_staff(db)
    tool = _kyc_tool(db, allowed_actions=["analyze_application", "recommend_decision"])
    execution = _start(db, staff.employee, "automated", tool)

    review = execution.context["ai_kyc_review"]
    assert review["available"] is False
    assert review["invocation_status"] == "blocked"
    assert execution.current_steps == ["account_approval"]


def test_failing_tool_escalates_safely(db: Session) -> None:
    staff = make_staff(db)
    tool = _kyc_tool(
        db,
        tool_id="kyc-fault-injector",
        adapter="fault_injection",
        configuration={"failure_rate": 1},
    )
    execution = _start(db, staff.employee, "automated", tool)
    assert execution.context["ai_kyc_review"]["error"]["code"] == "injected_failure"
    assert execution.current_steps == ["account_approval"]


def test_policy_engine_cannot_approve_beyond_low_risk(db: Session) -> None:
    staff = make_staff(db)
    engine_user = db.execute(
        select(User).where(User.username == POLICY_ENGINE_USERNAME)
    ).scalar_one()
    policy = AuthenticatedUser(
        id=engine_user.id,
        username=engine_user.username,
        role=RoleCode.AUTOMATED_POLICY.value,
        permissions=permissions_for(RoleCode.AUTOMATED_POLICY.value),
    )
    for risk in (RiskRating.MEDIUM, RiskRating.HIGH):
        customer = make_customer(db, risk=risk)
        request = submit_request(
            db,
            customer_id=customer.id,
            account_type=AccountType.CURRENT,
            currency=None,
            requested_by=staff.employee.id,
        )
        with pytest.raises(PermissionDeniedError):
            approve_request(db, request.id, policy, "automation")


def test_service_roles_cannot_be_given_to_people(client: TestClient, db: Session) -> None:
    headers = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))
    response = client.post(
        "/api/v1/users",
        json={
            "username": "robot-friend",
            "email": "robot@atlasbank.example",
            "display_name": "Robot",
            "password": "a-long-enough-password",
            "role": "automated_policy",
        },
        headers=headers,
    )
    assert response.status_code == 422
    assert "system principals only" in response.text


def test_policy_engine_cannot_sign_in(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"username": POLICY_ENGINE_USERNAME, "password": "!unusable"}
    )
    assert response.status_code == 401


# --- Experiments: A, B and C on the same applications -------------------------------------------


@pytest.fixture
def sim_client(app: FastAPI, db_connection: Connection):
    def factory() -> Session:
        return Session(
            bind=db_connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
            expire_on_commit=False,
        )

    app.dependency_overrides[get_simulation_sessionmaker] = lambda: factory
    with TestClient(app) as client:
        yield client


def _suite(client: TestClient, headers: dict, **changes) -> list[dict]:
    body = {
        "scenario_version": 2,
        "profile": "custom",
        "applications": 30,
        "employees": 6,
        "seed": 31,
        "tool_id": "agb-intelligent-kyc-assistant",
        **changes,
    }
    response = client.post("/api/v1/simulations/suites", json=body, headers=headers)
    assert response.status_code == 202, response.text
    return [
        client.get(f"/api/v1/simulations/{r['id']}", headers=headers).json()
        for r in response.json()
    ]


def test_experiment_suite_runs_three_modes_on_identical_workloads(
    sim_client: TestClient, db: Session
) -> None:
    make_org_tree(db)
    _kyc_tool(db)
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    baseline, assisted, automated = _suite(sim_client, headers)

    assert [r["mode"] for r in (baseline, assisted, automated)] == [
        "baseline",
        "ai_assisted",
        "ai_automated",
    ]
    assert all(r["status"] == "completed" for r in (baseline, assisted, automated))
    assert len({r["batch_id"] for r in (baseline, assisted, automated)}) == 1
    assert baseline["tool_id"] is None and assisted["tool_id"] == "agb-intelligent-kyc-assistant"

    def cases(run):
        rows = db.execute(
            select(SimulationCaseResult.kind, SimulationCaseResult.expected_outcome)
            .where(SimulationCaseResult.run_id == uuid.UUID(run["id"]))
            .order_by(SimulationCaseResult.case_index)
        ).all()
        return [tuple(r) for r in rows]

    # Same seed: the same applications with the same ground truth in every mode.
    assert cases(baseline) == cases(assisted) == cases(automated)

    base, helped, auto = (r["results"] for r in (baseline, assisted, automated))
    assert base["ai"]["invocations"] == 0
    assert helped["ai"]["invocations"] > 0 and helped["ai"]["automated_approvals"] == 0
    # Assisted: the same reviews, less reviewer time (the scenario's stated assumption).
    assert helped["manual_reviews"] == base["manual_reviews"]
    assert helped["review_labor_hours"] < base["review_labor_hours"]
    # Automated: the policy engine took low-risk approvals, so fewer people were needed.
    assert auto["ai"]["automated_approvals"] > 0
    assert auto["manual_reviews"] < base["manual_reviews"]
    automated_cases = db.execute(
        select(SimulationCaseResult).where(
            SimulationCaseResult.run_id == uuid.UUID(automated["id"]),
            SimulationCaseResult.automated.is_(True),
        )
    ).scalars()
    for case in automated_cases:
        assert case.risk_rating == "low" and case.flags == [] and case.manual_reviews == 0
        assert "policy_approval" in case.path


def test_ai_experiments_are_reproducible(sim_client: TestClient, db: Session) -> None:
    make_org_tree(db)
    _kyc_tool(db)
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    first = _suite(sim_client, headers, modes=["ai_automated"], applications=15)[0]
    rerun = sim_client.post(f"/api/v1/simulations/{first['id']}/rerun", headers=headers)
    assert rerun.status_code == 202
    second = sim_client.get(f"/api/v1/simulations/{rerun.json()['id']}", headers=headers).json()
    assert second["mode"] == "ai_automated"
    assert second["result_digest"] == first["result_digest"]
    assert second["reproductions"][0]["matches"] is True


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"scenario_version": 1}, "has no AI modes"),
        ({"tool_id": None}, "need tool_id"),
        ({"tool_id": "no-such-tool"}, "not registered"),
    ],
)
def test_invalid_experiments_are_refused(
    client: TestClient, db: Session, changes: dict, message: str
) -> None:
    _kyc_tool(db)
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    body = {"scenario_version": 2, "tool_id": "agb-intelligent-kyc-assistant", **changes}
    response = client.post("/api/v1/simulations/suites", json=body, headers=headers)
    assert response.status_code in (404, 422), response.text
    assert message in response.text


def test_incompatible_or_disabled_tools_cannot_run_experiments(
    client: TestClient, db: Session
) -> None:
    _kyc_tool(db, compatible_workflows=[])
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    body = {"scenario_version": 2, "tool_id": "agb-intelligent-kyc-assistant"}
    response = client.post(
        "/api/v1/simulations", json={**body, "mode": "ai_assisted"}, headers=headers
    )
    assert response.status_code == 422 and "not declared compatible" in response.text


def test_queued_suite_members_are_not_reaped_while_the_suite_runs(db: Session) -> None:
    from datetime import UTC, datetime, timedelta

    from app.simulation import service
    from app.simulation.runner import create_run
    from app.simulation.scenarios import get_scenario

    user = make_user(db, RoleCode.AI_RESEARCHER)
    scenario = get_scenario("retail-onboarding", 2)
    batch = uuid.uuid4()
    old = datetime.now(UTC) - timedelta(minutes=30)
    running = create_run(
        db,
        scenario,
        profile="custom",
        applications=5,
        employees=3,
        seed=1,
        created_by=user.id,
        batch_id=batch,
    )
    waiting = create_run(
        db,
        scenario,
        profile="custom",
        applications=5,
        employees=3,
        seed=1,
        created_by=user.id,
        batch_id=batch,
    )
    running.status, running.heartbeat_at = "running", datetime.now(UTC)
    waiting.created_at = old
    db.flush()
    assert service.reap_stale(db) == 0
    running.heartbeat_at = old  # the process stopped
    db.flush()
    assert service.reap_stale(db) == 2
    db.refresh(waiting)
    assert waiting.status == "failed" and waiting.failure_reason.startswith("Interrupted")


def test_synthetic_document_numbers_used_in_tests_are_valid() -> None:
    assert synthetic_document_number("passport", 1234567).startswith("P1234567")


def test_ai_review_sees_documents_submitted_after_the_wait(db: Session) -> None:
    staff = make_staff(db)
    tool = _kyc_tool(db)
    payload = application(name="Ada Lovelace", documents=("passport",))
    execution, _ = engine.start(
        db,
        workflow_id="WF-0001",
        version=2,
        payload=payload,
        initiator=principal(staff.employee),
        settings={"ai_mode": "assisted", "ai_tool_id": str(tool.id)},
    )
    db.flush()
    assert execution.current_steps == ["await_documents"]
    proof = {
        "document_type": "proof_of_address",
        "document_number": synthetic_document_number("proof_of_address", 4242),
        "name_on_document": "Ada Lovelace",
    }
    engine.signal(
        db, execution.id, "documents_submitted", {"documents": [proof]}, staff.employee.id
    )
    db.flush()

    review = execution.context["ai_kyc_review"]
    call = db.get(AIToolInvocation, uuid.UUID(review["invocation_id"]))
    assert [d["document_type"] for d in call.input["application"]["documents"]] == [
        "passport",
        "proof_of_address",
    ]
    assert call.output["missing_fields"] == []
    assert review["recommendation"] == "approve"


def test_oversized_inputs_are_refused_before_any_analysis(db: Session) -> None:
    tool = _kyc_tool(db)
    huge = _payload(applicant_name="A" * 10_000)
    call = invoke(db, tool, "analyze_application", huge, actor_id=None)
    assert call.status == "invalid_input"
