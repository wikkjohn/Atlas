"""Phase 9: payment and loan workloads through the simulation and experiment engines."""

import uuid
from collections import Counter

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, func, select, text
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.experiments.measurements import measure
from app.modules.lending.models import Loan
from app.modules.payments.models import Payment
from app.modules.workflows.models import WorkflowExecution
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.router import get_simulation_sessionmaker
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import ScenarioConfig, get_scenario
from app.simulation.workloads import PAYMENT_SHOULD_REJECT, WORKLOADS
from tests.factories import auth, make_org_tree, make_user

PAYMENTS = get_scenario("domestic-payments")
LOANS = get_scenario("personal-loans")


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


def _run(db: Session, factory, scenario, *, seed: int, cases: int = 30, **options):
    creator = make_user(db, RoleCode.AI_RESEARCHER)
    run = create_run(
        db,
        scenario,
        profile="custom",
        applications=cases,
        employees=8,
        seed=seed,
        created_by=creator.id,
        **options,
    )
    db.commit()
    execute_run(factory, run.id)
    db.expire_all()
    return db.get(SimulationRun, run.id)


def _cases(db: Session, run: SimulationRun) -> list[SimulationCaseResult]:
    return list(
        db.execute(
            select(SimulationCaseResult)
            .where(SimulationCaseResult.run_id == run.id)
            .order_by(SimulationCaseResult.case_index)
        ).scalars()
    )


def test_every_scenario_matches_its_workload() -> None:
    for scenario in (get_scenario("retail-onboarding"), PAYMENTS, LOANS):
        workload = WORKLOADS[scenario.workload]
        workload.validate(scenario)
        assert workload.workflow_id == scenario.workflow_id
    broken = PAYMENTS.model_copy(
        update={"config": ScenarioConfig(mix={"routine": 1, "teleportation": 1})}
    )
    with pytest.raises(ValueError, match="teleportation"):
        WORKLOADS["domestic_payments"].validate(broken)


def test_payment_run_moves_money_through_the_ledger(db: Session, factory) -> None:
    make_org_tree(db)
    run = _run(db, factory, PAYMENTS, seed=11)

    assert run.status == SimulationStatus.COMPLETED, run.failure_reason
    assert run.results["completed"] == 30
    cases = _cases(db, run)
    by_kind = Counter(c.kind for c in cases)
    assert set(by_kind) <= WORKLOADS["domestic_payments"].kinds
    released = db.execute(
        select(func.count())
        .select_from(Payment)
        .join(WorkflowExecution, WorkflowExecution.id == Payment.workflow_execution_id)
        .where(WorkflowExecution.simulation_run_id == run.id, Payment.status == "released")
    ).scalar_one()
    assert released == sum(c.outcome == "approved" for c in cases)
    # Payments without funds are refused by the workflow itself, never by a reviewer.
    for case in cases:
        if case.kind == "insufficient_funds":
            assert (case.outcome, case.manual_reviews) == ("rejected", 0)
        if case.kind == "routine":
            assert case.manual_reviews == 0 and "release_payment" in case.path
        if case.kind == "scam":
            assert "scam_reference" in case.flags and "fraud_review" in case.path
    assert {c.expected_outcome for c in cases if c.kind in PAYMENT_SHOULD_REJECT} <= {"rejected"}
    measured = measure(db, run)
    assert measured["decisions_checked"] == released
    assert measured["policy_violations"] == 0


def test_payment_runs_reproduce(db: Session, factory) -> None:
    make_org_tree(db)
    first = _run(db, factory, PAYMENTS, seed=5, cases=15)
    second = _run(db, factory, PAYMENTS, seed=5, cases=15)
    other = _run(db, factory, PAYMENTS, seed=6, cases=15)

    assert first.result_digest == second.result_digest
    assert first.result_digest != other.result_digest


