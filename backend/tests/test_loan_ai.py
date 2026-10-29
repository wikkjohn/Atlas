"""Phase 11: the AI underwriting assistant, WF-0003 v2 and the personal-loans v2 scenario."""

import uuid
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.errors import PermissionDeniedError
from app.core.permissions import RoleCode
from app.modules.ai_tools.adapters.credit_underwriting import (
    CreditUnderwritingConfig,
    CreditUnderwritingInput,
    analyze,
)
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.identity.models import User
from app.modules.lending import service as lending
from app.modules.lending.models import Loan
from app.modules.workflows import engine
from app.modules.workflows.principals import POLICY_ENGINE_USERNAME
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationCaseResult, SimulationRun
from app.simulation.router import get_simulation_sessionmaker
from app.simulation.scenarios import get_scenario
from app.simulation.workloads import WORKLOADS
from tests.factories import (
    auth,
    funded_account,
    loan_application,
    make_org_tree,
    make_staff,
    make_user,
    principal,
    unique_surname,
)

BORN = date(1979, 4, 2)
START = "/api/v1/workflows/WF-0003/executions"


def _review(**overrides) -> dict:
    data = {
        "application": {
            "amount": 1_000_000,
            "currency": "USD",
            "term_months": 36,
            "purpose": "vehicle",
            "employment_status": "employed",
            "monthly_income": 500_000,
            "monthly_debt_payments": 20_000,
        },
        "bureau": {"score": 780, "recent_defaults": 0, "open_credit_lines": 2},
        "affordability": {"debt_to_income": 0.1, "committee_required": False},
        "income": {"estimated_monthly_income": 500_000, "declared_to_estimate": 1.0},
        "as_of": "2026-10-29",
    }
    for path, value in overrides.items():
        section, key = path.split("__")
        data[section][key] = value
    result, _ = analyze(CreditUnderwritingInput.model_validate(data), CreditUnderwritingConfig())
    return result.model_dump()


def test_the_assistant_flags_inflated_income_and_explains_itself() -> None:
    clean = _review()
    assert (clean["recommendation"], clean["risk_classification"]) == ("approve", "low")
    inflated = _review(income__declared_to_estimate=2.0)
    assert (inflated["recommendation"], inflated["risk_classification"]) == ("reject", "high")
    assert "2.0× the bureau's estimate" in inflated["explanation"]
    # A self-employed applicant a little above the estimate: approve, but not low risk.
    self_employed = _review(
        application__employment_status="self_employed", income__declared_to_estimate=1.2
    )
    assert (self_employed["recommendation"], self_employed["risk_classification"]) == (
        "approve",
        "medium",
    )
    # Its blind spot: an honest self-employed applicant well above the estimate.
    assert (
        _review(application__employment_status="self_employed", income__declared_to_estimate=1.5)[
            "recommendation"
        ]
        == "reject"
    )
    stretched = _review(bureau__score=650, affordability__debt_to_income=0.4)
    assert stretched["recommendation"] == "escalate"
    unverifiable = _review(income__declared_to_estimate=None)
    assert unverifiable["risk_classification"] == "medium"


# --- WF-0003 v2 ---------------------------------------------------------------------------------


def _applicant(db: Session, staff, *, score: tuple[int, int] = (760, 850), ratio: float = 1.0):
    """A borrower with a bureau score in `score` whose declared income is `ratio` × the
    bureau's estimate (USD)."""
    for _ in range(20_000):
        name = f"Ines {unique_surname()}"
        if score[0] <= lending.bureau_report(name, BORN)["score"] <= score[1]:
            break
    account = funded_account(db, staff, name=name, born=BORN)
    income = round(lending.income_estimate(name, BORN) * ratio) * 100
    return account, income


def _application(account, amount: int, income: int, **overrides) -> dict:
    return loan_application(
        account.customer,
        account,
        amount,
        monthly_income=income,
        monthly_debt_payments=0,
        term_months=60,
        **overrides,
    )


def _register_assistant(db: Session):
    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-credit-underwriting-assistant")
    return register_tool(db, ToolCreate.model_validate(spec), actor_id=None)


