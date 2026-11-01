"""Phase 46: the alert-triage workload and the alert review AI tool."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.accounts.models import AccountType
from app.modules.accounts.service import deposit
from app.modules.ai_tools.adapters.alert_review import (
    AlertProfile,
    AlertReviewConfig,
    AlertReviewInput,
    analyze,
)
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.compliance import service as compliance
from app.modules.workflows import authoring
from app.modules.workflows.examples import HERE
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import get_scenario
from app.simulation.workloads import WORKLOADS
from tests.factories import make_customer, make_org_tree, make_staff, make_user, open_account

SCENARIO = get_scenario("alert-triage")


def _advice(**profile) -> tuple[str, list[str]]:
    values = {"rule": "large_cash", "customer_type": "business", "deposits": 4,
              "activity_vs_baseline_pct": 105, "amount_x_threshold_pct": 600}  # fmt: skip
    result, _ = analyze(
        AlertReviewInput(profile=AlertProfile(**{**values, **profile})), AlertReviewConfig()
    )
    return result.recommendation, [f.code for f in result.findings]


def test_the_alert_rules_and_their_blind_spot() -> None:
    assert _advice() == ("approve", ["consistent_takings"])
    assert _advice(activity_vs_baseline_pct=320) == ("escalate", ["business_spike", "large_amount"])
    assert _advice(rule="structuring", customer_type="individual")[0] == "reject"
    assert _advice(rule="rapid_movement", activity_vs_baseline_pct=900)[0] == "reject"
    assert _advice(rule="rapid_movement", activity_vs_baseline_pct=100) == (
        "approve", ["usual_pattern"]
    )  # fmt: skip
    assert _advice(rule="high_risk_turnover", activity_vs_baseline_pct=500)[0] == "reject"
    assert _advice(customer_type="individual", deposits=1) == ("approve", ["one_off"])
    assert _advice(prior_reports_filed=1)[0] == "reject"
    # The blind spot: earlier alerts that led to no report are never read.
    assert _advice(prior_alerts_365d=3) == ("approve", ["consistent_takings"])


def test_the_alert_profile(db: Session) -> None:
    staff = make_staff(db)
    account = open_account(db, staff, make_customer(db), AccountType.CURRENT)
    today = datetime.now(UTC).date()
    limit = compliance.threshold("USD")

    def cash(amount: int, days_ago: int, n: int) -> None:
        deposit(db, account.id, amount=amount, memo="Cash", actor_id=staff.employee.id,
                idempotency_key=f"profile-{account.id}-{n}",
                effective_date=today - timedelta(days=days_ago))  # fmt: skip

    for n, days_ago in enumerate((100, 70, 40)):  # a month's takings in each baseline month
        cash(2 * limit, days_ago, n)
    compliance.run_monitoring(db, window_end=today - timedelta(days=60),
                              account_ids=[account.id])  # fmt: skip
    earlier = compliance.find_open_alert(db, account.id, "large_cash")
    compliance.dismiss_alert(db, earlier, staff.manager.id, "Usual takings")
    cash(4 * limit, 10, 9)  # twice the usual month
    compliance.run_monitoring(db, window_end=today, account_ids=[account.id])
    alert = compliance.find_open_alert(db, account.id, "large_cash")
    profile = compliance.alert_profile(db, alert, today)
    assert profile["amount_x_threshold_pct"] == 400 and profile["deposits"] == 1
    assert profile["baseline_monthly_credits"] == 2 * limit
    assert profile["activity_vs_baseline_pct"] == 200
    assert profile["prior_alerts_365d"] == 1 and profile["prior_reports_filed"] == 0


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


def _setup(db: Session) -> None:
    """The org tree, WF-1027 v1, the tool (compatible with WF-1027), then WF-1027 v2."""
    make_org_tree(db)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    authoring.import_definition(db, json.loads((HERE / "WF-1027.json").read_text()), admin.id)
    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-alert-assistant")
    register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    authoring.import_definition(db, json.loads((HERE / "WF-1027-v2.json").read_text()), admin.id)


def _run(db: Session, factory, mode: str, seed: int = 11) -> SimulationRun:
    from app.modules.ai_tools.service import find_tool

    creator = make_user(db, RoleCode.AI_RESEARCHER)
    tool = find_tool(db, "agb-alert-assistant") if mode != "baseline" else None
    run = create_run(
        db, SCENARIO, profile="custom", applications=40, employees=10, seed=seed,
        created_by=creator.id, mode=mode, tool=tool,
    )  # fmt: skip
    db.commit()
    execute_run(factory, run.id)
    db.expire_all()
    return db.get(SimulationRun, run.id)


def _cases(db: Session, run: SimulationRun, **where) -> list[SimulationCaseResult]:
    query = select(SimulationCaseResult).where(SimulationCaseResult.run_id == run.id)
    for column, value in where.items():
        query = query.where(getattr(SimulationCaseResult, column) == value)
    return db.execute(query).scalars().all()


def test_alert_runs_with_and_without_the_assistant(db: Session, factory) -> None:
    _setup(db)
    db.commit()
    baseline = _run(db, factory, "baseline")
    assisted = _run(db, factory, "ai_assisted")
    for run in (baseline, assisted):
        assert run.status == SimulationStatus.COMPLETED, run.failure_reason
        assert run.results["completed"] == 40
        controls = WORKLOADS["alert_triage"].check_controls(db, run.id)
        # Every alert goes to a second officer.
        assert controls.decisions == 40 and controls.violations == []
    assert baseline.results["ai"]["invocations"] == 0
    ai = assisted.results["ai"]
    assert ai["invocations"] == 40 and ai["failed_invocations"] == 0
    expected = {"payroll_cash_business": "approve", "one_off_windfall": "approve",
                "salary_pass_through": "approve", "classic_structuring": "reject",
                "funnel_account": "reject", "high_risk_spike": "reject",
                "business_spike": "escalate", "repeat_offender": "approve"}  # fmt: skip
    seen = set()
    for case in _cases(db, assisted):
        assert case.ai_recommendation == expected[case.kind], case.kind
        seen.add(case.kind)
    assert {"repeat_offender", "payroll_cash_business", "classic_structuring"} <= seen
    assert ai["recommendation_accuracy"] < 1
    closed = _cases(db, assisted, outcome="approved")
    assert closed and all("close" in c.path for c in closed)
    escalated = _cases(db, assisted, outcome="rejected")
    assert escalated and all("escalate" in c.path for c in escalated)
