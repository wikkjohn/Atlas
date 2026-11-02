"""Phase 58: the invoice-payments workload and the invoice review AI tool."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.ai_tools.adapters.invoice_review import (
    InvoiceProfile,
    InvoiceReviewConfig,
    InvoiceReviewInput,
    analyze,
)
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.procurement import service as procurement
from app.modules.workflows import authoring
from app.modules.workflows.examples import HERE
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import get_scenario
from app.simulation.workloads import WORKLOADS
from tests.factories import make_org_tree, make_user

SCENARIO = get_scenario("invoice-payments")


def _advice(**profile) -> tuple[str, list[str]]:
    values = {"amount": 250_000, "amount_usd": 2_500, "vendor_age_days": 400}
    result, _ = analyze(
        InvoiceReviewInput(profile=InvoiceProfile(**{**values, **profile})), InvoiceReviewConfig()
    )
    return result.recommendation, [f.code for f in result.findings]


def test_the_invoice_rules_and_their_blind_spot() -> None:
    assert _advice() == ("approve", ["routine"])
    assert _advice(bank_changed_days_ago=5, paid_since_bank_change=0) == (
        "reject", ["recent_bank_change"])  # fmt: skip
    # Paid to the new account since, or changed long ago: nothing to confirm.
    assert _advice(bank_changed_days_ago=5, paid_since_bank_change=1) == ("approve", ["routine"])
    assert _advice(bank_changed_days_ago=200, paid_since_bank_change=0) == (
        "approve", ["routine"])  # fmt: skip
    assert _advice(invoice_before_order=True) == ("reject", ["dated_before_order"])
    assert _advice(over_received_bps=150) == ("escalate", ["over_received"])
    assert _advice(vendor_age_days=5, amount_usd=20_000) == ("escalate", ["new_vendor_large"])
    assert _advice(vendor_age_days=5, amount_usd=2_000) == ("approve", ["routine"])
    assert _advice(vendor_risk_tier="high") == ("escalate", ["high_risk_vendor"])
    # The blind spot: the same amount billed before is never read.
    assert _advice(vendor_invoices_90d=2, same_amount_invoices_90d=1) == ("approve", ["routine"])


def test_the_invoice_profile(db: Session) -> None:
    tree = make_org_tree(db)
    clerk = make_user(db, RoleCode.BANKING_EMPLOYEE)
    manager = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    now = datetime.now(UTC)
    vendor = procurement.register_vendor(db, name="Linden Facilities", country_code="US",
                                         category="facilities", bank_account="US000123456789",
                                         registered_by=clerk.id)  # fmt: skip
    procurement.decide_vendor(db, vendor, manager.id, True)
    vendor.created_at = now - timedelta(days=300)

    def received_order(amount: int, received: int, days_ago: int):
        order = procurement.raise_order(db, vendor, tree.us_onboarding.id, "Cleaning",
                                        [{"description": "Cleaning", "quantity": 1,
                                          "unit_price": amount}], clerk.id)  # fmt: skip
        procurement.decide_order(db, order, manager.id, True)
        procurement.receive(db, order, received, clerk.id)
        order.created_at = now - timedelta(days=days_ago)
        return order

    # An earlier invoice for the same amount, paid 30 days ago, before a bank change.
    earlier = received_order(120_000, 120_000, 40)
    first = procurement.record_invoice(db, earlier, "LF-1", 120_000, date(2041, 1, 1), clerk.id)
    procurement.pay_invoice(db, first, manager.id)
    first.created_at = first.decided_at = now - timedelta(days=30)
    procurement.request_bank_change(db, vendor, "US000987654321", clerk.id)
    procurement.verify_bank_change(db, vendor, manager.id, True)
    vendor.bank_changed_at = now - timedelta(days=6)
    # This one: half delivered, invoiced 1 % over, dated before its order.
    order = received_order(240_000, 120_000, 20)
    invoice = procurement.record_invoice(db, order, "LF-2", 121_200,
                                         (now - timedelta(days=25)).date(), clerk.id)  # fmt: skip
    db.flush()
    profile = procurement.invoice_profile(db, invoice)
    assert profile["amount"] == 121_200 and profile["amount_usd"] == 1_212
    assert profile["vendor_age_days"] == 300 and profile["vendor_risk_tier"] == "low"
    assert profile["bank_changed_days_ago"] == 6 and profile["paid_since_bank_change"] == 0
    assert profile["invoice_before_order"] and profile["invoice_age_days"] == 25
    assert profile["partial_delivery"] and profile["over_received_bps"] == 100
    assert profile["vendor_invoices_90d"] == 1 and profile["same_amount_invoices_90d"] == 0


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
    """The org tree, WF-1048 v1, the tool (compatible with WF-1048), then WF-1048 v2."""
    make_org_tree(db)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    authoring.import_definition(db, json.loads((HERE / "WF-1048.json").read_text()), admin.id)
    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-invoice-assistant")
    register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    authoring.import_definition(db, json.loads((HERE / "WF-1048-v2.json").read_text()), admin.id)


def _run(db: Session, factory, mode: str, seed: int = 11) -> SimulationRun:
    from app.modules.ai_tools.service import find_tool

    creator = make_user(db, RoleCode.AI_RESEARCHER)
    tool = find_tool(db, "agb-invoice-assistant") if mode != "baseline" else None
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


def test_invoice_runs_with_and_without_the_assistant(db: Session, factory) -> None:
    _setup(db)
    db.commit()
    baseline = _run(db, factory, "baseline")
    assisted = _run(db, factory, "ai_assisted")
    for run in (baseline, assisted):
        assert run.status == SimulationStatus.COMPLETED, run.failure_reason
        assert run.results["completed"] == 40
        controls = WORKLOADS["invoice_payments"].check_controls(db, run.id)
        # Every invoice reaches a manager other than whoever recorded it: none is held.
        assert controls.decisions == 40 and controls.violations == []
    assert baseline.results["ai"]["invocations"] == 0
    ai = assisted.results["ai"]
    assert ai["invocations"] == 40 and ai["failed_invocations"] == 0
    expected = {"routine": "approve", "partial_delivery": "approve",
                "within_tolerance": "escalate", "old_bank_change": "approve",
                "new_vendor_small": "approve", "recent_bank_change": "reject",
                "backdated": "reject", "near_duplicate": "approve"}  # fmt: skip
    seen = set()
    for case in _cases(db, assisted):
        assert case.ai_recommendation == expected[case.kind], case.kind
        seen.add(case.kind)
    assert {"near_duplicate", "routine", "recent_bank_change", "backdated"} <= seen
    assert ai["recommendation_accuracy"] < 1
    paid = _cases(db, assisted, outcome="approved")
    assert paid and all("pay" in c.path for c in paid)
    rejected = _cases(db, assisted, outcome="rejected")
    assert rejected and all("reject" in c.path for c in rejected)