def test_version_2_checks_income_and_still_goes_to_an_underwriter(
    client: TestClient, db: Session
) -> None:
    staff = make_staff(db)
    account, income = _applicant(db, staff, ratio=2.0)

    response = client.post(
        START,
        json={"input": _application(account, 1_000_000, income)},
        headers=auth(staff.employee),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["workflow_version"] == 2  # live applications run the latest version
    assert body["context"]["verify_income"]["declared_to_estimate"] == 2.0
    assert body["context"]["ai_underwriting_review"] == {"mode": "off"}
    assert body["current_steps"] == ["underwriting_review"]


def test_automated_mode_underwrites_small_clean_loans_only(db: Session) -> None:
    staff = make_staff(db)
    tool = _register_assistant(db)
    settings = {"ai_mode": "automated", "ai_tool_id": str(tool.id)}

    def apply(amount: int, ratio: float, **overrides) -> dict:
        account, income = _applicant(db, staff, ratio=ratio)
        execution, _ = engine.start(
            db,
            workflow_id="WF-0003",
            payload=_application(account, amount, income, **overrides),
            initiator=principal(staff.employee),
            settings=settings,
        )
        return execution.context | {"_status": execution.status, "_outcome": execution.outcome}

    clean = apply(1_000_000, 1.0)
    assert clean["ai_underwriting_review"]["recommendation"] == "approve"
    assert clean["policy_underwrite"]["approved"] is True
    assert clean["_outcome"] == "approved"
    loan = db.get(Loan, uuid.UUID(clean["disburse_loan"]["loan_id"]))
    engine_user = db.execute(
        select(User).where(User.username == POLICY_ENGINE_USERNAME)
    ).scalar_one()
    assert loan.underwritten_by == engine_user.id

    inflated = apply(1_000_000, 2.0)
    assert inflated["ai_underwriting_review"]["recommendation"] == "reject"
    assert "policy_underwrite" not in inflated and inflated["_status"] == "waiting"

    # Clean but above the automation limit: the policy refuses, a person underwrites.
    larger = apply(2_000_000, 1.0)
    assert larger["ai_underwriting_review"]["automation_requested"] is True
    assert larger["policy_underwrite"]["failed_checks"] == ["within_automation_limit"]
    assert larger["_status"] == "waiting"

    # Self-employed income is never underwritten without a person.
    self_employed = apply(1_000_000, 1.0, employment_status="self_employed")
    assert self_employed["_status"] == "waiting"


def test_the_lending_service_limits_what_the_policy_engine_may_underwrite(db: Session) -> None:
    staff = make_staff(db)
    engine_user = principal(
        db.execute(select(User).where(User.username == POLICY_ENGINE_USERNAME)).scalar_one()
    )

    def originate(amount: int):
        account, _ = _applicant(db, staff)
        return lending.originate(
            db,
            customer_id=account.customer_id,
            account_id=account.id,
            principal=amount,
            annual_rate_bps=690,
            term_months=36,
            purpose="other",
            requested_by=staff.employee.id,
            underwriter=engine_user,
            committee=None,
        )

    with pytest.raises(PermissionDeniedError) as refused:
        originate(1_500_001)  # one cent above the automation limit
    assert refused.value.details == {"rule": "underwriter_without_authority"}
    assert originate(1_500_000).underwritten_by == engine_user.id


# --- personal-loans v2 through the simulation and experiment engines --------------------------


@pytest.fixture
def factory(db_connection: Connection):
    def make() -> Session:
        return Session(
            bind=db_connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
            expire_on_commit=False,
        )

    return make


@pytest.fixture
def api(app: FastAPI, factory) -> TestClient:
    app.dependency_overrides[get_simulation_sessionmaker] = lambda: factory
    with TestClient(app) as client:
        yield client


def test_personal_loans_v2_matches_its_workload() -> None:
    scenario = get_scenario("personal-loans")
    assert (scenario.version, scenario.workflow_version) == (2, 2)
    assert scenario.config.ai_assistance is not None
    workload = WORKLOADS[scenario.workload]
    workload.validate(scenario)
    assert workload.ai_step == "ai_underwriting_review"
    assert get_scenario("personal-loans", 1).workload == "personal_loans"  # unchanged


def test_underwriting_assistant_experiment_catches_inflated_incomes(
    api: TestClient, db: Session
) -> None:
    make_org_tree(db)
    _register_assistant(db)
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))

    response = api.post(
        "/api/v1/experiments",
        json={
            "name": "Underwriting assistant, automated",
            "scenario_id": "personal-loans",
            "tool_id": "agb-credit-underwriting-assistant",
            "candidate_mode": "ai_automated",
            "profile": "custom",
            "applications": 80,
            "employees": 10,
            "seed": 11,
        },
        headers=headers,
    )
    assert response.status_code == 202, response.text
    experiment = api.get(f"/api/v1/experiments/{response.json()['id']}", headers=headers).json()

    assert experiment["status"] == "completed", experiment["failure_reason"]
    candidate = db.get(SimulationRun, uuid.UUID(experiment["candidate"]["id"]))
    cases = list(
        db.execute(
            select(SimulationCaseResult).where(SimulationCaseResult.run_id == candidate.id)
        ).scalars()
    )
    inflated = [c for c in cases if c.kind == "inflated_income"]
    automated = [c for c in cases if c.automated]
    assert inflated and automated, "seed 11 should produce both"
    # The assistant rejects every inflated income, so the policy never underwrites one; the
    # policy engine only ever underwrites loans that should be approved.
    assert all(c.ai_recommendation == "reject" and not c.automated for c in inflated)
    assert all(c.expected_outcome == "approved" for c in automated)
    assert not any(c.kind in ("large_loan", "self_employed") for c in automated)
    evaluation = experiment["evaluation"]
    metrics = {m["metric"]: m for m in evaluation["comparisons"]}
    assert metrics["false_approval_rate"]["candidate"] <= metrics["false_approval_rate"]["baseline"]
    assert metrics["policy_violation_rate"]["candidate"] == 0
    assert metrics["manual_reviews"]["candidate"] < metrics["manual_reviews"]["baseline"]
    assert evaluation["verdict"] == "successful"
