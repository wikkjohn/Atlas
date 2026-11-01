"""Phase 50: manual journals, the journal-review workload and the journal review AI tool."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation
from app.core.permissions import RoleCode
from app.modules.ai_tools.adapters.journal_review import (
    JournalProfile,
    JournalReviewConfig,
    JournalReviewInput,
    analyze,
)
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.finance import service as finance
from app.modules.ledger import service as ledger
from app.modules.workflows import authoring
from app.modules.workflows.examples import HERE
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import get_scenario
from app.simulation.workloads import WORKLOADS
from tests.factories import auth, make_org_tree, make_staff, make_user

SCENARIO = get_scenario("journal-review")


def _advice(**profile) -> tuple[str, list[str]]:
    values = {"amount_usd": 12_000, "materiality_pct": 12, "description_chars": 50}
    result, _ = analyze(
        JournalReviewInput(profile=JournalProfile(**{**values, **profile})), JournalReviewConfig()
    )
    return result.recommendation, [f.code for f in result.findings]


def test_the_journal_rules_and_their_blind_spot() -> None:
    assert _advice() == ("approve", ["routine"])
    assert _advice(touches_equity=True) == ("reject", ["equity_adjustment"])
    assert _advice(duplicate_of="MJ-0000001")[0] == "reject"
    assert _advice(days_backdated=60) == ("reject", ["stale"])
    assert _advice(days_backdated=5, in_closed_period=True) == ("reject", ["closed_period"])
    assert _advice(touches_cash=True, round_amount=True, description_chars=10)[0] == "reject"
    assert _advice(touches_cash=True, round_amount=True) == ("approve", ["routine"])
    assert _advice(materiality_pct=250) == ("escalate", ["material"])
    assert _advice(materiality_pct=250, description_chars=12) == (
        "reject", ["material_undocumented"]
    )  # fmt: skip
    # The blind spot: the preparer's other journals on the same accounts are never read.
    assert _advice(materiality_pct=90, same_accounts_7d=3, same_accounts_7d_usd=270_000) == (
        "approve", ["routine"]
    )  # fmt: skip


def _accounts(db: Session) -> tuple[str, str]:
    return finance.shared_costs_account(db, "USD").code, finance.accruals_account(db, "USD").code


def _lines(debit: str, credit: str, amount: int) -> list[dict]:
    return [{"account_code": debit, "direction": "debit", "amount": amount},
            {"account_code": credit, "direction": "credit", "amount": amount}]  # fmt: skip


def test_manual_journals_and_their_profile(db: Session) -> None:
    staff = make_staff(db)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    expense, accrual = _accounts(db)
    today = datetime.now(UTC).date()
    for bad, rule in (
        (_lines(expense, accrual, 100)[:1], "2 to 20"),
        ([*_lines(expense, accrual, 100)[:1], {**_lines(expense, accrual, 99)[1]}], "equal"),
        (_lines(expense, "NO-SUCH-ACCOUNT", 100), "No ledger account"),
    ):
        with pytest.raises(BusinessRuleViolation, match=rule):
            finance.propose_journal(db, currency="USD", effective_date=today, description="x",
                                    lines=bad, proposed_by=staff.manager.id)  # fmt: skip
    # Finance's standard accounts are created on first use, in a currency already booked in.
    assert finance._ledger_account(db, "fin-accruals-usd").account_type == "liability"
    with pytest.raises(BusinessRuleViolation, match="No ledger account"):
        finance._ledger_account(db, "FIN-ACCRUALS-XQZ")
    first = finance.propose_journal(db, currency="USD", effective_date=today - timedelta(days=4),
                                    description="Accrual for October invoices",
                                    lines=_lines(expense, accrual, 9_000_000),
                                    proposed_by=staff.manager.id)  # fmt: skip
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        finance.approve_journal(db, first, staff.manager.id)
    finance.approve_journal(db, first, executive.id)
    assert first.status == "posted" and first.entry_number.startswith("JE-")
    assert ledger.balance(db, finance.accruals_account(db, "USD")) == 9_000_000
    again = finance.propose_journal(db, currency="USD", effective_date=today,
                                    description="Accrual for October invoices",
                                    lines=_lines(expense, accrual, 9_000_000),
                                    proposed_by=staff.manager.id)  # fmt: skip
    profile = finance.journal_profile(db, again, today)
    assert profile["amount_usd"] == 90_000 and profile["materiality_pct"] == 90
    assert profile["account_types"] == ["expense", "liability"]
    assert not profile["touches_cash"] and not profile["touches_equity"]
    assert profile["duplicate_of"] == first.journal_number
    assert profile["same_accounts_7d"] == 1 and profile["same_accounts_7d_usd"] == 90_000
    cash = ledger.cash_account(db, "USD").code
    old = today - timedelta(days=40)
    round_cash = finance.propose_journal(db, currency="USD", effective_date=old,
                                         description="Adjustment",
                                         lines=_lines(expense, cash, 500_000),
                                         proposed_by=staff.employee.id)  # fmt: skip
    profile = finance.journal_profile(db, round_cash, today)
    assert profile["touches_cash"] and profile["round_amount"] and profile["days_backdated"] == 40
    assert profile["same_accounts_7d"] == 0  # another preparer
    finance.reject_journal(db, round_cash, executive.id, "Unexplained")
    assert round_cash.status == "rejected"


def test_the_journal_api(client: TestClient, db: Session) -> None:
    staff = make_staff(db)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    expense, accrual = _accounts(db)
    db.commit()
    body = {
        "currency": "USD",
        "effective_date": date.today().isoformat(),
        "description": "Accrual for legal fees",
        "lines": _lines(expense, accrual, 250_000),
    }
    assert client.post("/api/v1/finance/journals", json=body,
                       headers=auth(staff.employee)).status_code == 403  # fmt: skip
    made = client.post("/api/v1/finance/journals", json=body, headers=auth(staff.manager))
    assert made.status_code == 201 and made.json()["status"] == "proposed"
    url = f"/api/v1/finance/journals/{made.json()['id']}"
    assert client.get(f"{url}/profile", headers=auth(executive)).json()["amount_usd"] == 2_500
    assert client.post(f"{url}/approve", headers=auth(staff.manager)).status_code == 403
    assert client.post(f"{url}/approve", headers=auth(executive)).json()["status"] == "posted"
    counts = client.get("/api/v1/finance/summary/counts", headers=auth(executive)).json()
    assert counts["journals_to_approve"] == 0


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
    """The org tree, WF-1036 v1, the tool (compatible with WF-1036), then WF-1036 v2."""
    make_org_tree(db)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    authoring.import_definition(db, json.loads((HERE / "WF-1036.json").read_text()), admin.id)
    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-journal-assistant")
    register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    authoring.import_definition(db, json.loads((HERE / "WF-1036-v2.json").read_text()), admin.id)


def _run(db: Session, factory, mode: str, seed: int = 11) -> SimulationRun:
    from app.modules.ai_tools.service import find_tool

    creator = make_user(db, RoleCode.AI_RESEARCHER)
    tool = find_tool(db, "agb-journal-assistant") if mode != "baseline" else None
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


def test_journal_runs_with_and_without_the_assistant(db: Session, factory) -> None:
    _setup(db)
    db.commit()
    baseline = _run(db, factory, "baseline")
    assisted = _run(db, factory, "ai_assisted")
    for run in (baseline, assisted):
        assert run.status == SimulationStatus.COMPLETED, run.failure_reason
        assert run.results["completed"] == 40
        controls = WORKLOADS["journal_review"].check_controls(db, run.id)
        # Every journal goes to an approver, never its preparer.
        assert controls.decisions == 40 and controls.violations == []
    assert baseline.results["ai"]["invocations"] == 0
    ai = assisted.results["ai"]
    assert ai["invocations"] == 40 and ai["failed_invocations"] == 0
    expected = {"routine_accrual": "approve", "reclassification": "approve",
                "large_documented": "escalate", "equity_adjustment": "reject",
                "stale_backdated": "reject", "duplicate_entry": "reject",
                "unexplained_cash": "reject", "split_below_threshold": "approve"}  # fmt: skip
    seen = set()
    for case in _cases(db, assisted):
        assert case.ai_recommendation == expected[case.kind], case.kind
        seen.add(case.kind)
    assert {"split_below_threshold", "routine_accrual", "duplicate_entry"} <= seen
    assert ai["recommendation_accuracy"] < 1
    posted = _cases(db, assisted, outcome="approved")
    assert posted and all("approve" in c.path for c in posted)
    rejected = _cases(db, assisted, outcome="rejected")
    assert rejected and all("reject" in c.path for c in rejected)
