"""Phase 71: named task assignment, delegation and escalation routing."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, PermissionDeniedError
from app.core.permissions import RoleCode
from app.modules.employees.models import Employee
from app.modules.identity.models import User
from app.modules.workflows import authoring, engine
from app.modules.workflows.definition import WorkflowDefinition
from app.modules.workflows.models import RunStatus, TaskDelegation, WorkflowEvent, WorkflowStepRun
from tests.factories import auth, make_employee, make_org_tree, make_user, principal

NOW = datetime(2026, 11, 2, 9, tzinfo=UTC)  # a Monday
EXAMPLES = Path(__file__).parent.parent / "app" / "modules" / "workflows" / "examples"


def _doc(workflow_id: str, assign: str | None, action: str = "flag") -> dict:
    approval: dict = {"permissions": ["hr:manage"], "distinct_from": ["initiator"]}
    if assign:
        approval["assign"] = assign
    return {
        "workflow_id": workflow_id,
        "name": "Routing test",
        "description": "A test workflow with one approval (Phase 71).",
        "version": 1,
        "business_owner": "Human Resources",
        "trigger_type": "api",
        "input_schema": {"type": "object", "properties": {}},
        "start": "approval",
        "steps": [
            {"id": "approval", "type": "approval", "name": "Approve", "approval": approval,
             "timeout": {"after_seconds": 3600, "action": action},
             "transitions": [{"to": "approved", "when": {"path": "approval.approved",
                                                          "op": "truthy"}}],
             "next": "rejected"},
            {"id": "approved", "type": "completion", "name": "Approved", "outcome": "approved"},
            {"id": "rejected", "type": "completion", "name": "Rejected", "outcome": "rejected"},
        ],
    }  # fmt: skip


def _person(db: Session, role: RoleCode, employee: Employee | None = None) -> User:
    user = make_user(db, role)
    user.employee_id = employee.id if employee else None
    db.flush()
    return user


@pytest.fixture
def team(db: Session):
    """A head of department over a team lead over an analyst, each with an account, and two
    HR approvers outside the line."""
    tree = make_org_tree(db)
    org = tree.us_onboarding
    head_e = make_employee(db, org, first_name="Head", role=RoleCode.DEPARTMENT_MANAGER)
    lead_e = make_employee(db, org, first_name="Lead", manager=head_e,
                           role=RoleCode.DEPARTMENT_MANAGER)  # fmt: skip
    analyst_e = make_employee(db, org, first_name="Analyst", manager=lead_e)
    people = {
        "head": _person(db, RoleCode.DEPARTMENT_MANAGER, head_e),
        "lead": _person(db, RoleCode.DEPARTMENT_MANAGER, lead_e),
        "analyst": _person(db, RoleCode.BANKING_EMPLOYEE, analyst_e),
        "hr_a": _person(db, RoleCode.DEPARTMENT_MANAGER),
        "hr_b": _person(db, RoleCode.DEPARTMENT_MANAGER),
        "admin": _person(db, RoleCode.PLATFORM_ADMINISTRATOR),
    }
    # Only the people made here compete for tasks: other qualified accounts are switched off.
    for other in db.execute(select(User).where(User.id.not_in([u.id for u in people.values()]),
                                              User.is_active.is_(True))).scalars():  # fmt: skip
        other.is_active = False
    for workflow_id, assign, action in [("WF-9711", "least_loaded", "flag"),
                                        ("WF-9712", "initiator_manager", "escalate"),
                                        ("WF-9713", None, "escalate")]:  # fmt: skip
        authoring.import_definition(db, _doc(workflow_id, assign, action), people["admin"].id)
    db.flush()
    return people


def _start(db: Session, workflow_id: str, initiator: User):
    execution, _ = engine.start(
        db, workflow_id=workflow_id, version=1, payload={}, initiator=principal(initiator),
        now=NOW, allow_inactive=True,
    )  # fmt: skip
    run = db.execute(select(WorkflowStepRun).where(
        WorkflowStepRun.execution_id == execution.id,
        WorkflowStepRun.status == RunStatus.WAITING)).scalar_one()  # fmt: skip
    return execution, run


def _events(db: Session, execution_id, kind: str) -> list[WorkflowEvent]:
    query = select(WorkflowEvent).where(WorkflowEvent.execution_id == execution_id,
                                        WorkflowEvent.event_type == kind)  # fmt: skip
    return list(db.execute(query).scalars())


def test_least_loaded_spreads_tasks_and_only_the_assignee_decides(db: Session, team) -> None:
    runs = [_start(db, "WF-9711", team["analyst"])[1] for _ in range(6)]
    counts: dict = {}
    for run in runs:
        counts[run.assignee_id] = counts.get(run.assignee_id, 0) + 1
    # Five qualified people (head, lead, two HR approvers and the administrator), not the
    # initiator; six tasks go out one at a time, each to whoever has the fewest.
    assert team["analyst"].id not in counts
    assert max(counts.values()) - min(counts.values()) <= 1 and len(counts) == 5
    run = runs[0]
    assignee = db.get(User, run.assignee_id)
    other = next(u for k, u in team.items() if k not in ("analyst",) and u.id != assignee.id)
    with pytest.raises(PermissionDeniedError) as refused:
        engine.complete_task(db, run.id, principal(other), decision="approve", now=NOW)
    assert refused.value.details["rule"] == "not_assignee"
    execution = engine.complete_task(db, run.id, principal(assignee), decision="approve", now=NOW)
    assert execution.outcome == "approved"
    (assigned,) = _events(db, execution.id, "task.assigned")
    assert assigned.data["rule"] == "least_loaded"


def test_the_initiator_s_manager_then_escalation_up_the_line(db: Session, team) -> None:
    execution, run = _start(db, "WF-9712", team["analyst"])
    assert run.assignee_id == team["lead"].id  # the analyst's line manager
    # Overdue: it goes to the lead's manager, the head of department.
    engine.process_timers(db, execution, NOW + timedelta(hours=2))
    db.refresh(run)
    assert run.assignee_id == team["head"].id and run.delegated_from_id == team["lead"].id
    assert run.escalated_at is not None
    (escalated,) = _events(db, execution.id, "task.escalated")
    assert escalated.data["from_id"] == str(team["lead"].id)
    # It escalates once: the timer does not fire again.
    assert engine.process_timers(db, execution, NOW + timedelta(hours=5)) == 0
    with pytest.raises(PermissionDeniedError):
        engine.complete_task(db, run.id, principal(team["lead"]), decision="approve", now=NOW)
    engine.complete_task(db, run.id, principal(team["head"]), decision="reject", now=NOW)

    # A head of department's own request: nobody above them, so the least loaded decides.
    _, own = _start(db, "WF-9712", team["head"])
    assert own.assignee_id not in (None, team["head"].id)
    (assigned,) = _events(db, own.execution_id, "task.assigned")
    assert assigned.data["rule"] == "least_loaded"


def test_a_queue_task_escalates_to_the_initiator_s_manager(db: Session, team) -> None:
    execution, run = _start(db, "WF-9713", team["analyst"])
    assert run.assignee_id is None  # a shared queue: anyone qualified may take it
    engine.process_timers(db, execution, NOW + timedelta(hours=2))
    db.refresh(run)
    assert run.assignee_id == team["lead"].id and run.delegated_from_id is None
    # With nobody in the line (the administrator has no employee record), it is flagged.
    execution, run = _start(db, "WF-9713", team["admin"])
    engine.process_timers(db, execution, NOW + timedelta(hours=2))
    db.refresh(run)
    assert run.assignee_id is None and run.escalated_at is not None
    assert _events(db, execution.id, "task.overdue")


def test_out_of_office_and_handing_a_task_on(db: Session, team) -> None:
    db.add(TaskDelegation(user_id=team["lead"].id, delegate_id=team["hr_a"].id,
                          starts_on=date(2026, 11, 1), ends_on=date(2026, 11, 6),
                          reason="Annual leave"))  # fmt: skip
    db.flush()
    execution, run = _start(db, "WF-9712", team["analyst"])
    assert run.assignee_id == team["hr_a"].id and run.delegated_from_id == team["lead"].id
    (assigned,) = _events(db, execution.id, "task.assigned")
    assert assigned.data["away"] == str(team["lead"].id)
    # The delegate hands it to a colleague; not to the initiator (four-eyes).
    with pytest.raises(BusinessRuleViolation) as refused:
        engine.delegate_task(db, run.id, principal(team["hr_a"]), team["analyst"].id, now=NOW)
    assert refused.value.details["rule"] == "delegate_not_qualified"
    engine.delegate_task(db, run.id, principal(team["hr_a"]), team["hr_b"].id, note="Busy",
                         now=NOW)  # fmt: skip
    db.refresh(run)
    assert run.assignee_id == team["hr_b"].id and run.delegated_from_id == team["hr_a"].id
    # Someone else cannot pass it on; a workflow manager can.
    with pytest.raises(PermissionDeniedError):
        engine.delegate_task(db, run.id, principal(team["hr_a"]), team["head"].id, now=NOW)
    engine.delegate_task(db, run.id, principal(team["admin"]), team["head"].id, now=NOW)
    db.refresh(run)
    assert run.assignee_id == team["head"].id
    assert len(_events(db, execution.id, "task.delegated")) == 2


def test_the_api(client: TestClient, db: Session, team) -> None:
    _, run = _start(db, "WF-9712", team["analyst"])
    db.commit()
    lead, hr_a = auth(team["lead"]), auth(team["hr_a"])
    mine = client.get("/api/v1/workflow-tasks?mine=true", headers=lead).json()
    assert [t["run_id"] for t in mine["items"]] == [str(run.id)]
    (task,) = mine["items"]
    assert task["assigned_to_me"] and task["can_act"]
    assert task["assignee_username"] == team["lead"].username
    # Others see it, but cannot act on it.
    seen = client.get("/api/v1/workflow-tasks", headers=hr_a).json()["items"]
    (other_view,) = [t for t in seen if t["run_id"] == str(run.id)]
    assert not other_view["can_act"] and not other_view["assigned_to_me"]
    assert client.get("/api/v1/workflow-tasks?actionable=true", headers=hr_a).json()["total"] == 0
    candidates = client.get(f"/api/v1/workflow-tasks/{run.id}/candidates", headers=lead).json()
    assert team["analyst"].username not in {c["username"] for c in candidates}
    assert [c["assignee"] for c in candidates].count(True) == 1
    handed = client.post(f"/api/v1/workflow-tasks/{run.id}/delegate", headers=lead,
                         json={"delegate_id": str(team["hr_a"].id), "note": "Away"})  # fmt: skip
    assert handed.status_code == 200, handed.text
    assert handed.json()["delegated_from_username"] == team["lead"].username
    refused = client.post(f"/api/v1/workflow-tasks/{run.id}/complete", headers=lead,
                          json={"decision": "approve"})  # fmt: skip
    assert refused.status_code == 403
    done = client.post(f"/api/v1/workflow-tasks/{run.id}/complete", headers=hr_a,
                       json={"decision": "approve"})  # fmt: skip
    assert done.status_code == 200, done.text
    step = next(s for s in done.json()["steps"] if s["step_id"] == "approval")
    assert step["assignee_username"] == team["hr_a"].username

    found = client.get("/api/v1/workflow-tasks/people?q=" + team["hr_b"].username, headers=lead)
    assert [p["username"] for p in found.json()] == [team["hr_b"].username]

    # Out of office.
    body = {"delegate_id": str(team["hr_b"].id), "starts_on": "2026-11-10",
            "ends_on": "2026-11-20", "reason": "Training"}  # fmt: skip
    made = client.post("/api/v1/workflow-tasks/delegations", headers=lead, json=body)
    assert made.status_code == 201, made.text
    assert made.json()["username"] == team["lead"].username
    # The delegate sees it too; only a workflow manager may set one up for someone else.
    listed = client.get("/api/v1/workflow-tasks/delegations", headers=auth(team["hr_b"])).json()
    assert [d["id"] for d in listed] == [made.json()["id"]]
    other = client.post("/api/v1/workflow-tasks/delegations", headers=hr_a,
                        json={**body, "user_id": str(team["lead"].id)})  # fmt: skip
    assert other.status_code == 403
    backwards = client.post("/api/v1/workflow-tasks/delegations", headers=lead,
                            json={**body, "ends_on": "2026-11-01"})  # fmt: skip
    assert backwards.status_code == 422
    gone = client.delete(f"/api/v1/workflow-tasks/delegations/{made.json()['id']}", headers=hr_a)
    assert gone.status_code == 403
    gone = client.delete(f"/api/v1/workflow-tasks/delegations/{made.json()['id']}", headers=lead)
    assert gone.status_code == 204
    assert client.get("/api/v1/workflow-tasks/delegations", headers=lead).json() == []


def test_definitions_and_simulations_are_unchanged() -> None:
    # The new fields default to None, so earlier definitions keep their content hashes.
    v2 = WorkflowDefinition.model_validate(json.loads((EXAMPLES / "WF-1044-v2.json").read_text()))
    assert "assign" not in json.dumps(v2.model_dump(mode="json", exclude_none=True))
    v3 = WorkflowDefinition.model_validate(json.loads((EXAMPLES / "WF-1044-v3.json").read_text()))
    approval = v3.step("approval")
    assert approval.approval.assign == "initiator_manager"
    assert approval.timeout.action == "escalate"
    bad = _doc("WF-9714", None, "escalate")
    bad["steps"].insert(0, {"id": "pause", "type": "wait", "name": "Wait", "next": "approval",
                            "timeout": {"after_seconds": 60, "action": "escalate"}})  # fmt: skip
    bad["start"] = "pause"
    loose = WorkflowDefinition.model_validate(bad, context={"defer_graph": True})
    assert [p["code"] for p in loose.graph_problems()] == ["timeout_escalate"]
