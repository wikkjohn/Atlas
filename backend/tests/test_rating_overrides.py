"""Phase 48: the rating-overrides workload and the rating review AI tool."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.accounts.service import deposit, withdraw
from app.modules.ai_tools.adapters.rating_review import (
    RatingProfile,
    RatingReviewConfig,
    RatingReviewInput,
    analyze,
)
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.customers.models import Customer
from app.modules.retail import service as retail
from app.modules.risk import service as risk
from app.modules.workflows import authoring
from app.modules.workflows.examples import HERE
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import get_scenario
from app.simulation.workloads import WORKLOADS
from tests.factories import funded_account, make_org_tree, make_staff, make_user

SCENARIO = get_scenario("rating-overrides")


def _advice(**profile) -> tuple[str, list[str]]:
    values = {"suggested_grade": 6, "proposed_grade": 5, "notches": -1, "direction": "upgrade",
              "exposure_to_annual_inflow_pct": 12}  # fmt: skip
    result, _ = analyze(
        RatingReviewInput(profile=RatingProfile(**{**values, **profile})), RatingReviewConfig()
    )
    return result.recommendation, [f.code for f in result.findings]


def test_the_rating_rules_and_their_blind_spot() -> None:
    assert _advice() == ("approve", ["strong_capacity"])
    assert _advice(overdraft_use_pct=90) == ("reject", ["strained_upgrade"])
    assert _advice(exposure_to_annual_inflow_pct=200)[0] == "reject"
    assert _advice(exposure_to_annual_inflow_pct=60) == ("escalate", ["thin_support"])
    assert _advice(proposed_grade=3, notches=-3) == (
        "reject",
        ["large_departure", "strong_capacity"],
    )
    down = {"suggested_grade": 4, "direction": "downgrade"}
    assert _advice(**down, proposed_grade=6, notches=2, overdraft_use_pct=95) == (
        "approve", ["overdraft_stress"]
    )  # fmt: skip
    assert _advice(**down, proposed_grade=6, notches=2, exposure_to_annual_inflow_pct=180)[0] == (
        "approve"
    )  # fmt: skip
    assert _advice(**down, proposed_grade=5, notches=1) == ("escalate", ["no_stress_seen"])
    assert _advice(**down, proposed_grade=10, notches=6)[0] == "reject"
    assert _advice(**down, proposed_grade=10, notches=6, worst_days_past_due=120)[0] == "reject"
    # The blind spot: earlier departures, refused, are never read.
    assert _advice(prior_overrides_365d=3, prior_overrides_rejected_365d=3) == (
        "approve", ["strong_capacity"]
    )  # fmt: skip


def test_the_rating_profile(db: Session) -> None:
    staff = make_staff(db)
    account = funded_account(db, staff, balance=0)
    customer = db.get(Customer, account.customer_id)
    today = datetime.now(UTC).date()
    for n, days_ago in enumerate((70, 40, 10)):
        deposit(db, account.id, amount=100_000, memo="Salary", actor_id=staff.employee.id,
                idempotency_key=f"rp-{account.id}-{n}",
                effective_date=today - timedelta(days=days_ago))  # fmt: skip
    deposit(
        db,
        account.id,
        amount=500_000,
        memo="Old",
        actor_id=staff.employee.id,
        idempotency_key=f"rp-{account.id}-old",
        effective_date=today - timedelta(days=120),
    )
    limit = retail.max_overdraft(retail.get_product(db, account.account_type), account.currency)
    retail.set_overdraft(db, account, limit, staff.manager.id)
    withdraw(db, account.id, amount=800_000 + limit * 8 // 10, memo="Spent",
             actor_id=staff.employee.id, idempotency_key=f"rp-{account.id}-out")  # fmt: skip
    earlier = risk.rate(db, customer, 2, staff.employee.id, "Asked for before",
                        today=today - timedelta(days=100))  # fmt: skip
    risk.decide_rating(db, earlier, staff.manager.id, approve=False)
    rating = risk.rate(db, customer, 6, staff.employee.id, "Overdraft drawn", today=today)
    profile = risk.rating_profile(db, rating, today)
    assert profile["suggested_grade"] == 4 and profile["notches"] == 2
    assert profile["direction"] == "downgrade" and profile["overdraft_use_pct"] == 80
    assert profile["exposure_usd"] == profile["overdraft_usd"] > 0
    # Only the 90 days' deposits: three of 1,000.00, a month's average of 1,000.00.
    assert profile["monthly_inflow_usd"] == 1_000
    assert profile["prior_overrides_365d"] == 1 and profile["prior_overrides_rejected_365d"] == 1
    assert (
        profile["limit_at_model_usd"] == 10_000_000
        and profile["limit_at_proposed_usd"] == 2_000_000
    )


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
    """The org tree, WF-1030 v1, the tool (compatible with WF-1030), then WF-1030 v2."""
    make_org_tree(db)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    authoring.import_definition(db, json.loads((HERE / "WF-1030.json").read_text()), admin.id)
    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-rating-assistant")
    register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    authoring.import_definition(db, json.loads((HERE / "WF-1030-v2.json").read_text()), admin.id)


def _run(db: Session, factory, mode: str, seed: int = 11) -> SimulationRun:
    from app.modules.ai_tools.service import find_tool

    creator = make_user(db, RoleCode.AI_RESEARCHER)
    tool = find_tool(db, "agb-rating-assistant") if mode != "baseline" else None
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


def test_rating_runs_with_and_without_the_assistant(db: Session, factory) -> None:
    _setup(db)
    db.commit()
    baseline = _run(db, factory, "baseline")
    assisted = _run(db, factory, "ai_assisted")
    for run in (baseline, assisted):
        assert run.status == SimulationStatus.COMPLETED, run.failure_reason
        assert run.results["completed"] == 40
        controls = WORKLOADS["rating_overrides"].check_controls(db, run.id)
        # Every departing grade goes to an approver.
        assert controls.decisions == 40 and controls.violations == []
    assert baseline.results["ai"]["invocations"] == 0
    ai = assisted.results["ai"]
    assert ai["invocations"] == 40 and ai["failed_invocations"] == 0
    expected = {"overdraft_stress_downgrade": "approve", "heavy_debt_downgrade": "approve",
                "cautious_downgrade": "escalate", "strong_inflow_upgrade": "approve",
                "upgrade_under_strain": "reject", "excessive_upgrade": "reject",
                "unfounded_default": "reject", "unsupported_downgrade": "reject",
                "rating_shopping": "approve"}  # fmt: skip
    seen = set()
    for case in _cases(db, assisted):
        assert case.ai_recommendation == expected[case.kind], case.kind
        seen.add(case.kind)
    assert {"rating_shopping", "overdraft_stress_downgrade", "upgrade_under_strain"} <= seen
    assert ai["recommendation_accuracy"] < 1
    approved = _cases(db, assisted, outcome="approved")
    assert approved and all("approve" in c.path for c in approved)
    rejected = _cases(db, assisted, outcome="rejected")
    assert rejected and all("reject" in c.path for c in rejected)
