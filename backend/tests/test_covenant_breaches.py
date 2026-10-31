"""Phase 36: the covenant-breaches workload and the covenant breach AI tool."""

import json
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.accounts.models import AccountType
from app.modules.ai_tools.adapters.covenant_review import (
    BreachProfile,
    CovenantReviewConfig,
    CovenantReviewInput,
    analyze,
)
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.commercial import service as commercial
from app.modules.customers.models import CustomerType
from app.modules.workflows import authoring
from app.modules.workflows.examples import HERE
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import get_scenario
from app.simulation.workloads import WORKLOADS
from tests.factories import make_customer, make_org_tree, make_staff, make_user, open_account

SCENARIO = get_scenario("covenant-breaches")


def _advice(**profile) -> tuple[str, list[str]]:
    values = {
        "currency": "USD", "dscr_centi": 118, "dscr_threshold_centi": 125,
        "leverage_centi": 260, "leverage_threshold_centi": 350, "ebitda_change_bps": -2000,
        "previous_ebitda_change_bps": 300, "consecutive_declines": 1, "utilisation_bps": 4000,
        "periods_tested": 3,
    }  # fmt: skip
    result, _ = analyze(
        CovenantReviewInput(profile=BreachProfile(**{**values, **profile})),
        CovenantReviewConfig(),
    )
    return result.recommendation, [f.code for f in result.findings]


def test_the_covenant_rules_and_their_blind_spot() -> None:
    assert _advice() == ("approve", ["marginal"])  # a near miss after a good year
    assert _advice(dscr_centi=111) == ("approve", [])
    assert _advice(dscr_centi=95)[0] == "reject"  # cannot cover its debt service
    assert _advice(dscr_centi=150, leverage_centi=520) == ("reject", ["leverage_far_over"])
    two_falls = {"consecutive_declines": 2, "previous_ebitda_change_bps": -2200}
    assert _advice(**two_falls)[0] == "reject"
    # Thin cover on a facility drawn to its limit: escalate.
    assert _advice(dscr_centi=104, utilisation_bps=9500) == (
        "escalate",
        ["thin_cover", "fully_drawn"],
    )
    # The blind spot: earlier breaches and waivers are in the profile and never read.
    assert _advice(previous_breaches=1, previous_waivers=1) == ("approve", ["marginal"])


def test_the_breach_profile_reads_the_history(db: Session) -> None:
    staff = make_staff(db)
    business = make_customer(db, customer_type=CustomerType.BUSINESS, name="Kestrel Print Ltd")
    account = open_account(db, staff, business, AccountType.BUSINESS_CURRENT)
    facility = commercial.propose_facility(
        db, customer=business, account=account, facility_type="revolving",
        credit_limit=20_000_000, term_months=36, purpose="Working capital",
        requested_by=staff.employee.id,
    )  # fmt: skip
    now = datetime(2026, 4, 1, tzinfo=UTC)
    commercial.approve_facility(db, facility, staff.manager.id, now=now)
    commercial.draw(db, facility, 15_000_000, None, now=now)
    years = [(date(2023, 12, 31), 30_000_000), (date(2024, 12, 31), 23_000_000),
             (date(2025, 12, 31), 22_000_000)]  # fmt: skip
    tests = []
    for period, ebitda in years:
        tests.append(commercial.run_covenant_test(
            db, facility, period_end=period, ebitda=ebitda, debt_service=20_000_000,
            total_debt=50_000_000, actor_id=staff.employee.id,
        ))  # fmt: skip
        if tests[-1].breached:
            commercial.waive_breach(db, tests[-1], staff.admin.id, now=now)
    profile = commercial.breach_profile(db, tests[-1])
    assert profile["dscr_centi"] == 110 and profile["dscr_threshold_centi"] == 125
    assert profile["leverage_centi"] == 227
    assert profile["ebitda_change_bps"] == -434 and profile["previous_ebitda_change_bps"] == -2333
    assert profile["consecutive_declines"] == 2 and profile["periods_tested"] == 3
    assert profile["utilisation_bps"] == 7500
    # The 2024 figures (DSCR 1.15×) were a breach the committee waived.
    assert tests[1].breached and tests[1].waived_by is not None
    assert profile["previous_breaches"] == 1 and profile["previous_waivers"] == 1


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
    """The org tree, WF-1013 v1, the tool (compatible with WF-1013), then WF-1013 v2."""
    make_org_tree(db)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    authoring.import_definition(db, json.loads((HERE / "WF-1013.json").read_text()), admin.id)
    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-covenant-breach-assistant")
    register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    authoring.import_definition(db, json.loads((HERE / "WF-1013-v2.json").read_text()), admin.id)


def _run(db: Session, factory, mode: str, seed: int = 11) -> SimulationRun:
    from app.modules.ai_tools.service import find_tool

    creator = make_user(db, RoleCode.AI_RESEARCHER)
    tool = find_tool(db, "agb-covenant-breach-assistant") if mode != "baseline" else None
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


def test_covenant_runs_with_and_without_the_assistant(db: Session, factory) -> None:
    _setup(db)
    db.commit()
    baseline = _run(db, factory, "baseline")
    assisted = _run(db, factory, "ai_assisted")
    for run in (baseline, assisted):
        assert run.status == SimulationStatus.COMPLETED, run.failure_reason
        assert run.results["completed"] == 40
        controls = WORKLOADS["covenant_breaches"].check_controls(db, run.id)
        # Every case breaches, so the committee decides each one.
        assert controls.decisions == 40 and controls.violations == []
    assert baseline.results["ai"]["invocations"] == 0
    ai = assisted.results["ai"]
    assert ai["invocations"] == 40 and ai["failed_invocations"] == 0
    expected = {"one_off_dip": "approve", "seasonal_borderline": "approve",
                "structural_decline": "reject", "over_leveraged": "reject",
                "repeat_breach": "approve", "stretched_facility": "escalate"}  # fmt: skip
    seen = set()
    for case in _cases(db, assisted):
        assert case.ai_recommendation == expected[case.kind], case.kind
        seen.add(case.kind)
    assert {"repeat_breach", "structural_decline", "one_off_dip"} <= seen
    assert ai["recommendation_accuracy"] < 1
    waived = _cases(db, assisted, outcome="approved")
    assert waived and all("waive" in c.path for c in waived)
    kept = _cases(db, assisted, outcome="rejected")
    assert kept and all("waive" not in c.path for c in kept)
