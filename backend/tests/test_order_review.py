"""Phase 44: the order-review workload and the suitability review AI tool."""

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.accounts.models import AccountType
from app.modules.accounts.service import deposit
from app.modules.ai_tools.adapters.suitability_review import (
    OrderProfile,
    SuitabilityReviewConfig,
    SuitabilityReviewInput,
    analyze,
)
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.wealth import service as wealth
from app.modules.workflows import authoring
from app.modules.workflows.examples import HERE
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import get_scenario
from app.simulation.workloads import WORKLOADS
from tests.factories import make_customer, make_org_tree, make_staff, make_user, open_account

SCENARIO = get_scenario("order-review")
TODAY = date(2026, 10, 15)


def _advice(**profile) -> tuple[str, list[str]]:
    values = {"reasons": ["risk_above_profile"], "risk_level": 5, "risk_profile": 4,
              "risk_gap": 1, "knowledge": "informed", "cash_after_pct": 80,
              "experienced": True}  # fmt: skip
    result, _ = analyze(
        SuitabilityReviewInput(profile=OrderProfile(**{**values, **profile})),
        SuitabilityReviewConfig(),
    )
    return result.recommendation, [f.code for f in result.findings]


def test_the_suitability_rules_and_their_blind_spot() -> None:
    assert _advice() == ("approve", ["small_risk_gap"])
    assert _advice(risk_level=6, risk_profile=2, risk_gap=4, experienced=False)[0] == "reject"
    assert _advice(risk_level=6, risk_gap=2, experienced=False) == (
        "escalate", ["risk_gap", "no_experience"]
    )  # fmt: skip
    complex_order = {"reasons": ["complex_product"], "risk_level": 6, "risk_profile": 6,
                     "risk_gap": 0, "complex": True, "knowledge": "basic"}  # fmt: skip
    assert _advice(**complex_order) == ("reject", ["complex_for_novice"])
    assert _advice(cash_after_pct=6)[0] == "reject"
    safe = {"reasons": ["concentration"], "risk_level": 2, "risk_profile": 3, "risk_gap": 0,
            "share_after_pct": 60}  # fmt: skip
    assert _advice(**safe) == ("approve", ["concentration_low_risk"])
    # The blind spot: orders that went ahead against advice, and refusals, are never read.
    assert _advice(insisted_90d=4, refused_90d=1) == ("approve", ["small_risk_gap"])


def test_the_order_profile(db: Session) -> None:
    staff = make_staff(db)
    wealth.ensure_securities(db)
    customer = make_customer(db)
    account = open_account(db, staff, customer, AccountType.CURRENT)
    deposit(db, account.id, amount=20_000_000, memo="Synthetic", actor_id=staff.employee.id,
            idempotency_key=f"order-{account.id}")  # fmt: skip
    wealth.record_profile(db, customer, objective="balanced", horizon_years=12,
                          knowledge="informed", loss_capacity="high",
                          assessed_by=staff.employee.id,
                          today=TODAY - timedelta(days=200))  # fmt: skip
    portfolio = wealth.open_portfolio(db, account, staff.employee.id)
    fund = wealth.find_security(db, "AGB-GLOBAL-EQ")  # risk 5, against a profile of 4

    def order(days_ago: int, approve: bool | None = True):
        on = TODAY - timedelta(days=days_ago)
        placed = wealth.place_order(db, portfolio=portfolio, security=fund, side="buy",
                                    units=10, placed_by=staff.employee.id, today=on)  # fmt: skip
        from datetime import UTC, datetime

        when = datetime.combine(on, datetime.min.time(), tzinfo=UTC)
        if approve is True:
            wealth.approve_order(db, placed, staff.manager.id, "Insistent", today=on, now=when)
        elif approve is False:
            wealth.reject_order(db, placed, staff.manager.id, "No", now=when)
        return placed

    order(150)  # experience, but more than 90 days ago
    order(30)
    order(20, approve=False)
    case = order(0, approve=None)
    assert case.status == "awaiting_approval"
    profile = wealth.order_profile(db, case, TODAY)
    assert profile["reasons"] == ["risk_above_profile"] and profile["risk_gap"] == 1
    assert profile["experienced"] and profile["knowledge"] == "informed"
    assert profile["insisted_90d"] == 1 and profile["refused_90d"] == 1
    assert 0 < profile["share_after_pct"] < 40 and profile["cash_after_pct"] > 50


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
    """The org tree, WF-1025 v1, the tool (compatible with WF-1025), then WF-1025 v2."""
    make_org_tree(db)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    authoring.import_definition(db, json.loads((HERE / "WF-1025.json").read_text()), admin.id)
    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-suitability-assistant")
    register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    authoring.import_definition(db, json.loads((HERE / "WF-1025-v2.json").read_text()), admin.id)


def _run(db: Session, factory, mode: str, seed: int = 11) -> SimulationRun:
    from app.modules.ai_tools.service import find_tool

    creator = make_user(db, RoleCode.AI_RESEARCHER)
    tool = find_tool(db, "agb-suitability-assistant") if mode != "baseline" else None
    run = create_run(
        db, SCENARIO, profile="custom", applications=40, employees=8, seed=seed,
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


def test_order_runs_with_and_without_the_assistant(db: Session, factory) -> None:
    _setup(db)
    db.commit()
    baseline = _run(db, factory, "baseline")
    assisted = _run(db, factory, "ai_assisted")
    for run in (baseline, assisted):
        assert run.status == SimulationStatus.COMPLETED, run.failure_reason
        assert run.results["completed"] == 40
        controls = WORKLOADS["order_review"].check_controls(db, run.id)
        # Every order goes to a manager.
        assert controls.decisions == 40 and controls.violations == []
    assert baseline.results["ai"]["invocations"] == 0
    ai = assisted.results["ai"]
    assert ai["invocations"] == 40 and ai["failed_invocations"] == 0
    expected = {"experienced_small_step": "approve", "safe_concentration": "approve",
                "large_gap": "reject", "complex_novice": "reject", "liquidity_drain": "reject",
                "serial_insister": "approve",
                "stretch_without_experience": "escalate"}  # fmt: skip
    seen = set()
    for case in _cases(db, assisted):
        assert case.ai_recommendation == expected[case.kind], case.kind
        seen.add(case.kind)
    assert {"serial_insister", "experienced_small_step", "large_gap"} <= seen
    assert ai["recommendation_accuracy"] < 1
    executed = _cases(db, assisted, outcome="approved")
    assert executed and all("approve" in c.path for c in executed)
    refused = _cases(db, assisted, outcome="rejected")
    assert refused and all("reject" in c.path for c in refused)
