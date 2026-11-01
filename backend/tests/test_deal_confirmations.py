"""Phase 40: the deal-confirmations workload and the back-office check AI tool."""

import json
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.accounts.service import deposit
from app.modules.ai_tools.adapters.back_office_check import (
    BackOfficeCheckConfig,
    BackOfficeCheckInput,
    DealProfile,
    analyze,
)
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.treasury import service as treasury
from app.modules.workflows import authoring
from app.modules.workflows.examples import HERE
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import get_scenario
from app.simulation.workloads import WORKLOADS
from tests.factories import make_customer, make_org_tree, make_staff, make_user, open_account

SCENARIO = get_scenario("deal-confirmations")
TODAY = date(2026, 6, 9)


def _advice(**profile) -> tuple[str, list[str]]:
    values = {"kind": "placement", "currency": "USD", "rate_bps": 530, "reference_rate_bps": 525,
              "rate_against_bank_bps": -5, "tenor_days": 30, "rating": "AA",
              "limit_utilisation_bps": 4000, "coverage_after_bps": 50_000}  # fmt: skip
    result, _ = analyze(
        BackOfficeCheckInput(profile=DealProfile(**{**values, **profile})),
        BackOfficeCheckConfig(),
    )
    return result.recommendation, [f.code for f in result.findings]


def test_the_back_office_rules_and_their_blind_spot() -> None:
    assert _advice() == ("approve", [])
    assert _advice(rate_against_bank_bps=200) == ("reject", ["off_market"])
    assert _advice(rate_against_bank_bps=80) == ("approve", ["slightly_off"])
    assert _advice(rating="BBB-", tenor_days=240) == (
        "reject",
        ["weak_name_long_tenor", "long_tenor"],
    )
    # Most of a limit for longer than 90 days: escalate.
    assert _advice(limit_utilisation_bps=9400, tenor_days=120) == (
        "escalate",
        ["near_limit", "long_tenor"],
    )
    assert _advice(kind="borrowing", limit_utilisation_bps=9900, coverage_after_bps=None) == (
        "approve",
        [],
    )
    # The blind spot: a same-day duplicate is in the profile and never read.
    assert _advice(same_day_duplicates=1) == ("approve", [])


def test_the_deal_profile(db: Session) -> None:
    staff = make_staff(db)
    treasury.ensure_counterparties(db)
    customer = make_customer(db)
    account = open_account(db, staff, customer)
    deposit(db, account.id, amount=2_000_000_000, memo="Synthetic", actor_id=staff.employee.id,
            idempotency_key=f"profile-{account.id}")  # fmt: skip
    currency = account.currency
    northgate = treasury.find_counterparty(db, "CP-NORTHGATE")
    reference = treasury.reference_rate(currency)
    first = treasury.book_deal(
        db, counterparty=northgate, kind="placement", currency=currency, principal=100_000_000,
        rate_bps=reference - 200, tenor_days=120, booked_by=staff.employee.id, today=TODAY,
    )  # fmt: skip
    treasury.confirm_deal(db, first, staff.manager.id, now=datetime(2026, 6, 9, 8, tzinfo=UTC))
    again = treasury.book_deal(
        db, counterparty=northgate, kind="placement", currency=currency, principal=100_000_000,
        rate_bps=reference - 200, tenor_days=120, booked_by=staff.employee.id, today=TODAY,
    )  # fmt: skip
    profile = treasury.deal_profile(db, again, TODAY)
    assert profile["rate_against_bank_bps"] == 200 and profile["tenor_days"] == 120
    assert profile["rating"] == "AA-" and profile["same_day_duplicates"] == 1
    # Both placements count against the limit: exposure over US$250m.
    used = treasury.exposure_usd(db, northgate, TODAY)
    assert profile["limit_utilisation_bps"] == used * 10_000 // 250_000_000
    # Matures beyond 30 days: 1,800m of cash left against 200m of stressed outflow.
    assert profile["coverage_after_bps"] == 1_800_000_000 * 10_000 // 200_000_000


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
    """The org tree, WF-1018 v1, the tool (compatible with WF-1018), then WF-1018 v2."""
    make_org_tree(db)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    authoring.import_definition(db, json.loads((HERE / "WF-1018.json").read_text()), admin.id)
    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-back-office-check-assistant")
    register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    authoring.import_definition(db, json.loads((HERE / "WF-1018-v2.json").read_text()), admin.id)


def _run(db: Session, factory, mode: str, seed: int = 11) -> SimulationRun:
    from app.modules.ai_tools.service import find_tool

    creator = make_user(db, RoleCode.AI_RESEARCHER)
    tool = find_tool(db, "agb-back-office-check-assistant") if mode != "baseline" else None
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


def test_deal_runs_with_and_without_the_assistant(db: Session, factory) -> None:
    _setup(db)
    db.commit()
    baseline = _run(db, factory, "baseline")
    assisted = _run(db, factory, "ai_assisted")
    for run in (baseline, assisted):
        assert run.status == SimulationStatus.COMPLETED, run.failure_reason
        assert run.results["completed"] == 40
        controls = WORKLOADS["deal_confirmations"].check_controls(db, run.id)
        # Every deal goes to back office.
        assert controls.decisions == 40 and controls.violations == []
    assert baseline.results["ai"]["invocations"] == 0
    ai = assisted.results["ai"]
    assert ai["invocations"] == 40 and ai["failed_invocations"] == 0
    expected = {"standard_placement": "approve", "standard_borrowing": "approve",
                "off_market_rate": "reject", "weak_counterparty": "reject",
                "duplicate_booking": "approve", "stretched_counterparty": "escalate"}  # fmt: skip
    seen = set()
    for case in _cases(db, assisted):
        assert case.ai_recommendation == expected[case.kind], case.kind
        seen.add(case.kind)
    assert {"duplicate_booking", "off_market_rate", "standard_placement"} <= seen
    assert ai["recommendation_accuracy"] < 1
    confirmed = _cases(db, assisted, outcome="approved")
    assert confirmed and all("settle" in c.path for c in confirmed)
    cancelled = _cases(db, assisted, outcome="rejected")
    assert cancelled and all("cancel" in c.path for c in cancelled)


def test_pr31_review_fixes(db: Session) -> None:
    """Settlement locks use FOR NO KEY UPDATE; a same-day deal on other terms is no
    duplicate."""
    import uuid

    from sqlalchemy.dialects import postgresql

    sql = str(treasury.lock_query({uuid.uuid4()}).compile(dialect=postgresql.dialect()))
    assert sql.endswith("FOR NO KEY UPDATE")
    staff = make_staff(db)
    treasury.ensure_counterparties(db)
    northgate = treasury.find_counterparty(db, "CP-NORTHGATE")

    def book(rate: int, tenor: int):
        return treasury.book_deal(
            db, counterparty=northgate, kind="borrowing", currency="USD", principal=50_000_000,
            rate_bps=rate, tenor_days=tenor, booked_by=staff.employee.id, today=TODAY,
        )  # fmt: skip

    book(500, 30)
    other_rate, other_tenor, same = book(510, 30), book(500, 60), book(500, 30)
    assert treasury.deal_profile(db, other_rate, TODAY)["same_day_duplicates"] == 0
    assert treasury.deal_profile(db, other_tenor, TODAY)["same_day_duplicates"] == 0
    assert treasury.deal_profile(db, same, TODAY)["same_day_duplicates"] == 1
