"""Phase 88: the dashboard drill-down — enterprise → country → department → workflow."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation
from app.core.permissions import RoleCode
from app.core.scope import Scope
from app.modules.analytics.drilldown import Path, drilldown
from app.modules.identity import scopes
from app.modules.workflows.models import (
    WorkflowCatalogueEntry,
    WorkflowDefinitionRecord,
    WorkflowExecution,
    WorkflowStepRun,
)
from app.simulation.models import SimulationRun
from tests.factories import auth, make_user

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
DEPT = "Drill-down Test Department"
OTHER = "Drill-down Other Department"


def _workflow(db: Session, workflow_id: str, name: str, department: str | None, countries):
    record = WorkflowDefinitionRecord(
        workflow_id=workflow_id, version=1, name=name, definition={},
        content_hash=uuid.uuid4().hex * 2,
    )  # fmt: skip
    db.add(record)
    db.add(WorkflowCatalogueEntry(workflow_id=workflow_id, department=department,
                                  countries=countries))  # fmt: skip
    db.flush()
    return record


def _run(db: Session, user) -> uuid.UUID:
    run = SimulationRun(
        scenario_id="drilldown-test", scenario_version=1, workflow_id="WF-T8801",
        workflow_version=1, profile="small", seed=1, config={}, config_hash="0" * 64,
        software_version="test", status="completed", created_by=user.id,
        simulated_start=NOW - timedelta(days=2),
    )  # fmt: skip
    db.add(run)
    db.flush()
    return run.id


def _execution(db: Session, record, user, *, status="completed", outcome="approved",
               country=None, minutes=10, realm="live", started=None, steps=()):  # fmt: skip
    started = started or NOW - timedelta(days=1)
    execution = WorkflowExecution(
        id=uuid.uuid4(), realm=realm, workflow_id=record.workflow_id, workflow_version=1,
        definition_id=record.id, status=status, outcome=outcome if status == "completed" else None,
        context={"input": {"country_code": country} if country else {}},
        initiated_by=user.id, started_at=started,
        completed_at=started + timedelta(minutes=minutes) if status in ("completed", "failed")
        else None,
        updated_at=started,
        simulation_run_id=_run(db, user) if realm == "simulation" else None,
    )  # fmt: skip
    db.add(execution)
    db.flush()
    for n, (step_id, step_type, step_status, ms) in enumerate(steps):
        db.add(WorkflowStepRun(
            id=uuid.uuid4(), realm=realm, execution_id=execution.id, sequence=n,
            step_id=step_id, step_type=step_type, status=step_status, created_at=started,
            duration_ms=ms,
        ))  # fmt: skip
    db.flush()
    return execution


@pytest.fixture
def bank(db: Session):
    """Two variants of one process (a country each), a multi-country workflow whose
    executions name their country, and an unclassified one."""
    user = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    kenya = _workflow(db, "WF-T8801", "Overdraft — Kenya", DEPT, ["KE"])
    peru = _workflow(db, "WF-T8802", "Overdraft — Peru", DEPT, ["PE"])
    shared = _workflow(db, "WF-T8803", "Shared intake", OTHER, ["KE", "PE"])
    loose = _workflow(db, "WF-T8804", "Unclassified tool", None, [])
    steps = [("check", "service_task", "completed", 100), ("approve", "approval", "completed", 900)]
    for _ in range(3):
        _execution(db, kenya, user, steps=steps)
    _execution(db, kenya, user, status="failed", steps=[("check", "service_task", "failed", 50)])
    _execution(db, kenya, user, status="waiting",
               steps=[("check", "service_task", "completed", 120),
                      ("approve", "approval", "waiting", None)])  # fmt: skip
    _execution(db, kenya, user, outcome="rejected", realm="simulation")
    _execution(db, peru, user, minutes=30)
    _execution(db, shared, user, country="ke")  # the input names its country (lower case)
    _execution(db, shared, user)  # several catalogue countries, none named: not attributed
    _execution(db, loose, user, country="PE")
    _execution(db, kenya, user, started=NOW - timedelta(days=60))  # outside a 30-day window
    return user


def _row(result, key):
    return next(r for r in result["breakdown"] if r["key"] == key)


def test_the_bank_breaks_down_by_country_then_department_then_workflow(db: Session, bank) -> None:
    top = drilldown(db, Path(), now=NOW)
    assert top["level"] == "enterprise" and top["breakdown_by"] == "country"
    kenya = _row(top, "KE")
    assert kenya["label"] == "Kenya"
    # Kenya: 7 executions of its variant (one simulated, one older) + the shared intake.
    assert kenya["executions"] == 8 and kenya["failed"] == 1 and kenya["active"] == 1
    assert kenya["open_tasks"] == 1 and kenya["failure_rate"] == round(1 / 7, 4)
    assert _row(top, "none")["label"] == "Not attributed"

    country = drilldown(db, Path(country="KE"), now=NOW)
    assert [c["label"] for c in country["path"]] == ["ATLAS Global Bank", "Kenya"]
    assert {r["key"]: r["executions"] for r in country["breakdown"]} == {DEPT: 7, OTHER: 1}

    dept = drilldown(db, Path(country="KE", department=DEPT), now=NOW)
    assert dept["breakdown_by"] == "workflow"
    assert [(r["key"], r["label"]) for r in dept["breakdown"]] == [
        ("WF-T8801", "Overdraft — Kenya")
    ]

    flow = drilldown(db, Path(country="KE", department=DEPT, workflow_id="WF-T8801"), now=NOW)
    assert flow["level"] == "workflow" and flow["breakdown"] == []
    steps = {s["step_id"]: s for s in flow["steps"]}
    assert list(steps) == ["check", "approve"]  # in the order the steps run
    assert steps["check"]["runs"] == 5 and steps["check"]["failed"] == 1
    assert steps["approve"]["waiting"] == 1 and steps["approve"]["avg_ms"] == 900.0
    assert flow["outcomes"] == {"approved": 4, "rejected": 1, "none": 2}
    assert flow["summary"]["avg_duration_s"] == 600.0


def test_unattributed_and_unclassified_groups_can_be_opened(db: Session, bank) -> None:
    none = drilldown(db, Path(country="none"), now=NOW)
    assert none["path"][-1]["label"] == "Not attributed"
    assert _row(none, OTHER)["executions"] >= 1
    peru = drilldown(db, Path(country="PE"), now=NOW)
    assert (
        _row(peru, "none")["label"] == "Unclassified"
    )  # the uncatalogued tool, country from input
    unclassified = drilldown(db, Path(country="PE", department="none"), now=NOW)
    assert [r["key"] for r in unclassified["breakdown"]] == ["WF-T8804"]


def test_history_and_period_filters(db: Session, bank) -> None:
    path = Path(country="KE", department=DEPT, workflow_id="WF-T8801")
    assert drilldown(db, path, now=NOW)["summary"]["executions"] == 7
    assert drilldown(db, path, realm="live", now=NOW)["summary"]["executions"] == 6
    assert drilldown(db, path, realm="simulation", now=NOW)["summary"]["executions"] == 1
    assert drilldown(db, path, days=30, now=NOW)["summary"]["executions"] == 6
    with pytest.raises(BusinessRuleViolation):
        drilldown(db, path, realm="other", now=NOW)
    with pytest.raises(BusinessRuleViolation, match="country before a department"):
        drilldown(db, Path(department=DEPT), now=NOW)


def test_a_scoped_user_sees_only_their_scope(db: Session, bank) -> None:
    kenya_only = Scope(countries=frozenset({"KE"}))
    top = drilldown(db, Path(), scope=kenya_only, now=NOW)
    assert [r["key"] for r in top["breakdown"]] == ["KE"]  # no Peru, no "not attributed"
    assert top["scope"] == {"countries": ["KE"], "departments": None}
    assert drilldown(db, Path(country="PE"), scope=kenya_only, now=NOW)["summary"][
        "executions"] == 0  # fmt: skip
    one_dept = Scope(departments=frozenset({OTHER}))
    by_dept = drilldown(db, Path(country="KE"), scope=one_dept, now=NOW)
    assert [r["key"] for r in by_dept["breakdown"]] == [OTHER]


def test_the_api_applies_the_permission_and_the_callers_scope(
    client: TestClient, db: Session, bank
) -> None:
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    response = client.get("/api/v1/analytics/drilldown?country=KE", headers=auth(admin))
    assert response.status_code == 200 and response.json()["level"] == "country"
    scoped = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    scopes.set_scopes(db, scoped, ["PE"], [], admin.id)
    body = client.get("/api/v1/analytics/drilldown", headers=auth(scoped)).json()
    assert {r["key"] for r in body["breakdown"]} <= {"PE"}
    invalid = client.get("/api/v1/analytics/drilldown?country=Kenya", headers=auth(admin))
    assert invalid.status_code == 422
    # Every person role holds analytics:read; without a session there is nothing.
    assert client.get("/api/v1/analytics/drilldown").status_code == 401


def test_code_workflows_use_their_registered_catalogue(db: Session, bank) -> None:
    """PR #79 review: WF-0001 has no stored catalogue entry; its department is the one
    registered in code. A stored entry, when there is one, wins."""
    from app.modules.workflows import catalog  # noqa: F401
    from app.modules.workflows.registry import catalogue_of

    department = catalogue_of("WF-0001").department
    record = WorkflowDefinitionRecord(
        workflow_id="WF-0001", version=9001, name="Account opening (test version)",
        definition={}, content_hash=uuid.uuid4().hex * 2,
    )  # fmt: skip
    db.add(record)
    db.flush()
    _execution(db, record, bank, country="KE")
    kenya = drilldown(db, Path(country="KE"), now=NOW)
    assert department in {r["key"] for r in kenya["breakdown"]}
    scoped = drilldown(db, Path(country="KE"), scope=Scope(departments=frozenset({department})),
                       now=NOW)  # fmt: skip
    assert scoped["summary"]["executions"] >= 1  # no longer lost to a department scope

    db.add(WorkflowCatalogueEntry(workflow_id="WF-0001", department=OTHER, countries=[]))
    db.flush()
    overridden = drilldown(db, Path(country="KE"), now=NOW)
    assert department not in {r["key"] for r in overridden["breakdown"]}
