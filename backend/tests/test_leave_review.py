"""Phase 56: the leave-requests workload and the leave review AI tool."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Connection, select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.ai_tools.adapters.leave_review import (
    LeaveProfile,
    LeaveReviewConfig,
    LeaveReviewInput,
    analyze,
)
from app.modules.ai_tools.schemas import ToolCreate
from app.modules.ai_tools.service import register_tool
from app.modules.hr import service as hr
from app.modules.workflows import authoring
from app.modules.workflows.examples import HERE
from app.seed import DEMO_AI_TOOLS
from app.simulation.models import SimulationCaseResult, SimulationRun, SimulationStatus
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import get_scenario
from app.simulation.workloads import WORKLOADS
from tests.factories import make_employee, make_org_tree, make_user

SCENARIO = get_scenario("leave-requests")
MONDAY = date(2041, 3, 4)


def _advice(**profile) -> tuple[str, list[str]]:
    values = {"kind": "annual", "days": 3, "notice_days": 30, "coverage_pct": 80}
    result, _ = analyze(
        LeaveReviewInput(profile=LeaveProfile(**{**values, **profile})), LeaveReviewConfig()
    )
    return result.recommendation, [f.code for f in result.findings]


def test_the_leave_rules_and_their_blind_spot() -> None:
    assert _advice() == ("approve", ["routine"])
    assert _advice(coverage_pct=40) == ("reject", ["understaffed"])
    assert _advice(coverage_pct=60) == ("escalate", ["tight_cover"])
    assert _advice(days=6, notice_days=3) == ("reject", ["short_notice"])
    assert _advice(days=2, notice_days=3) == ("approve", ["routine"])
    assert _advice(kind="sick", days=8, notice_days=0) == ("escalate", ["long_sickness"])
    # The blind spot: the employee's short-notice history is never read.
    assert _advice(days=1, notice_days=2, prior_requests_90d=4,
                   prior_short_notice_90d=4) == ("approve", ["routine"])  # fmt: skip


def test_the_leave_profile(db: Session) -> None:
    tree = make_org_tree(db)
    manager, other = make_user(db, RoleCode.DEPARTMENT_MANAGER), make_user(
        db, RoleCode.DEPARTMENT_MANAGER)  # fmt: skip
    team = [make_employee(db, tree.us_onboarding) for _ in range(5)]
    employee = team[0]
    # Two colleagues away on the Tuesday of the week asked for.
    for colleague in team[1:3]:
        away = hr.request_leave(db, colleague, "annual", MONDAY + timedelta(days=1),
                                MONDAY + timedelta(days=1), manager.id)  # fmt: skip
        hr.decide_leave(db, away, other.id, approve=True)
    # An earlier day off asked for the day before, and a sick day.
    early = hr.request_leave(db, employee, "annual", date(2041, 2, 4), date(2041, 2, 4),
                             manager.id)  # fmt: skip
    sick = hr.request_leave(db, employee, "sick", date(2041, 2, 11), date(2041, 2, 12),
                            manager.id)  # fmt: skip
    hr.decide_leave(db, sick, other.id, approve=True)
    leave = hr.request_leave(db, employee, "annual", MONDAY, MONDAY + timedelta(days=4),
                             manager.id)  # fmt: skip
    early.created_at = datetime(2041, 2, 3, tzinfo=UTC)
    sick.created_at = datetime(2041, 2, 11, tzinfo=UTC)
    leave.created_at = datetime(2041, 2, 25, tzinfo=UTC)
    db.flush()
    profile = hr.leave_profile(db, leave)
    assert profile["days"] == 5 and profile["notice_days"] == 7
    assert profile["annual_balance_after"] == 25 - 1 - 5
    assert profile["department_headcount"] == 5 and profile["others_away"] == 2
    assert profile["coverage_pct"] == 40  # five, less two away and the employee
    assert profile["sick_days_365"] == 2
    assert profile["prior_requests_90d"] == 2 and profile["prior_short_notice_90d"] == 2


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
    """The org tree, WF-1044 v1, the tool (compatible with WF-1044), then WF-1044 v2."""
    make_org_tree(db)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    authoring.import_definition(db, json.loads((HERE / "WF-1044.json").read_text()), admin.id)
    spec = next(t for t in DEMO_AI_TOOLS if t["tool_id"] == "agb-leave-assistant")
    register_tool(db, ToolCreate.model_validate(spec), actor_id=None)
    authoring.import_definition(db, json.loads((HERE / "WF-1044-v2.json").read_text()), admin.id)


def _run(db: Session, factory, mode: str, seed: int = 11) -> SimulationRun:
    from app.modules.ai_tools.service import find_tool

    creator = make_user(db, RoleCode.AI_RESEARCHER)
    tool = find_tool(db, "agb-leave-assistant") if mode != "baseline" else None
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


def test_leave_runs_with_and_without_the_assistant(db: Session, factory) -> None:
    _setup(db)
    db.commit()
    baseline = _run(db, factory, "baseline")
    assisted = _run(db, factory, "ai_assisted")
    for run in (baseline, assisted):
        assert run.status == SimulationStatus.COMPLETED, run.failure_reason
        assert run.results["completed"] == 40
        controls = WORKLOADS["leave_requests"].check_controls(db, run.id)
        # Every request goes to a manager other than whoever made it.
        assert controls.decisions == 40 and controls.violations == []
    assert baseline.results["ai"]["invocations"] == 0
    ai = assisted.results["ai"]
    assert ai["invocations"] == 40 and ai["failed_invocations"] == 0
    expected = {"routine_annual": "approve", "planned_long": "approve", "short_sick": "approve",
                "short_notice_short": "approve", "tight_cover": "escalate",
                "understaffed": "reject", "short_notice_long": "reject",
                "serial_short_notice": "approve"}  # fmt: skip
    seen = set()
    for case in _cases(db, assisted):
        assert case.ai_recommendation == expected[case.kind], case.kind
        seen.add(case.kind)
    assert {"serial_short_notice", "routine_annual", "understaffed"} <= seen
    assert ai["recommendation_accuracy"] < 1
    approved = _cases(db, assisted, outcome="approved")
    assert approved and all("approve" in c.path for c in approved)
    rejected = _cases(db, assisted, outcome="rejected")
    assert rejected and all("reject" in c.path for c in rejected)
