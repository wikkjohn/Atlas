"""Phase 42: the recall-triage workload and the recall review AI tool."""

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.accounts.models import AccountType
from app.modules.accounts.service import deposit
from app.modules.ai_tools.adapters.recall_review import (
    RecallProfile,
    RecallReviewConfig,
    RecallReviewInput,
    analyze,
)
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.clearing import service as clearing
from app.modules.workflows import authoring
from app.modules.workflows.examples import HERE
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import get_scenario
from app.simulation.workloads import WORKLOADS
from tests.factories import make_customer, make_org_tree, make_staff, make_user, open_account

SCENARIO = get_scenario("recall-triage")
TODAY = date(2026, 9, 15)


def _advice(**profile) -> tuple[str, list[str]]:
    values = {"reason_code": "DUPL", "days_since_settlement": 2, "window_days": 10,
              "days_left": 8, "duplicate_matches": 1}  # fmt: skip
    result, _ = analyze(
        RecallReviewInput(profile=RecallProfile(**{**values, **profile})), RecallReviewConfig()
    )
    return result.recommendation, [f.code for f in result.findings]


def test_the_recall_rules_and_their_blind_spot() -> None:
    assert _advice() == ("approve", [])
    assert _advice(duplicate_matches=0) == ("reject", ["no_duplicate_found"])
    assert _advice(days_since_settlement=12, days_left=-2)[0] == "reject"
    fraud = {"reason_code": "FRAD", "window_days": 3, "days_since_settlement": 0, "days_left": 3}
    assert _advice(**fraud) == ("approve", [])
    assert _advice(**fraud, payee_history=4) == ("reject", ["established_payee"])
    # A late technical recall of a high-value payment: escalate.
    late_tech = {"reason_code": "TECH", "days_since_settlement": 9, "days_left": 1}
    assert _advice(**late_tech, high_value=True) == ("escalate", ["near_window_end", "high_value"])
    # The blind spot: the payer's earlier recalls, most refused, are never read.
    cust = {"reason_code": "CUST", "window_days": 5, "days_left": 3}
    assert _advice(**cust, payer_recalls_90d=4, payer_refused_90d=3) == ("approve", [])


def test_the_recall_profile(db: Session) -> None:
    staff = make_staff(db)
    account = open_account(db, staff, make_customer(db), AccountType.CURRENT)
    deposit(db, account.id, amount=5_000_000, memo="Synthetic", actor_id=staff.employee.id,
            idempotency_key=f"recall-{account.id}")  # fmt: skip
    payee = clearing.account_number("123456789012")

    def pay(amount: int, days_ago: int, to: str = payee):
        on = TODAY - timedelta(days=days_ago)
        payment = clearing.create_outgoing(
            db, debtor=account, beneficiary_name="Supplier", beneficiary_bank="NBKAGB22",
            beneficiary_account=to, amount=amount, reference="x",
            initiated_by=staff.employee.id, today=on,
        )  # fmt: skip
        clearing.run_cycle(db, account.currency, None, today=on)
        return payment

    pay(30_000, 40)
    pay(40_000, 30)  # two earlier payments to the same beneficiary
    earlier = pay(10_000, 20, to=clearing.account_number("223456789012"))
    refused = clearing.request_recall(db, earlier, "CUST", staff.employee.id)
    clearing.approve_recall(db, refused, staff.manager.id)
    clearing.resolve_recall(db, refused, staff.manager.id, today=TODAY - timedelta(days=11))
    pay(50_000, 2)
    twin = pay(50_000, 2)  # keyed twice
    recall = clearing.request_recall(db, twin, "DUPL", staff.employee.id)
    profile = clearing.recall_profile(db, recall, TODAY)
    assert profile["days_since_settlement"] == 2 and profile["days_left"] == 8
    assert profile["duplicate_matches"] == 1 and profile["payee_history"] == 2
    assert profile["payer_recalls_90d"] == 1 and profile["payer_refused_90d"] == 1


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
    """The org tree, WF-1023 v1, the tool (compatible with WF-1023), then WF-1023 v2."""
    make_org_tree(db)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    authoring.import_definition(db, json.loads((HERE / "WF-1023.json").read_text()), admin.id)
    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-recall-assistant")
    register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    authoring.import_definition(db, json.loads((HERE / "WF-1023-v2.json").read_text()), admin.id)


def _run(db: Session, factory, mode: str, seed: int = 11) -> SimulationRun:
    from app.modules.ai_tools.service import find_tool

    creator = make_user(db, RoleCode.AI_RESEARCHER)
    tool = find_tool(db, "agb-recall-assistant") if mode != "baseline" else None
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


def test_recall_runs_with_and_without_the_assistant(db: Session, factory) -> None:
    _setup(db)
    db.commit()
    baseline = _run(db, factory, "baseline")
    assisted = _run(db, factory, "ai_assisted")
    for run in (baseline, assisted):
        assert run.status == SimulationStatus.COMPLETED, run.failure_reason
        assert run.results["completed"] == 40
        controls = WORKLOADS["recall_triage"].check_controls(db, run.id)
        # Every recall goes to back office.
        assert controls.decisions == 40 and controls.violations == []
    assert baseline.results["ai"]["invocations"] == 0
    ai = assisted.results["ai"]
    assert ai["invocations"] == 40 and ai["failed_invocations"] == 0
    expected = {"genuine_duplicate": "approve", "fraud_reported_fast": "approve",
                "claimed_duplicate_no_match": "reject", "fraud_on_known_payee": "reject",
                "serial_recaller": "approve", "stretched_tech": "escalate"}  # fmt: skip
    seen = set()
    for case in _cases(db, assisted):
        assert case.ai_recommendation == expected[case.kind], case.kind
        seen.add(case.kind)
    assert {"serial_recaller", "claimed_duplicate_no_match", "genuine_duplicate"} <= seen
    assert ai["recommendation_accuracy"] < 1
    recovered = _cases(db, assisted, outcome="approved")
    assert recovered and all("resolve" in c.path for c in recovered)
    withdrawn = _cases(db, assisted, outcome="rejected")
    assert withdrawn and all("withdraw" in c.path for c in withdrawn)


def test_recall_cases_come_from_the_runs_countries(db: Session, factory) -> None:
    """PR #33 review: a run limited to Germany builds its payers there (EUR payments)."""
    from app.modules.clearing.models import OutgoingPayment

    _setup(db)
    creator = make_user(db, RoleCode.AI_RESEARCHER)
    run = create_run(
        db, SCENARIO, profile="custom", applications=6, employees=6, seed=5,
        created_by=creator.id, countries=["DE"],
    )  # fmt: skip
    db.commit()
    execute_run(factory, run.id)
    db.expire_all()
    assert db.get(SimulationRun, run.id).status == SimulationStatus.COMPLETED
    currencies = set(db.execute(select(OutgoingPayment.currency)).scalars())
    assert currencies == {"EUR"}
