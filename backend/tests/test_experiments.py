"""Phase 7: evaluation engine, cost model, criteria, experiments API, reports, benchmarks."""

import copy
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select, text
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.experiments.assumptions import (
    CostAssumptions,
    EvaluationConfig,
    SuccessThresholds,
)
from app.modules.experiments.evaluation import costs, evaluate
from app.modules.experiments.measurements import measure
from app.modules.experiments.models import ExperimentMeasurement
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationRun
from app.simulation.router import get_simulation_sessionmaker
from tests.factories import auth, make_org_tree, make_user

# --- Raw measurements built by hand, so every derived number can be checked -----------------

WORKLOAD = {
    "scenario_id": "retail-onboarding",
    "scenario_version": 2,
    "workflow_id": "WF-0001",
    "workflow_version": 2,
    "seed": 7,
    "applications": 100,
    "employees": 20,
    "dataset": {"countries": ["GB"], "watchlist": "synthetic-watchlist-v1"},
    "scenario_config": {},
    "software_version": "0.7.0",
}


def measurement(**changes) -> dict:
    m = {
        "mode": "baseline",
        "result_digest": "x",
        "workload": dict(WORKLOAD),
        "case_fingerprint": "same-cases",
        "cases": 100,
        "completed": 100,
        "should_approve": 90,
        "should_reject": 10,
        "approved": 88,
        "rejected": 12,
        "correct": 96,
        "false_approvals": 1,
        "false_rejections": 3,
        "manual_reviews": 90,
        "review_seconds": 60 * 60 * 18,  # 18 hours
        "queue_wait_seconds": 0,
        "escalations": 10,
        "automated_approvals": 0,
        "overdue_tasks": 0,
        "document_timeouts": 2,
        "failed_executions": 0,
        "exceptions": 2,
        "cycle_seconds": {
            "sum": 360000,
            "avg": 3600.0,
            "p50": 1800.0,
            "p95": 18000.0,
            "max": 259200,
        },
        "ai": {
            "invocations": 0,
            "executed_invocations": 0,
            "by_status": {},
            "errors": 0,
            "blocked": 0,
        },
        "decisions_checked": 88,
        "policy_violations": 0,
        "policy_violation_details": [],
    }
    for key, value in changes.items():
        if key == "ai":
            m["ai"] = {**m["ai"], **value}
        else:
            m[key] = value
    return m


def candidate(**changes) -> dict:
    defaults = {
        "mode": "ai_automated",
        "manual_reviews": 20,
        "review_seconds": 60 * 60 * 4,  # 4 hours
        "automated_approvals": 70,
        "correct": 98,
        "false_approvals": 0,
        "false_rejections": 2,
        "ai": {"invocations": 98, "executed_invocations": 98, "by_status": {"succeeded": 98}},
        "cycle_seconds": {"sum": 300000, "avg": 3000.0, "p50": 0.0, "p95": 18000.0, "max": 259200},
    }
    return measurement(**{**defaults, **changes})


def by_metric(result: dict) -> dict:
    return {row["metric"]: row for row in result["comparisons"]}


def by_criterion(result: dict) -> dict:
    return {row["criterion"]: row for row in result["criteria"]}


def test_cost_lines_use_recorded_inputs_and_stated_assumptions() -> None:
    a = CostAssumptions()
    base = costs(measurement(), a)
    # 18 h of review at 0.85/min; 20 + 100 × 0.02 infrastructure; 2 exceptions × 12;
    # 10 escalations × 6; no AI and no automation.
    assert base["lines"] == {
        "review_labour": 918.0,
        "automation_oversight": 0.0,
        "ai_execution": 0.0,
        "infrastructure": 22.0,
        "exception_handling": 24.0,
        "manual_escalation": 60.0,
    }
    assert base["operating_total"] == 1024.0
    assert base["cost_per_completed_case"] == 10.24
    assert base["risk_exposure"] == {"false_approvals": 750.0, "false_rejections": 180.0}

    cand = costs(candidate(), a)
    # Oversight: 70 automated × 10 % sampled × 6 minutes × 0.85; AI: 98 calls × 0.04.
    assert cand["lines"]["automation_oversight"] == 35.7
    assert cand["lines"]["ai_execution"] == 3.92
    assert cand["inputs"]["oversight_minutes"] == 42.0