def test_payment_control_check_detects_a_tampered_release(db: Session, factory) -> None:
    make_org_tree(db)
    run = _run(db, factory, PAYMENTS, seed=11, cases=20)
    assert measure(db, run)["policy_violations"] == 0
    # Someone without payment authority is recorded as the approver of a released payment.
    outsider = make_user(db, RoleCode.AUDITOR)
    db.execute(
        text(
            "UPDATE payments SET approved_by = :outsider WHERE id = ("
            " SELECT p.id FROM payments p JOIN workflow_executions e"
            " ON e.id = p.workflow_execution_id"
            " WHERE e.simulation_run_id = :run AND p.status = 'released' LIMIT 1)"
        ),
        {"run": run.id, "outsider": outsider.id},
    )
    found = measure(db, run)
    assert "approver_without_authority" in {v["rule"] for v in found["policy_violation_details"]}


def test_loan_run_books_loans_with_their_approvals(db: Session, factory) -> None:
    make_org_tree(db)
    run = _run(db, factory, LOANS, seed=3, cases=30)

    assert run.status == SimulationStatus.COMPLETED, run.failure_reason
    cases = _cases(db, run)
    loans = list(
        db.execute(
            select(Loan)
            .join(WorkflowExecution, WorkflowExecution.id == Loan.workflow_execution_id)
            .where(WorkflowExecution.simulation_run_id == run.id)
        ).scalars()
    )
    assert len(loans) == sum(c.outcome == "approved" for c in cases)
    for case in cases:
        if case.kind in ("poor_credit", "overextended"):
            assert (case.outcome, case.manual_reviews) == ("rejected", 0)
        if case.kind == "large_loan" and case.outcome == "approved":
            assert "credit_committee" in case.path
    for loan in loans:
        assert loan.underwritten_by != loan.requested_by
    measured = measure(db, run)
    assert measured["decisions_checked"] == len(loans)
    assert measured["policy_violations"] == 0
    assert run.results["staff"]["credit_committee_reviewers"] >= 1


@pytest.fixture
def api(app: FastAPI, factory) -> TestClient:
    app.dependency_overrides[get_simulation_sessionmaker] = lambda: factory
    with TestClient(app) as client:
        yield client


def test_payment_screener_experiment_exposes_the_quiet_scams(api: TestClient, db: Session) -> None:
    make_org_tree(db)
    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-payment-fraud-screener")
    register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))

    response = api.post(
        "/api/v1/experiments",
        json={
            "name": "Fraud screener, automated",
            "scenario_id": "domestic-payments",
            "tool_id": "agb-payment-fraud-screener",
            "candidate_mode": "ai_automated",
            "profile": "custom",
            "applications": 60,
            "employees": 8,
            "seed": 7,
        },
        headers=headers,
    )
    assert response.status_code == 202, response.text
    experiment = api.get(f"/api/v1/experiments/{response.json()['id']}", headers=headers).json()

    assert experiment["status"] == "completed", experiment["failure_reason"]
    candidate = db.get(SimulationRun, uuid.UUID(experiment["candidate"]["id"]))
    quiet = [c for c in _cases(db, candidate) if c.kind == "quiet_scam"]
    assert quiet, "seed 7 should generate quiet scams"
    # The screener cannot tell a quiet scam from a legitimate large payment, so the policy
    # engine releases them; the evaluation reports it as a correctness regression.
    assert all(c.automated and c.outcome == "approved" for c in quiet)
    evaluation = experiment["evaluation"]
    metrics = {m["metric"]: m for m in evaluation["comparisons"]}
    assert metrics["false_approval_rate"]["candidate"] > metrics["false_approval_rate"]["baseline"]
    assert evaluation["verdict"] == "not_successful"


def test_ai_modes_need_a_compatible_tool(api: TestClient, db: Session) -> None:
    make_org_tree(db)
    register_tool(db, ToolCreate.model_validate(DEMO_AI_TOOLS[0]), actor_id=None)
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    response = api.post(
        "/api/v1/simulations",
        json={
            "scenario_id": "domestic-payments",
            "mode": "ai_assisted",
            "tool_id": "agb-intelligent-kyc-assistant",
        },
        headers=headers,
    )
    assert response.status_code == 422
    assert "not declared compatible with WF-0002" in response.text
    loans = api.post(
        "/api/v1/simulations",
        json={"scenario_id": "personal-loans", "mode": "ai_assisted", "tool_id": "x"},
        headers=headers,
    )
    assert loans.status_code == 422 and "has no AI modes" in loans.text
