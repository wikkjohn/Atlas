"""Phase 52: the complaint-redress workload and the complaint review AI tool."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.accounts.service import charge_fee
from app.modules.ai_tools.adapters.complaint_review import (
    ComplaintProfile,
    ComplaintReviewConfig,
    ComplaintReviewInput,
    analyze,
)
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.customer_service import service as cs
from app.modules.customers.models import Customer
from app.modules.workflows import authoring
from app.modules.workflows.examples import HERE
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import get_scenario
from app.simulation.workloads import WORKLOADS
from tests.factories import funded_account, make_org_tree, make_staff, make_user

SCENARIO = get_scenario("complaint-redress")


def _advice(**profile) -> tuple[str, list[str]]:
    values = {"topic": "fees", "redress_amount": 1_000, "redress_usd": 10, "fees_90d": 1,
              "fees_90d_amount": 1_000, "redress_to_fees_pct": 100}  # fmt: skip
    result, _ = analyze(
        ComplaintReviewInput(profile=ComplaintProfile(**{**values, **profile})),
        ComplaintReviewConfig(),
    )
    return result.recommendation, [f.code for f in result.findings]


def test_the_complaint_rules_and_their_blind_spot() -> None:
    assert _advice() == ("approve", ["refund"])
    assert _advice(fees_90d=2, fees_90d_amount=2_000, redress_to_fees_pct=50,
                   duplicate_fee=True) == ("approve", ["duplicate_fee"])  # fmt: skip
    assert _advice(fees_90d=0, fees_90d_amount=0, redress_to_fees_pct=0) == (
        "reject", ["no_fee_found"]
    )  # fmt: skip
    assert _advice(redress_to_fees_pct=600) == ("reject", ["exceeds_loss"])
    goodwill = {"topic": "digital", "fees_90d": 0, "fees_90d_amount": 0}
    assert _advice(**goodwill, redress_usd=30) == ("approve", ["small_goodwill"])
    assert _advice(**goodwill, redress_usd=150) == ("escalate", ["moderate_goodwill"])
    assert _advice(**goodwill, redress_usd=900) == ("reject", ["large_goodwill"])
    # The blind spot: the customer's earlier complaints and redress are never read.
    assert _advice(prior_complaints_365d=4, prior_upheld_365d=4,
                   prior_redress_paid_365d_usd=40) == ("approve", ["refund"])  # fmt: skip


def test_the_complaint_profile(db: Session) -> None:
    staff = make_staff(db)
    account = funded_account(db, staff, balance=100_000)
    customer = db.get(Customer, account.customer_id)
    now = datetime.now(UTC)
    for n in range(2):  # the same fee twice
        charge_fee(db, account.id, amount=750, fee_code="MONTHLY", memo="Fee",
                   idempotency_key=f"cp-{account.id}-{n}", actor_id=staff.employee.id,
                   effective_date=now.date() - timedelta(days=10))  # fmt: skip
    charge_fee(db, account.id, amount=999, fee_code="OLD", memo="Old fee",
               idempotency_key=f"cp-{account.id}-old", actor_id=staff.employee.id,
               effective_date=now.date() - timedelta(days=120))  # fmt: skip
    earlier = cs.open_case(db, customer, category="complaint", channel="phone", topic="fees",
                           priority="normal", subject="Earlier", description="Earlier fee",
                           opened_by=staff.employee.id, account=account,
                           now=now - timedelta(days=60))  # fmt: skip
    cs.propose_redress(db, earlier, 750, account, staff.employee.id)
    cs.pay_redress(db, earlier, staff.manager.id)
    cs.resolve(db, earlier, staff.employee.id, "Refunded", "upheld")
    case = cs.open_case(db, customer, category="complaint", channel="email", topic="fees",
                        priority="normal", subject="Fee twice", description="Taken twice",
                        opened_by=staff.employee.id, account=account, now=now)  # fmt: skip
    cs.propose_redress(db, case, 750, account, staff.employee.id)
    profile = cs.complaint_profile(db, case, now)
    assert profile["fees_90d"] == 2 and profile["fees_90d_amount"] == 1_500  # not the old fee
    assert profile["duplicate_fee"] and profile["redress_to_fees_pct"] == 50
    assert profile["redress_usd"] == 7 and profile["description_chars"] == len("Taken twice")
    assert profile["prior_complaints_365d"] == 1 and profile["prior_upheld_365d"] == 1
    assert profile["prior_redress_paid_365d_usd"] == 7


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
    """The org tree, WF-1038 v1, the tool (compatible with WF-1038), then WF-1038 v2."""
    make_org_tree(db)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    authoring.import_definition(db, json.loads((HERE / "WF-1038.json").read_text()), admin.id)
    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-complaint-assistant")
    register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    authoring.import_definition(db, json.loads((HERE / "WF-1038-v2.json").read_text()), admin.id)


def _run(db: Session, factory, mode: str, seed: int = 11) -> SimulationRun:
    from app.modules.ai_tools.service import find_tool

    creator = make_user(db, RoleCode.AI_RESEARCHER)
    tool = find_tool(db, "agb-complaint-assistant") if mode != "baseline" else None
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


def test_complaint_runs_with_and_without_the_assistant(db: Session, factory) -> None:
    _setup(db)
    db.commit()
    baseline = _run(db, factory, "baseline")
    assisted = _run(db, factory, "ai_assisted")
    for run in (baseline, assisted):
        assert run.status == SimulationStatus.COMPLETED, run.failure_reason
        assert run.results["completed"] == 40
        controls = WORKLOADS["complaint_redress"].check_controls(db, run.id)
        # Every redress goes to a manager other than whoever proposed it.
        assert controls.decisions == 40 and controls.violations == []
    assert baseline.results["ai"]["invocations"] == 0
    ai = assisted.results["ai"]
    assert ai["invocations"] == 40 and ai["failed_invocations"] == 0
    expected = {"duplicate_fee": "approve", "fee_refund": "approve", "small_goodwill": "approve",
                "moderate_goodwill": "escalate", "no_fee_found": "reject",
                "redress_exceeds_loss": "reject", "large_goodwill": "reject",
                "serial_complainant": "approve"}  # fmt: skip
    seen = set()
    for case in _cases(db, assisted):
        assert case.ai_recommendation == expected[case.kind], case.kind
        seen.add(case.kind)
    assert {"serial_complainant", "fee_refund", "no_fee_found"} <= seen
    assert ai["recommendation_accuracy"] < 1
    upheld = _cases(db, assisted, outcome="approved")
    assert upheld and all("pay" in c.path for c in upheld)
    refused = _cases(db, assisted, outcome="rejected")
    assert refused and all("withdraw" in c.path for c in refused)