def test_metrics_compare_baseline_and_candidate() -> None:
    result = evaluate(measurement(), candidate(), EvaluationConfig())
    m = by_metric(result)
    assert len(m) == 14
    assert m["manual_reviews"]["baseline"] == 90 and m["manual_reviews"]["candidate"] == 20
    assert m["labour_hours"]["candidate"] == pytest.approx(4 + 42 / 60)  # review + oversight
    assert m["false_approval_rate"]["baseline"] == pytest.approx(0.1)  # 1 of 10 should-reject
    assert m["false_rejection_rate"]["candidate"] == pytest.approx(2 / 90, abs=1e-6)
    assert m["escalation_rate"]["baseline"] == pytest.approx(0.1)
    assert m["ai_execution_cost"]["regression"] is False  # informational
    assert m["labour_hours"]["improved"] and not m["labour_hours"]["regression"]
    assert result["verdict"] == "successful"
    assert all(c["passed"] for c in result["criteria"])
    assert "not verified savings" in result["conclusion"]


def test_quality_regressions_are_detected_and_fail_the_experiment() -> None:
    worse = candidate(false_approvals=3, correct=93)  # 30 % of should-reject cases approved
    result = evaluate(measurement(), worse, EvaluationConfig())
    m = by_metric(result)
    assert m["false_approval_rate"]["regression"] is True
    assert m["accuracy"]["regression"] is True
    checks = by_criterion(result)
    assert checks["compliance_thresholds"]["passed"] is False
    assert checks["correctness_acceptable"]["passed"] is False
    assert result["verdict"] == "not_successful"
    assert "False approval rate" in result["conclusion"]


def test_errors_from_a_zero_baseline_are_regressions() -> None:
    noisy = candidate(ai={"errors": 9, "by_status": {"succeeded": 89, "failed": 9}})
    result = evaluate(measurement(), noisy, EvaluationConfig())
    assert by_metric(result)["error_count"]["regression"] is True
    assert by_criterion(result)["compliance_thresholds"]["passed"] is False  # 9 % > 5 %


def test_improvement_must_reach_the_threshold() -> None:
    marginal = candidate(
        review_seconds=60 * 60 * 18 - 60,
        automated_approvals=0,
        manual_reviews=89,
        cycle_seconds=measurement()["cycle_seconds"],
    )
    result = evaluate(measurement(), marginal, EvaluationConfig())
    assert by_criterion(result)["measurable_improvement"]["passed"] is False
    looser = EvaluationConfig(thresholds=SuccessThresholds(min_improvement=0.0))
    assert by_criterion(evaluate(measurement(), marginal, looser))["measurable_improvement"][
        "passed"
    ]


def test_costs_must_include_ai_operation_and_oversight() -> None:
    free_ai = EvaluationConfig(costs=CostAssumptions(ai_cost_per_invocation=0))
    check = by_criterion(evaluate(measurement(), candidate(), free_ai))["costs_complete"]
    assert check["passed"] is False and "AI execution" in check["detail"]
    no_oversight = EvaluationConfig(costs=CostAssumptions(oversight_sample_rate=0))
    check = by_criterion(evaluate(measurement(), candidate(), no_oversight))["costs_complete"]
    assert check["passed"] is False and "oversight" in check["detail"]


def test_authorization_violations_fail_the_experiment() -> None:
    breached = candidate(policy_violations=1)
    check = by_criterion(evaluate(measurement(), breached, EvaluationConfig()))[
        "authorization_controls"
    ]
    assert check["passed"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"workload": {**WORKLOAD, "seed": 8}},
        {"workload": {**WORKLOAD, "software_version": "0.6.0"}},
        {"case_fingerprint": "other-cases"},
    ],
)
def test_non_equivalent_workloads_fail_the_comparison(change: dict) -> None:
    result = evaluate(measurement(), candidate(**change), EvaluationConfig())
    assert by_criterion(result)["equivalent_workloads"]["passed"] is False
    assert result["verdict"] == "not_successful"


def test_evaluation_is_deterministic() -> None:
    first = evaluate(measurement(), candidate(), EvaluationConfig())
    again = evaluate(copy.deepcopy(measurement()), copy.deepcopy(candidate()), EvaluationConfig())
    assert first["evaluation_digest"] == again["evaluation_digest"]
    dearer = EvaluationConfig(costs=CostAssumptions(reviewer_cost_per_minute=1.2))
    assert (
        evaluate(measurement(), candidate(), dearer)["evaluation_digest"]
        != first["evaluation_digest"]
    )


