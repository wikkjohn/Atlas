"""Phase 30: the retail-overdrafts workload and the overdraft affordability AI tool."""

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.ai_tools.adapters.overdraft_affordability import (
    AccountProfile,
    OverdraftAffordabilityConfig,
    OverdraftAffordabilityInput,
    analyze,
)
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.ledger import service as ledger
from app.modules.ledger.models import Direction
from app.modules.retail import service as retail
from app.modules.workflows import authoring
from app.modules.workflows.examples import HERE
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.runner import SimulationSetupError, create_run, execute_run
from app.simulation.scenarios import get_scenario
from app.simulation.workloads import WORKLOADS
from tests.factories import funded_account, make_org_tree, make_staff, make_user

SCENARIO = get_scenario("retail-overdrafts")


def _profile(**overrides) -> AccountProfile:
    values = {
        "currency": "USD",
        "balance": 150_000,
        "overdraft_limit": 0,
        "max_overdraft": 250_000,
        "monthly_credits": 400_000,
        "months_with_credits": 3,
        "days_overdrawn": 0,
    }
    return AccountProfile(**{**values, **overrides})


def _advice(limit: int, **profile) -> tuple[str, list[str]]:
    result, _ = analyze(
        OverdraftAffordabilityInput(limit=limit, profile=_profile(**profile)),
        OverdraftAffordabilityConfig(),
    )
    return result.recommendation, [f.code for f in result.findings]


def test_the_affordability_rules_and_their_blind_spot() -> None:
    assert _advice(80_000) == ("approve", [])
    assert _advice(240_000) == ("approve", ["moderate_size"])  # 60 % of a month
    assert _advice(600_000, monthly_credits=300_000)[0] == "reject"  # 2× a month's income
    assert _advice(300_000, max_overdraft=250_000)[0] == "reject"  # above the maximum
    assert _advice(100_000, monthly_credits=0) == ("reject", ["no_income"])
    # Irregular income alone is a concern, not a refusal; with another it escalates.
    assert _advice(80_000, months_with_credits=2) == ("approve", ["irregular_income"])
    assert _advice(80_000, months_with_credits=2, days_overdrawn=40)[0] == "escalate"
    # The blind spot: a customer overdrawn most days with regular income still passes.
    assert _advice(150_000, days_overdrawn=80) == ("approve", ["often_overdrawn"])


def test_the_account_profile_reads_ninety_days_of_history(db: Session) -> None:
    staff = make_staff(db)
    account = funded_account(db, staff)
    cash = ledger.cash_account(db, "USD")
    today = date(2026, 4, 7)
    for n, (amount, days) in enumerate([(300_000, 88), (-350_000, 87), (300_000, 28)]):
        inbound = amount > 0
        ledger.post_entry(
            db,
            idempotency_key=f"profile-{n}",
            currency="USD",
            description="Test",
            source="test",
            lines=[
                ledger.LineSpec(
                    cash.id, Direction.DEBIT if inbound else Direction.CREDIT, abs(amount)
                ),
                ledger.LineSpec(
                    account.ledger_account_id,
                    Direction.CREDIT if inbound else Direction.DEBIT,
                    abs(amount),
                ),
            ],
            actor_id=None,
            effective_date=today - timedelta(days=days),
        )  # fmt: skip
    profile = retail.account_profile(db, account, today)
    assert profile["monthly_credits"] == 200_000  # 600,000 in over three months
    assert profile["months_with_credits"] == 2  # nothing in the middle window
    assert profile["days_overdrawn"] == 59  # from 87 days before until the next salary
    assert profile["max_overdraft"] == 250_000 and profile["currency"] == "USD"


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
    """The org tree, WF-1003 v1, the tool (compatible with WF-1003), then WF-1003 v2."""
    make_org_tree(db)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    authoring.import_definition(db, json.loads((HERE / "WF-1003.json").read_text()), admin.id)
    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-overdraft-affordability-assistant")
    register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    authoring.import_definition(db, json.loads((HERE / "WF-1003-v2.json").read_text()), admin.id)


def _run(db: Session, factory, mode: str, seed: int = 11) -> SimulationRun:
    from app.modules.ai_tools.service import find_tool

    creator = make_user(db, RoleCode.AI_RESEARCHER)
    tool = find_tool(db, "agb-overdraft-affordability-assistant") if mode != "baseline" else None
    run = create_run(
        db, SCENARIO, profile="custom", applications=40, employees=6, seed=seed,
        created_by=creator.id, mode=mode, tool=tool,
    )  # fmt: skip
    db.commit()
    execute_run(factory, run.id)
    db.expire_all()
    return db.get(SimulationRun, run.id)


def test_overdraft_runs_with_and_without_the_assistant(db: Session, factory) -> None:
    _setup(db)
    db.commit()
    baseline = _run(db, factory, "baseline")
    assisted = _run(db, factory, "ai_assisted")
    for run in (baseline, assisted):
        assert run.status == SimulationStatus.COMPLETED, run.failure_reason
        assert run.results["completed"] == 40
        controls = WORKLOADS["retail_overdrafts"].check_controls(db, run.id)
        assert controls.decisions > 0 and controls.violations == []
    assert baseline.results["ai"]["invocations"] == 0
    ai = assisted.results["ai"]
    assert ai["invocations"] == 40 and ai["failed_invocations"] == 0
    # The assistant's blind spot: it recommends approving customers who live in overdraft.
    habitual = (
        db.execute(
            select(SimulationCaseResult).where(
                SimulationCaseResult.run_id == assisted.id,
                SimulationCaseResult.kind == "habitual_overdraft",
            )
        )
        .scalars()
        .all()
    )
    assert habitual and all(c.ai_recommendation == "approve" for c in habitual)
    assert ai["recommendation_accuracy"] < 1
    # Approved requests set the limit; nothing above the product's maximum was set.
    approved = (
        db.execute(
            select(SimulationCaseResult).where(
                SimulationCaseResult.run_id == assisted.id,
                SimulationCaseResult.outcome == "approved",
            )
        )
        .scalars()
        .all()
    )
    assert approved and all("set_limit" in c.path for c in approved)


def test_the_automated_mode_is_refused_without_a_policy_path(db: Session) -> None:
    _setup(db)
    from app.modules.ai_tools.service import find_tool

    creator = make_user(db, RoleCode.AI_RESEARCHER)
    with pytest.raises(SimulationSetupError, match="no automated decision path"):
        create_run(
            db, SCENARIO, profile="custom", applications=5, employees=4, seed=1,
            created_by=creator.id, mode="ai_automated",
            tool=find_tool(db, "agb-overdraft-affordability-assistant"),
        )  # fmt: skip
