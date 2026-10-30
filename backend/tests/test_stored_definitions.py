"""Phase 17: workflow definitions stored as data — validation, import, versions, lifecycle,
and executions that run on them exactly like code-registered workflows."""

import copy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.permissions import RoleCode
from app.modules.workflows import authoring, engine, examples, registry, store, validation
from app.modules.workflows.engine import WorkflowInputError
from app.modules.workflows.models import DefinitionStatus, WorkflowExecution
from tests.factories import auth, make_user, principal

# Content hashes of the code-registered definitions before Phase 17. The definition model
# gained optional fields (step params, presentation); existing definitions must not change,
# or their stored snapshots would no longer match and running cases could not continue.
CODE_HASHES = {
    ("WF-0001", 1): "4238dc63f9484f9b018df21ee52631302e625740e47e78cddf742e48aca745c4",
    ("WF-0001", 2): "0e3491b0f0b44a2c674f6902cf40fdfeea96ef47acb1194fee9ee5bebaaafe93",
    ("WF-0002", 1): "a62689ecc16f01a41938d130bd9f00d3343513b713b1df20cca2bc588e3f5021",
    ("WF-0003", 1): "ca63bd13c80438f78b7a54711e163d017c17745fff690f195b5164eb556254b8",
    ("WF-0003", 2): "1704897613bea4254a929eead568cc38e3e6d17d4b67ade071f2a74ed2f55d0b",
    ("WF-0004", 1): "625b59b8f362c4b1fe7d4a7b2f3bb540c8e6b0e987ef7271cabbad8c5a4b8878",
}

ADDRESS = {
    "customer_number": "CUS-0000042",
    "street": "1 Synthetic Way",
    "city": "Testville",
    "postal_code": "TS1 1AA",
    "country_code": "GB",
    "reason": "moved",
}


def document(workflow_id: str = "WF-1901", version: int = 1) -> dict:
    """The WF-1001 example under a test id (the demo seed may already hold WF-1001)."""
    (example,) = [
        d for d in examples.documents() if (d["workflow_id"], d["version"]) == ("WF-1001", 1)
    ]
    doc = copy.deepcopy(example)
    doc["workflow_id"], doc["version"] = workflow_id, version
    return doc


def steps(doc: dict) -> dict[str, dict]:
    return {s["id"]: s for s in doc["steps"]}


def codes(report: validation.Report) -> set[str]:
    return {e["code"] for e in report.errors}


def test_code_definitions_keep_their_content_hashes() -> None:
    assert {
        (d.workflow_id, d.version): d.content_hash() for d in registry.all_definitions()
    } == CODE_HASHES


def test_the_example_definition_is_valid_and_clean() -> None:
    report = validation.validate(None, examples.documents()[0])
    assert report.valid and report.warnings == [], (report.errors, report.warnings)


def test_validation_reports_every_problem_at_once() -> None:
    doc = document()
    by_id = steps(doc)
    by_id["assign_key"]["handler"] = "core.nope"
    by_id["check_country"]["params"]["condition"]["path"] = "input.contry_code"
    by_id["record_change"]["params"]["fields"]["city"] = "nowhere.city"
    by_id["notify_updated"]["params"]["channel"] = "pigeon"
    by_id["colleague_review"]["approval"]["permissions"] = ["customers:mange"]
    by_id["compliance_review"]["approval"]["distinct_from"] = ["initiator", "record_change"]
    by_id["record_change"]["timeout"] = {"after_seconds": 60}
    by_id["route_by_reason"]["params"] = {"x": 1}
    doc["presentation"]["subject_path"] = "input.customer"
    doc["input_schema"]["required"].append("phone")
    doc["steps"].append({"id": "trap", "type": "decision", "name": "Trap",
                         "transitions": [{"to": "trap"}]})  # fmt: skip

    report = validation.validate(None, doc)
    assert not report.valid
    assert codes(report) >= {
        "unknown_handler",
        "unknown_input_field",
        "unknown_path",
        "literal_error",  # the channel
        "unknown_permission",
        "unknown_task",
        "timeout_unsupported",
        "params_unused",
        "unknown_field",
        "unreachable",
        "cannot_finish",
    }
    located = {(e["location"], e["code"]) for e in report.errors}
    assert ("steps.assign_key.handler", "unknown_handler") in located
    assert ("steps.notify_updated.params.channel", "literal_error") in located
    assert ("presentation.subject_path", "unknown_input_field") in located