# --- Experiments through the API ----------------------------------------------------------------


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


@pytest.fixture
def lab(db: Session) -> dict:
    make_org_tree(db)
    register_tool(db, ToolCreate.model_validate(DEMO_AI_TOOLS[0]), actor_id=None)
    return auth(make_user(db, RoleCode.AI_RESEARCHER))


def _experiment(client: TestClient, headers: dict, **changes) -> dict:
    body = {
        "name": "KYC assistant, automated",
        "tool_id": "agb-intelligent-kyc-assistant",
        "candidate_mode": "ai_automated",
        "profile": "custom",
        "applications": 25,
        "employees": 6,
        "seed": 17,
        **changes,
    }
    response = client.post("/api/v1/experiments", json=body, headers=headers)
    assert response.status_code == 202, response.text
    return client.get(f"/api/v1/experiments/{response.json()['id']}", headers=headers).json()


def test_experiment_runs_both_modes_and_evaluates(api: TestClient, db: Session, lab: dict) -> None:
    experiment = _experiment(api, lab)

    assert experiment["status"] == "completed", experiment["failure_reason"]
    assert experiment["baseline"]["mode"] == "baseline"
    assert experiment["candidate"]["mode"] == "ai_automated"
    assert experiment["tool_version"] == "1.0.0"
    # Raw measurements and derived results are stored separately.
    roles = {m["role"]: m for m in experiment["measurements"]}
    assert set(roles) == {"baseline", "candidate"}
    assert roles["baseline"]["metrics"]["cases"] == 25
    assert roles["candidate"]["metrics"]["automated_approvals"] > 0
    stored = db.execute(
        select(ExperimentMeasurement).where(
            ExperimentMeasurement.experiment_id == uuid.UUID(experiment["id"])
        )
    ).scalars()
    assert len(list(stored)) == 2
    evaluation = experiment["evaluation"]
    assert {c["criterion"] for c in evaluation["criteria"]} == {
        "equivalent_workloads",
        "measurable_improvement",
        "correctness_acceptable",
        "compliance_thresholds",
        "authorization_controls",
        "costs_complete",
    }
    assert by_criterion(evaluation)["equivalent_workloads"]["passed"] is True
    assert by_criterion(evaluation)["authorization_controls"]["passed"] is True
    assert experiment["configuration"]["costs"]["reviewer_cost_per_minute"] == 0.85
    # Financial figures come from the recorded inputs.
    base = roles["baseline"]["metrics"]
    assert evaluation["costs"]["baseline"]["inputs"]["review_minutes"] == round(
        base["review_seconds"] / 60, 2
    )

    again = api.post(f"/api/v1/experiments/{experiment['id']}/re-evaluate", headers=lab).json()
    assert again["matches"] is True


def test_identical_experiments_reproduce(api: TestClient, lab: dict) -> None:
    first = _experiment(api, lab, applications=15)
    second = _experiment(api, lab, applications=15)
    assert first["evaluation"]["evaluation_digest"] == second["evaluation"]["evaluation_digest"]
    digests = lambda e: sorted(m["measurement_digest"] for m in e["measurements"])  # noqa: E731
    assert digests(first) == digests(second)


def test_runs_can_be_re_evaluated_under_other_assumptions(api: TestClient, lab: dict) -> None:
    original = _experiment(api, lab, applications=15)
    body = {
        "name": "Same runs, dearer AI",
        "baseline_run_id": original["baseline"]["id"],
        "candidate_run_id": original["candidate"]["id"],
        "costs": {"ai_cost_per_invocation": 2.5},
    }
    response = api.post("/api/v1/experiments/from-runs", json=body, headers=lab)
    assert response.status_code == 201, response.text
    repriced = response.json()
    raw = lambda e: sorted(m["measurement_digest"] for m in e["measurements"])  # noqa: E731
    assert raw(repriced) == raw(original)  # same raw measurements …
    ai_cost = lambda e: e["evaluation"]["costs"]["candidate"]["lines"]["ai_execution"]  # noqa: E731
    assert ai_cost(repriced) == pytest.approx(ai_cost(original) / 0.04 * 2.5)  # … other costs


