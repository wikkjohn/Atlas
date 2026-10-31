"""Phase 32: the card-fraud-alerts workload and the card fraud alert AI tool."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.ai_tools.adapters.card_fraud import (
    CardFraudConfig,
    CardFraudInput,
    CardFraudProfile,
    analyze,
)
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.cards import service as cards
from app.modules.workflows import authoring
from app.modules.workflows.examples import HERE
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import get_scenario
from app.simulation.workloads import WORKLOADS
from tests.factories import funded_account, make_org_tree, make_staff, make_user

SCENARIO = get_scenario("card-fraud-alerts")
NOW = datetime(2026, 5, 12, 9, 0, tzinfo=UTC)


def _advice(blocked: dict | None = None, **profile) -> tuple[str, list[str]]:
    declined = {
        "auth_code": "AUTH-00000001", "merchant_category": "7995", "merchant_country": "FR",
        "abroad": True, "amount": 10_000, "fraud_score": 70,
        "fraud_signals": ["foreign_merchant", "high_risk_category"],
    }  # fmt: skip
    values = {
        "currency": "USD", "home_country": "US", "daily_limit": 150_000,
        "blocked": None if blocked is False else {**declined, **(blocked or {})},
        "purchases_90d": 15, "median_amount": 5_000, "high_risk_purchases_90d": 0,
        "country_first_seen_hours": 60.0, "attempts_last_hour": [],
    }  # fmt: skip
    result, _ = analyze(
        CardFraudInput(profile=CardFraudProfile(**{**values, **profile})), CardFraudConfig()
    )
    return result.recommendation, [f.code for f in result.findings]


def test_the_fraud_alert_rules_and_their_blind_spot() -> None:
    # A traveller at a casino in a country the card has been used in for days: release.
    assert _advice() == ("approve", ["first_high_risk"])
    # A large one as well: escalate.
    assert _advice({"amount": 40_000}) == ("escalate", ["first_high_risk", "unusual_amount"])
    # A country the card has never been used in, or only in the last hour: keep blocked.
    assert _advice(country_first_seen_hours=None)[0] == "reject"
    assert _advice(country_first_seen_hours=0.5)[0] == "reject"
    # A regular crypto buyer in a hurry at home.
    home = {"merchant_category": "6051", "merchant_country": "US", "abroad": False}
    assert _advice(home, high_risk_purchases_90d=8, attempts_last_hour=[8_000] * 5) == (
        "approve",
        ["burst"],
    )
    assert _advice(home, purchases_90d=2)[0] == "escalate"  # thin history and a first
    assert _advice(False) == ("escalate", ["no_fraud_decline"])  # a manual block
    # The blind spot: five tiny test purchases are left out as noise, so card testing at
    # home looks like an ordinary first high-risk purchase.
    assert _advice(home, attempts_last_hour=[100, 150, 80, 120, 90]) == (
        "approve",
        ["first_high_risk"],
    )


def test_the_fraud_profile_reads_the_declined_purchase_and_the_history(db: Session) -> None:
    staff = make_staff(db)
    account = funded_account(db, staff, balance=500_000)
    card = cards.issue_card(db, account, "debit-standard", None, now=NOW - timedelta(days=200))
    assert cards.fraud_profile(db, card)["blocked"] is None

    def buy(amount, at, category="5411", country="US"):
        return cards.authorize(db, card, merchant_name="Shop", merchant_category=category,
                               merchant_country=country, amount=amount, now=at)  # fmt: skip

    for days, amount in [(30, 2_000), (20, 4_000), (10, 6_000)]:
        buy(amount, NOW - timedelta(days=days))
    buy(3_000, NOW - timedelta(hours=72), country="FR")
    buy(500, NOW - timedelta(minutes=20))
    declined = buy(9_000, NOW, category="7995", country="FR")
    assert declined.decline_reason == "fraud_suspected"
    profile = cards.fraud_profile(db, card)
    assert profile["blocked"]["auth_code"] == declined.auth_code
    assert profile["blocked"]["abroad"] and profile["home_country"] == "US"
    assert profile["purchases_90d"] == 5 and profile["median_amount"] == 3_000
    assert profile["high_risk_purchases_90d"] == 0
    assert profile["country_first_seen_hours"] == 72.0
    assert profile["attempts_last_hour"] == [500]


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
    """The org tree, WF-1008 v1, the tool (compatible with WF-1008), then WF-1008 v2."""
    make_org_tree(db)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    authoring.import_definition(db, json.loads((HERE / "WF-1008.json").read_text()), admin.id)
    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-card-fraud-assistant")
    register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    authoring.import_definition(db, json.loads((HERE / "WF-1008-v2.json").read_text()), admin.id)


def _run(db: Session, factory, mode: str, seed: int = 11) -> SimulationRun:
    from app.modules.ai_tools.service import find_tool

    creator = make_user(db, RoleCode.AI_RESEARCHER)
    tool = find_tool(db, "agb-card-fraud-assistant") if mode != "baseline" else None
    run = create_run(
        db, SCENARIO, profile="custom", applications=40, employees=6, seed=seed,
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


def test_fraud_alert_runs_with_and_without_the_assistant(db: Session, factory) -> None:
    _setup(db)
    db.commit()
    baseline = _run(db, factory, "baseline")
    assisted = _run(db, factory, "ai_assisted")
    for run in (baseline, assisted):
        assert run.status == SimulationStatus.COMPLETED, run.failure_reason
        assert run.results["completed"] == 40
        controls = WORKLOADS["card_fraud_alerts"].check_controls(db, run.id)
        assert controls.decisions == 40 and controls.violations == []
    assert baseline.results["ai"]["invocations"] == 0
    ai = assisted.results["ai"]
    assert ai["invocations"] == 40 and ai["failed_invocations"] == 0
    # Every kind's advice is as designed; card testing is the blind spot.
    expected = {"traveller": "approve", "big_spender_abroad": "escalate",
                "crypto_investor": "approve", "stolen_abroad": "reject",
                "account_takeover": "reject", "card_testing": "approve"}  # fmt: skip
    seen = set()
    for case in _cases(db, assisted):
        assert case.ai_recommendation == expected[case.kind], case.kind
        seen.add(case.kind)
    assert {"card_testing", "stolen_abroad", "traveller"} <= seen
    assert ai["recommendation_accuracy"] < 1
    # Released blocks went through the release step; kept ones did not.
    released = _cases(db, assisted, outcome="approved")
    assert released and all("release" in c.path for c in released)
    kept = _cases(db, assisted, outcome="rejected")
    assert kept and all("release" not in c.path for c in kept)