def test_validation_guards_ids_triggers_people_and_schemas() -> None:
    doc = document("WF-0001")
    doc["trigger_type"] = "simulation"
    steps(doc)["colleague_review"]["approval"]["permissions"] = ["accounts:approve_low_risk"]
    doc["input_schema"] = {"type": "array"}
    report = validation.validate(None, doc)
    assert codes(report) >= {
        "owned_by_code",
        "trigger_unsupported",
        "schema_not_object",
    }
    # Held by the automated policy engine and, like everything, by administrators only.
    assert "administrators_only" in {w["code"] for w in report.warnings}
    ai = document()
    steps(ai)["record_change"].update(type="ai_task", handler="core.copy_values")
    # Phase 18: AI steps may use the library's AI handlers, but not a service handler.
    assert "handler_type_mismatch" in codes(validation.validate(None, ai))
    # Structural errors are reported in the same pass, with a location.
    broken = document()
    steps(broken)["notify_updated"]["next"] = "updated_typo"
    broken["start"] = "nowhere"
    found = validation.validate(None, broken).errors
    assert {(e["location"], e["code"]) for e in found} >= {
        ("start", "unknown_step"),
        ("steps.notify_updated", "unknown_step"),
    }


def test_warnings_do_not_block_an_import(db: Session) -> None:
    doc = document()
    del doc["presentation"]
    doc["input_schema"].pop("additionalProperties")
    route = steps(doc)["route_by_reason"]
    route["transitions"].append(
        {"to": route.pop("next"), "when": {"path": "input.reason", "op": "eq", "value": "moved"}}
    )
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    _, created, report = authoring.import_definition(db, doc, admin.id)
    assert created
    assert {w["code"] for w in report.warnings} == {"no_presentation", "open_input", "no_fallback"}


def test_versions_are_immutable_and_increasing(db: Session) -> None:
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    first, created, _ = authoring.import_definition(db, document(), admin.id)
    assert created and first.source == "stored" and first.status == "active"
    again, created, _ = authoring.import_definition(db, document(), admin.id)
    assert (again.id, created) == (first.id, False)  # identical: a no-op

    changed = document()
    changed["description"] = "Edited after import"
    with pytest.raises(authoring.DefinitionInvalid) as refused:
        authoring.import_definition(db, changed, admin.id)
    assert refused.value.details["errors"][0]["code"] == "version_exists"

    authoring.import_definition(db, document(version=3), admin.id)
    with pytest.raises(authoring.DefinitionInvalid) as refused:
        authoring.import_definition(db, document(version=2), admin.id)
    assert refused.value.details["errors"][0]["code"] == "version_not_increasing"
    assert [r.version for r in store.stored_records(db, "WF-1901")] == [1, 3]

    audit = db.execute(
        select(AuditEvent.action).where(AuditEvent.entity_id == str(first.id))
    ).scalars()
    assert list(audit) == ["workflow_definition.imported"]


@pytest.fixture
def imported(db: Session):
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    record, _, _ = authoring.import_definition(db, document(), admin.id)
    return admin, record


