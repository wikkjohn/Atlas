"""Phase 54: the payment-plans workload and the collections review AI tool."""

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.accounts.service import deposit
from app.modules.ai_tools.adapters.plan_review import (
    PlanProfile,
    PlanReviewConfig,
    PlanReviewInput,
    analyze,
)
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.collections import service as collections
from app.modules.lending import servicing
from app.modules.workflows import authoring
from app.modules.workflows.examples import HERE
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import get_scenario
from app.simulation.workloads import WORKLOADS
from tests.factories import make_loan, make_org_tree, make_staff, make_user, principal

SCENARIO = get_scenario("payment-plans")
ON = date(2040, 3, 25)  # the loan from 2040-01-10 has two instalments missed


def _advice(**profile) -> tuple[str, list[str]]:
    values = {"credits_90d": 3, "days_since_last_credit": 15, "commitment_to_income_pct": 25}
    result, _ = analyze(
        PlanReviewInput(profile=PlanProfile(**{**values, **profile})), PlanReviewConfig()
    )
    return result.recommendation, [f.code for f in result.findings]


def test_the_plan_rules_and_their_blind_spot() -> None:
    assert _advice() == ("approve", ["affordable"])
    assert _advice(commitment_to_income_pct=55) == ("escalate", ["stretched"])
    assert _advice(commitment_to_income_pct=120) == ("reject", ["unaffordable"])
    assert _advice(credits_90d=0, commitment_to_income_pct=999) == ("reject", ["no_income"])
    assert _advice(days_since_last_credit=75) == ("reject", ["no_recent_income"])
    # The blind spot: the borrower's earlier, broken plans are never read.
    assert _advice(prior_plans=2, prior_plans_broken=2) == ("approve", ["affordable"])


def test_the_plan_profile(db: Session) -> None:
    staff = make_staff(db)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    loan = make_loan(db, staff)
    servicing.run(db, ON, principal(staff.manager))
    # An earlier plan, broken: both payments find the account empty.
    earlier = collections.propose_plan(db, loan, 7, staff.manager.id, today=ON)
    collections.decide_plan(db, earlier, executive.id, approve=True)
    collections.collect_plan(db, earlier, ON + timedelta(days=14), principal(staff.manager))
    assert earlier.status == "broken"
    # Salary paid in 70 and 20 days before, and once more outside the 90 days.
    for n, days in enumerate((70, 20, 120)):
        deposit(db, loan.disbursement_account_id, amount=200_000, memo="Salary",
                idempotency_key=f"pp-{loan.id}-{n}", actor_id=staff.employee.id,
                effective_date=ON + timedelta(days=14) - timedelta(days=days))  # fmt: skip
    plan = collections.propose_plan(db, loan, 14, staff.manager.id,
                                    today=ON + timedelta(days=14))  # fmt: skip
    profile = collections.plan_profile(db, plan)
    assert profile["overdue_instalments"] == plan.payments == 2
    assert profile["credits_90d"] == 2 and profile["inflow_90d"] == 400_000
    assert profile["days_since_last_credit"] == 20
    commitment = loan.monthly_payment + plan.arrears_amount // 2 * 30 // 14
    assert profile["monthly_commitment"] == commitment
    assert profile["commitment_to_income_pct"] == commitment * 100 // (400_000 // 3)
    assert profile["prior_plans"] == 1 and profile["prior_plans_broken"] == 1


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
    """The org tree, WF-1040 v1, the tool (compatible with WF-1040), then WF-1040 v2."""
    make_org_tree(db)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    authoring.import_definition(db, json.loads((HERE / "WF-1040.json").read_text()), admin.id)
    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-collections-assistant")
    register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    authoring.import_definition(db, json.loads((HERE / "WF-1040-v2.json").read_text()), admin.id)


def _run(db: Session, factory, mode: str, seed: int = 11) -> SimulationRun:
    from app.modules.ai_tools.service import find_tool

    creator = make_user(db, RoleCode.AI_RESEARCHER)
    tool = find_tool(db, "agb-collections-assistant") if mode != "baseline" else None
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


def test_plan_runs_with_and_without_the_assistant(db: Session, factory) -> None:
    _setup(db)
    db.commit()
    baseline = _run(db, factory, "baseline")
    assisted = _run(db, factory, "ai_assisted")
    for run in (baseline, assisted):
        assert run.status == SimulationStatus.COMPLETED, run.failure_reason
        assert run.results["completed"] == 40
        controls = WORKLOADS["payment_plans"].check_controls(db, run.id)
        # Every plan goes to a manager other than whoever proposed it.
        assert controls.decisions == 40 and controls.violations == []
    assert baseline.results["ai"]["invocations"] == 0
    ai = assisted.results["ai"]
    assert ai["invocations"] == 40 and ai["failed_invocations"] == 0
    expected = {"affordable": "approve", "short_arrears": "approve", "stretched": "escalate",
                "no_income": "reject", "unaffordable": "reject",
                "broken_before": "approve"}  # fmt: skip
    seen = set()
    for case in _cases(db, assisted):
        assert case.ai_recommendation == expected[case.kind], case.kind
        seen.add(case.kind)
    assert {"broken_before", "affordable", "no_income"} <= seen
    assert ai["recommendation_accuracy"] < 1
    activated = _cases(db, assisted, outcome="approved")
    assert activated and all("activate" in c.path for c in activated)
    rejected = _cases(db, assisted, outcome="rejected")
    assert rejected and all("reject" in c.path for c in rejected)
