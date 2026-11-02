"""Phase 60: the change-approvals workload and the change review AI tool."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.ai_tools.adapters.change_review import (
    ChangeProfile,
    ChangeReviewConfig,
    ChangeReviewInput,
    analyze,
)
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.itops import service as itops
from app.modules.workflows import authoring
from app.modules.workflows.examples import HERE
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import get_scenario
from app.simulation.workloads import WORKLOADS
from tests.factories import make_org_tree, make_user

SCENARIO = get_scenario("change-approvals")
NOW = datetime(2041, 3, 5, 9, 0, tzinfo=UTC)  # a Tuesday


def _advice(**profile) -> tuple[str, list[str]]:
    result, _ = analyze(ChangeReviewInput(profile=ChangeProfile(**profile)), ChangeReviewConfig())
    return result.recommendation, [f.code for f in result.findings]


def test_the_change_rules_and_their_blind_spot() -> None:
    assert _advice() == ("approve", ["routine"])
    assert _advice(has_backout_plan=False) == ("reject", ["no_backout_plan"])
    assert _advice(open_major_incidents=1) == ("reject", ["open_major_incident"])
    assert _advice(business_hours=True, start_hour_utc=11) == ("reject", ["business_hours"])
    # Business hours are fine on a tier-3 application.
    assert _advice(business_hours=True, start_hour_utc=11, tier=3) == ("approve", ["routine"])
    assert _advice(lead_hours=12) == ("escalate", ["short_notice"])
    assert _advice(window_hours=10) == ("escalate", ["long_window"])
    # The blind spot: failed changes to the application and by the requester are never read.
    assert _advice(app_failed_changes_90d=3, requester_failed_changes_90d=3,
                   app_changes_90d=3) == ("approve", ["routine"])  # fmt: skip


def test_the_change_profile(db: Session) -> None:
    tree = make_org_tree(db)
    engineer = make_user(db, RoleCode.BANKING_EMPLOYEE)
    manager = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    app = itops.register_application(db, name="Loan Desk", description="", tier=2,
                                     department_id=tree.us_onboarding.id,
                                     actor_id=None)  # fmt: skip
    plan = "Redeploy the previous release."
    # Two earlier changes by the same engineer, 40 and 20 days ago: one failed.
    for days_ago, success in ((40, True), (20, False)):
        raised = NOW - timedelta(days=days_ago)
        earlier = itops.raise_change(db, app, title="Patch the desk", kind="normal",
                                     backout_plan=plan, planned_start=raised + timedelta(days=1),
                                     planned_end=raised + timedelta(days=1, hours=2),
                                     requested_by=engineer.id, now=raised)  # fmt: skip
        itops.decide_change(db, earlier, manager.id, True)
        itops.implement(db, earlier, engineer.id, success, raised + timedelta(days=1))
    # The failure's incident (a P2) is still open.
    start = NOW + timedelta(hours=3)  # 12:00 UTC on a Tuesday: business hours
    change = itops.raise_change(db, app, title="Patch it again", kind="normal",
                                backout_plan="", planned_start=start,
                                planned_end=start + timedelta(hours=10),
                                requested_by=engineer.id, now=NOW)  # fmt: skip
    profile = itops.change_profile(db, change)
    assert profile["kind"] == "normal" and profile["tier"] == 2
    assert profile["risk"] == "high" and not profile["has_backout_plan"]
    assert profile["window_hours"] == 10 and profile["start_hour_utc"] == 12
    assert profile["business_hours"] and profile["lead_hours"] == 3
    assert not profile["in_freeze"] and profile["open_major_incidents"] == 1
    assert profile["app_changes_90d"] == 2 and profile["app_failed_changes_90d"] == 1
    assert profile["requester_failed_changes_90d"] == 1


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
    """The org tree, WF-1050 v1, the tool (compatible with WF-1050), then WF-1050 v2."""
    make_org_tree(db)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    authoring.import_definition(db, json.loads((HERE / "WF-1050.json").read_text()), admin.id)
    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-change-assistant")
    register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    authoring.import_definition(db, json.loads((HERE / "WF-1050-v2.json").read_text()), admin.id)


def _run(db: Session, factory, mode: str, seed: int = 11) -> SimulationRun:
    from app.modules.ai_tools.service import find_tool

    creator = make_user(db, RoleCode.AI_RESEARCHER)
    tool = find_tool(db, "agb-change-assistant") if mode != "baseline" else None
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


def test_change_runs_with_and_without_the_assistant(db: Session, factory) -> None:
    _setup(db)
    db.commit()
    baseline = _run(db, factory, "baseline")
    assisted = _run(db, factory, "ai_assisted")
    for run in (baseline, assisted):
        assert run.status == SimulationStatus.COMPLETED, run.failure_reason
        assert run.results["completed"] == 40
        controls = WORKLOADS["change_approvals"].check_controls(db, run.id)
        # Every change reaches a manager other than whoever raised it.
        assert controls.decisions == 40 and controls.violations == []
    assert baseline.results["ai"]["invocations"] == 0
    ai = assisted.results["ai"]
    assert ai["invocations"] == 40 and ai["failed_invocations"] == 0
    expected = {"routine": "approve", "tier3_daytime": "approve", "short_notice": "escalate",
                "no_backout": "reject", "during_incident": "reject",
                "business_hours": "reject", "serial_failures": "approve"}  # fmt: skip
    seen = set()
    for case in _cases(db, assisted):
        assert case.ai_recommendation == expected[case.kind], case.kind
        seen.add(case.kind)
    assert {"serial_failures", "routine", "business_hours", "during_incident"} <= seen
    assert ai["recommendation_accuracy"] < 1
    approved = _cases(db, assisted, outcome="approved")
    assert approved and all("approve" in c.path for c in approved)
    rejected = _cases(db, assisted, outcome="rejected")
    assert rejected and all("reject" in c.path for c in rejected)