def test_a_stored_workflow_runs_like_a_code_one(db: Session, imported) -> None:
    clerk = principal(make_user(db, RoleCode.BANKING_EMPLOYEE))
    colleague = principal(make_user(db, RoleCode.BANKING_EMPLOYEE))

    execution, _ = engine.start(db, workflow_id="WF-1901", payload=ADDRESS, initiator=clerk)
    assert execution.definition_id == imported[1].id
    assert (execution.status, execution.current_steps) == ("waiting", ["colleague_review"])
    assert execution.business_key == "ADDR-CUS-0000042"
    task = next(r for r in _runs(db, execution) if r.step_id == "colleague_review")
    with pytest.raises(PermissionDeniedError, match="Four-eyes"):
        engine.complete_task(db, task.id, clerk, decision="approve")

    store.forget()  # another process: nothing in memory, the definition comes from the DB
    engine.complete_task(db, task.id, colleague, decision="approve")
    assert (execution.status, execution.outcome) == ("completed", "updated")
    assert execution.context["record_change"]["city"] == "Testville"
    assert execution.context["notify_updated"]["template"] == "address_change_confirmed"

    correction, _ = engine.start(
        db, workflow_id="WF-1901", payload={**ADDRESS, "reason": "correction"}, initiator=clerk
    )
    assert (correction.status, correction.outcome) == ("completed", "updated")
    abroad, _ = engine.start(
        db, workflow_id="WF-1901", payload={**ADDRESS, "country_code": "FR"}, initiator=clerk
    )
    assert (abroad.status, abroad.outcome) == ("completed", "rejected")
    assert abroad.context["_failure"]["code"] == "country_not_served"

    with pytest.raises(WorkflowInputError) as invalid:
        engine.start(
            db,
            workflow_id="WF-1901",
            payload={**ADDRESS, "reason": "bored", "customer_number": "42", "extra": 1},
            initiator=clerk,
        )
    problems = {tuple(e["location"]): e["type"] for e in invalid.value.details}
    assert problems == {(): "additionalProperties", ("customer_number",): "pattern",
                        ("reason",): "enum"}  # fmt: skip


def _runs(db: Session, execution: WorkflowExecution):
    from app.modules.workflows.models import WorkflowStepRun

    db.flush()
    return list(
        db.execute(
            select(WorkflowStepRun).where(WorkflowStepRun.execution_id == execution.id)
        ).scalars()
    )


def test_retiring_stops_new_cases_but_not_running_ones(db: Session, imported) -> None:
    admin, record = imported
    clerk = principal(make_user(db, RoleCode.BANKING_EMPLOYEE))
    manager = principal(make_user(db, RoleCode.DEPARTMENT_MANAGER))
    running, _ = engine.start(db, workflow_id="WF-1901", payload=ADDRESS, initiator=clerk)

    authoring.set_status(db, "WF-1901", 1, DefinitionStatus.RETIRED, admin.id)
    with pytest.raises(ConflictError, match="retired"):
        engine.start(db, workflow_id="WF-1901", payload=ADDRESS, initiator=clerk)
    task = next(r for r in _runs(db, running) if r.status == "waiting")
    engine.complete_task(db, task.id, manager, decision="reject")
    assert (running.status, running.outcome) == ("completed", "declined")

    # A new version takes new cases; the old one stays readable.
    v2 = document(version=2)
    v2["name"] = "Customer Address Change (v2)"
    authoring.import_definition(db, v2, admin.id)
    fresh, _ = engine.start(db, workflow_id="WF-1901", payload=ADDRESS, initiator=clerk)
    assert fresh.workflow_version == 2
    assert store.resolve(db, "WF-1901", 1).version == 1
    with pytest.raises(ConflictError, match="retired"):
        engine.start(db, workflow_id="WF-1901", version=1, payload=ADDRESS, initiator=clerk)

    authoring.set_status(db, "WF-1901", 1, DefinitionStatus.ACTIVE, admin.id)
    old, _ = engine.start(db, workflow_id="WF-1901", version=1, payload=ADDRESS, initiator=clerk)
    assert old.workflow_version == 1
    with pytest.raises(ConflictError, match="registered in code"):
        authoring.set_status(db, "WF-0001", 1, DefinitionStatus.RETIRED, admin.id)
    with pytest.raises(NotFoundError):
        authoring.set_status(db, "WF-1999", 1, DefinitionStatus.RETIRED, admin.id)


def test_exports_round_trip_through_validation(db: Session, imported) -> None:
    exported = authoring.export(db, "WF-1901")
    assert exported == store.parsed(imported[1]).canonical_json()
    assert validation.validate(db, exported).existing == "identical"
    code = authoring.export(db, "WF-0002")
    report = validation.validate(None, code)
    # A code workflow's handlers are its own, not the library's: it cannot be imported.
    assert {"owned_by_code", "unknown_handler"} <= codes(report)


def publish(client: TestClient, author: dict, reviewer: dict, workflow_id: str, version: int):
    """Take an API-imported draft through review: submit, test, approve (four-eyes)."""
    base = f"/api/v1/workflow-definitions/{workflow_id}/versions/{version}"
    assert client.post(f"{base}/submit", headers=author).status_code == 200
    assert client.post(f"{base}/tests", headers=author).json()["failed"] == 0
    approved = client.post(f"{base}/approve", json={}, headers=reviewer)
    assert approved.status_code == 200, approved.text
    return approved.json()


