"""Phase 38: the discrepant-presentations workload and the document check AI tool."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.accounts.models import AccountType
from app.modules.accounts.service import deposit
from app.modules.ai_tools.adapters.document_check import (
    DocumentCheckConfig,
    DocumentCheckInput,
    PresentationProfile,
    analyze,
)
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.customers.models import CustomerType
from app.modules.trade import service as trade
from app.modules.workflows import authoring
from app.modules.workflows.examples import HERE
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import get_scenario
from app.simulation.workloads import WORKLOADS
from tests.factories import make_customer, make_org_tree, make_staff, make_user, open_account

SCENARIO = get_scenario("discrepant-presentations")


def _advice(**profile) -> tuple[str, list[str]]:
    values = {"currency": "USD", "discrepancy": "late_presentation", "draw_share_bps": 5000,
              "days_to_expiry": 90, "funding_cover_bps": 30_000}  # fmt: skip
    result, _ = analyze(
        DocumentCheckInput(profile=PresentationProfile(**{**values, **profile})),
        DocumentCheckConfig(),
    )
    return result.recommendation, [f.code for f in result.findings]


def test_the_document_check_rules_and_their_blind_spot() -> None:
    assert _advice() == ("approve", ["minor"])
    assert _advice(discrepancy="description_mismatch") == ("approve", ["minor"])
    assert _advice(discrepancy="missing_document") == ("reject", ["title_risk"])
    assert _advice(discrepancy="late_shipment") == ("approve", ["late_shipment"])
    assert _advice(discrepancy="late_shipment", days_to_expiry=4) == ("reject", ["last_minute"])
    assert _advice(discrepancy="inconsistent_documents", draw_share_bps=9500)[0] == "reject"
    # A late shipment the applicant can barely fund: escalate.
    assert _advice(discrepancy="late_shipment", funding_cover_bps=10_400) == (
        "escalate",
        ["late_shipment", "thin_funds"],
    )
    # The blind spot: earlier rejections for the same discrepancy are never read.
    history = {"earlier_presentations": 1, "earlier_rejected": 1, "earlier_same_discrepancy": 1}
    assert _advice(**history) == ("approve", ["minor"])


def test_the_presentation_profile(db: Session) -> None:
    staff = make_staff(db)
    business = make_customer(db, customer_type=CustomerType.BUSINESS, name="Heron Foods Ltd",
                             born=date(2006, 1, 1))  # fmt: skip
    account = open_account(db, staff, business, AccountType.BUSINESS_CURRENT)
    deposit(db, account.id, amount=3_000_000, memo="Synthetic", actor_id=staff.employee.id,
            idempotency_key=f"profile-{account.id}")  # fmt: skip
    today = date(2026, 5, 12)
    lc = trade.request_instrument(
        db, customer=business, account=account, kind="letter_of_credit",
        beneficiary_name="Saigon Coffee Exporters", beneficiary_country="VN", amount=5_000_000,
        expires_on=today + timedelta(days=40), purpose="Coffee", requested_by=staff.employee.id,
        today=today - timedelta(days=30),
    )  # fmt: skip
    trade.approve_instrument(db, lc, staff.manager.id, now=datetime(2026, 4, 12, tzinfo=UTC))
    first = trade.receive_demand(db, lc, amount=2_000_000, presented_on=today,
                                 discrepancies=["late_presentation"], received_by=None)  # fmt: skip
    trade.reject_demand(db, first, staff.manager.id, "Not waived")
    again = trade.receive_demand(db, lc, amount=2_000_000, presented_on=today,
                                 discrepancies=["late_presentation"], received_by=None)  # fmt: skip
    profile = trade.presentation_profile(db, again)
    assert profile["discrepancy"] == "late_presentation" and profile["draw_share_bps"] == 4000
    assert profile["days_to_expiry"] == 40
    # 2,000,000 left after the 1,000,000 margin, plus 400,000 released on payment.
    assert profile["funding_cover_bps"] == 12_000
    assert profile["earlier_presentations"] == 1 and profile["earlier_rejected"] == 1
    assert profile["earlier_same_discrepancy"] == 1


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
    """The org tree, WF-1016 v1, the tool (compatible with WF-1016), then WF-1016 v2."""
    make_org_tree(db)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    authoring.import_definition(db, json.loads((HERE / "WF-1016.json").read_text()), admin.id)
    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-document-check-assistant")
    register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    authoring.import_definition(db, json.loads((HERE / "WF-1016-v2.json").read_text()), admin.id)


def _run(db: Session, factory, mode: str, seed: int = 11) -> SimulationRun:
    from app.modules.ai_tools.service import find_tool

    creator = make_user(db, RoleCode.AI_RESEARCHER)
    tool = find_tool(db, "agb-document-check-assistant") if mode != "baseline" else None
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


def test_presentation_runs_with_and_without_the_assistant(db: Session, factory) -> None:
    _setup(db)
    db.commit()
    baseline = _run(db, factory, "baseline")
    assisted = _run(db, factory, "ai_assisted")
    for run in (baseline, assisted):
        assert run.status == SimulationStatus.COMPLETED, run.failure_reason
        assert run.results["completed"] == 40
        controls = WORKLOADS["discrepant_presentations"].check_controls(db, run.id)
        # Every presentation is discrepant, so a trade officer decides each waiver.
        assert controls.decisions == 40 and controls.violations == []
    assert baseline.results["ai"]["invocations"] == 0
    ai = assisted.results["ai"]
    assert ai["invocations"] == 40 and ai["failed_invocations"] == 0
    expected = {"late_presentation": "approve", "wording_slip": "approve",
                "missing_document": "reject", "last_minute_shipment": "reject",
                "repeat_discrepancy": "approve", "stretched_applicant": "escalate"}  # fmt: skip
    seen = set()
    for case in _cases(db, assisted):
        assert case.ai_recommendation == expected[case.kind], case.kind
        seen.add(case.kind)
    assert {"repeat_discrepancy", "missing_document", "late_presentation"} <= seen
    assert ai["recommendation_accuracy"] < 1
    paid = _cases(db, assisted, outcome="approved")
    assert paid and all("pay_waived" in c.path for c in paid)
    rejected = _cases(db, assisted, outcome="rejected")
    assert rejected and all("reject_waiver" in c.path for c in rejected)