def test_non_equivalent_or_wrong_runs_are_refused(api: TestClient, lab: dict) -> None:
    a = _experiment(api, lab, applications=10, seed=1)
    b = _experiment(api, lab, applications=10, seed=2)
    mixed = {
        "name": "Different seeds",
        "baseline_run_id": a["baseline"]["id"],
        "candidate_run_id": b["candidate"]["id"],
    }
    response = api.post("/api/v1/experiments/from-runs", json=mixed, headers=lab)
    assert response.status_code == 422
    assert "seed" in response.json()["error"]["details"]["differences"]
    swapped = {
        **mixed,
        "baseline_run_id": a["candidate"]["id"],
        "candidate_run_id": a["baseline"]["id"],
    }
    response = api.post("/api/v1/experiments/from-runs", json=swapped, headers=lab)
    assert response.status_code == 422 and "not a baseline" in response.text


def test_policy_violations_are_detected_from_recorded_decisions(
    api: TestClient, db: Session, lab: dict
) -> None:
    experiment = _experiment(api, lab, applications=15)
    candidate_run = db.get(SimulationRun, uuid.UUID(experiment["candidate"]["id"]))
    assert measure(db, candidate_run)["policy_violations"] == 0
    # Tamper with one recorded decision: someone without approval authority decided it.
    # (A self-approval cannot even be stored: the database enforces four-eyes itself.)
    db.execute(
        text(
            "UPDATE account_requests SET decided_by = :outsider WHERE id = ("
            " SELECT (context->'open_account'->>'account_request_id')::uuid"
            " FROM workflow_executions WHERE simulation_run_id = :run"
            " AND context ? 'open_account' LIMIT 1)"
        ),
        {"run": candidate_run.id, "outsider": candidate_run.created_by},
    )
    found = measure(db, candidate_run)
    assert found["policy_violations"] >= 1
    assert "decider_without_authority" in {v["rule"] for v in found["policy_violation_details"]}


def test_failed_runs_fail_the_experiment(api: TestClient, db: Session) -> None:
    # No organization structure: the simulation cannot hire staff.
    register_tool(db, ToolCreate.model_validate(DEMO_AI_TOOLS[0]), actor_id=None)
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))
    experiment = _experiment(api, headers, applications=5)
    assert experiment["status"] == "failed"
    assert "Retail Banking" in experiment["failure_reason"]
    assert experiment["evaluation"] is None
    report = api.get(f"/api/v1/experiments/{experiment['id']}/report", headers=headers)
    assert report.status_code == 409


def test_report_documents_the_proof_of_concept(api: TestClient, lab: dict) -> None:
    experiment = _experiment(api, lab, applications=15)
    response = api.get(f"/api/v1/experiments/{experiment['id']}/report", headers=lab)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "attachment" in response.headers["content-disposition"]
    report = response.text
    for section in (
        "## Tested tool",
        "## Test scenario and workload",
        "Data seed: `17`",
        "Software version: `0.7.0`",
        "## Baseline and AI performance",
        "## Operational differences",
        "## Financial assumptions",
        "## Security and compliance results",
        "## Known limitations",
        "## Recommendation",
        "is a verified saving",
    ):
        assert section in report, section
    data = api.get(
        f"/api/v1/experiments/{experiment['id']}/report", params={"format": "json"}, headers=lab
    )
    assert (
        data.json()["evaluation"]["evaluation_digest"]
        == experiment["evaluation"]["evaluation_digest"]
    )


def test_benchmarks_summarise_completed_experiments(api: TestClient, lab: dict) -> None:
    _experiment(api, lab, applications=12)
    _experiment(api, lab, applications=12, candidate_mode="ai_assisted")
    rows = api.get("/api/v1/benchmarks", headers=lab).json()
    assert {(r["tool_id"], r["candidate_mode"]) for r in rows} == {
        ("agb-intelligent-kyc-assistant", "ai_assisted"),
        ("agb-intelligent-kyc-assistant", "ai_automated"),
    }
    automated = next(r for r in rows if r["candidate_mode"] == "ai_automated")
    assert automated["experiments"] == 1
    assert automated["median_relative_change"]["labour_hours"] < 0


def test_only_permitted_roles_run_experiments(client: TestClient, db: Session) -> None:
    for role in (RoleCode.BANKING_EMPLOYEE, RoleCode.AUDITOR):
        headers = auth(make_user(db, role))
        assert client.get("/api/v1/experiments", headers=headers).status_code == 200
        assert client.get("/api/v1/benchmarks", headers=headers).status_code == 200
        response = client.post("/api/v1/experiments", json={}, headers=headers)
        assert response.status_code == 403 and "experiments:run" in response.text