def test_the_definitions_api(client: TestClient, db: Session) -> None:
    admin = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))
    employee_user = make_user(db, RoleCode.BANKING_EMPLOYEE)
    employee = auth(employee_user)
    body = {"definition": document()}

    assert client.post("/api/v1/workflow-definitions/validate", json=body,
                       headers=employee).status_code == 403  # fmt: skip
    report = client.post("/api/v1/workflow-definitions/validate", json=body, headers=admin)
    assert report.status_code == 200
    assert report.json() | {"content_hash": None, "effects": None} == {
        "valid": True, "workflow_id": "WF-1901", "version": 1, "content_hash": None,
        "existing": "new", "errors": [], "warnings": [], "effects": None,
    }  # fmt: skip
    broken = document()
    steps(broken)["assign_key"]["handler"] = "core.nope"
    refused = client.post("/api/v1/workflow-definitions", json={"definition": broken},
                          headers=admin)  # fmt: skip
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "definition_invalid"
    assert refused.json()["error"]["details"]["errors"][0]["code"] == "unknown_handler"

    created = client.post("/api/v1/workflow-definitions", json=body, headers=admin)
    assert created.status_code == 201 and created.json()["created"] is True
    again = client.post("/api/v1/workflow-definitions", json=body, headers=admin)
    assert again.status_code == 200 and again.json()["created"] is False

    stored = client.get("/api/v1/workflow-definitions", headers=employee).json()
    mine = [d for d in stored if d["workflow_id"] == "WF-1901"]
    # Imported through the API it is a draft (Phase 22) until reviewed.
    assert [(d["version"], d["status"], d["executions"]) for d in mine] == [(1, "draft", 0)]
    draft_start = client.post("/api/v1/workflows/WF-1901/executions", json={"input": ADDRESS},
                              headers=employee)  # fmt: skip
    assert draft_start.status_code == 409 and "draft" in draft_start.json()["error"]["message"]
    publish(client, admin, auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)), "WF-1901", 1)
    handlers = client.get("/api/v1/workflow-definitions/handlers", headers=employee).json()
    assert "core.check" in {h["name"] for h in handlers}
    assert all("properties" in h["params_schema"] for h in handlers)

    listed = {w["workflow_id"]: w for w in client.get("/api/v1/workflows", headers=employee).json()}
    assert (listed["WF-1901"]["source"], listed["WF-0001"]["source"]) == ("stored", "code")
    detail = client.get("/api/v1/workflows/WF-1901", headers=employee).json()
    assert detail["presentation"] == {"subject_path": "input.customer_number"}
    exported = client.get("/api/v1/workflows/WF-1901/export", headers=employee).json()
    assert exported["workflow_id"] == "WF-1901" and exported["steps"][0]["params"]

    started = client.post("/api/v1/workflows/WF-1901/executions", json={"input": ADDRESS},
                          headers=employee)  # fmt: skip
    assert started.status_code == 201, started.text
    assert started.json()["subject"] == "CUS-0000042"
    assert started.json()["steps"][0]["step_name"] == "Assign case reference"
    tasks = client.get("/api/v1/workflow-tasks", headers=admin).json()["items"]
    task = next(t for t in tasks if t["execution_id"] == started.json()["id"])
    assert (task["workflow_id"], task["subject"], task["can_act"]) == (
        "WF-1901", "CUS-0000042", True)  # fmt: skip

    retired = client.post("/api/v1/workflow-definitions/WF-1901/versions/1/retire",
                          headers=admin)  # fmt: skip
    assert retired.status_code == 200 and retired.json()["status"] == "retired"
    assert retired.json()["executions"] == 1
    blocked = client.post("/api/v1/workflows/WF-1901/executions", json={"input": ADDRESS},
                          headers=employee)  # fmt: skip
    assert blocked.status_code == 409
    listed = {w["workflow_id"]: w for w in client.get("/api/v1/workflows", headers=employee).json()}
    assert listed["WF-1901"]["status"] == "retired"
    reactivated = client.post("/api/v1/workflow-definitions/WF-1901/versions/1/reactivate",
                              headers=admin)  # fmt: skip
    assert reactivated.json()["status"] == "active"
