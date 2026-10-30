"""Phase 20: path tests generated from stored definitions — planning, synthesis, running,
coverage, and that they find real defects."""

import copy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.workflows import authoring, examples, store, templates, testing
from app.modules.workflows.definition import WorkflowDefinition
from app.modules.workflows.models import WorkflowTestRun
from app.modules.workflows.testing import Route, plan_for, routes, synthesize
from tests.factories import auth, make_user


def example(workflow_id: str, version: int = 1, as_id: str | None = None) -> dict:
    (found,) = [
        d
        for d in examples.documents()
        if (d["workflow_id"], d["version"]) == (workflow_id, version)
    ]
    doc = copy.deepcopy(found)
    if as_id:
        doc["workflow_id"] = as_id
    return doc


def steps(doc: dict) -> dict[str, dict]:
    return {s["id"]: s for s in doc["steps"]}


def definition(doc: dict) -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(doc)


@pytest.fixture
def admin(db: Session):
    return make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)


def test_routes_are_planned_from_their_conditions() -> None:
    d = definition(example("WF-1001"))
    path = testing._path_to(d, "route_by_reason")
    # transition[1] (corrections): reason is "correction" and not the earlier "fraud".
    plan = plan_for(d, [*path, Route("route_by_reason", "record_change", "transition", 1)], set())
    assert plan.inputs["reason"] == "correction"
    # The fallback: neither fraud nor correction.
    fallback = plan_for(d, [*path, Route("route_by_reason", "colleague_review", "next")], set())
    assert fallback.inputs["reason"] == "moved"
    # The country check on the way must pass: a country the bank serves.
    assert plan.inputs["country_code"] in {"US", "GB", "DE", "SG", "JP"}
    # An approval's reject route is a decision; its on_failure route an injected failure.
    review = testing._path_to(d, "colleague_review")
    reject = plan_for(d, [*review, Route("colleague_review", "notify_declined", "next")], set())
    assert reject.decisions == {"colleague_review": "reject"}
    failing = plan_for(
        d,
        [
            Route("assign_key", "check_country", "next"),
            Route("check_country", "notify_unsupported", "failure"),
        ],
        set(),
    )
    assert failing.fail == {"check_country"}
    assert len(routes(d)) == 14


def test_inputs_are_synthesised_from_the_schema() -> None:
    d = definition(example("WF-1002"))
    payload, problems = synthesize(d, testing.Plan(), {})
    assert problems == []
    assert payload["delivery"] == "email" and payload["months"] == 1
    assert payload["customer_number"] == "CUS-0000000"  # from its pattern
    assert testing._from_pattern(r"^[A-Z]{2}$") == "AA"
    assert testing._from_pattern(r"^(a|b)$") is None  # too complex: needs `examples`
    hard = example("WF-1002")
    hard["input_schema"]["properties"]["account_number"] = {"type": "string", "pattern": "^(x|y)+$"}
    _, problems = synthesize(definition(hard), testing.Plan(), {})
    assert any("account_number" in p for p in problems)
    # Fields that handlers look up are records the tests create.
    assert testing.fixture_needs(d) == {
        "input.customer_number": "customer.customer_number",
        "input.account_number": "account.account_number",
    }


def test_a_stored_workflow_is_fully_covered_and_passes(db: Session, admin) -> None:
    record, _, _ = authoring.import_definition(db, example("WF-1002", as_id="WF-1902"), admin.id)
    report = testing.run_path_tests(db, store.parsed(record))
    assert report.passed and report.count("skipped") == 0, [
        (r.name, r.detail) for r in report.results if r.status != "passed"
    ]
    assert (report.step_coverage, report.route_coverage, report.uncovered) == (1.0, 1.0, [])
    by_name = {r.name: r for r in report.results}
    fee = by_name["route fee_approval → charge_fee (transition[0])"]
    assert "charge_fee" in fee.visited and fee.outcome == "sent"
    refusals = by_name["approval fee_approval: refusals"].detail
    assert "refused the initiator (four-eyes)" in refusals
    assert "refused a person without its permissions" in refusals
    failure = by_name["route charge_fee → notify_refused (failure)"]
    assert failure.outcome == "refused"
    # Nothing a case did survives it.
    from app.modules.workflows.models import WorkflowExecution

    assert (
        db.execute(
            select(WorkflowExecution).where(WorkflowExecution.workflow_id == "WF-1902")
        ).first()
        is None
    )


def test_generated_variants_are_tested_like_any_stored_workflow(db: Session, admin) -> None:
    template_doc = examples.templates()[0]
    doc = {**copy.deepcopy(template_doc), "template_id": "TPL-TEST-PATHS", "id_range": [7100, 7109]}
    templates.import_template(db, doc, admin.id)
    params = {
        "country_code": "JP",
        "account_type": "savings",
        "fee": 5,
        "approval_permission": "accounts:approve",
        "screen_customers": True,
    }
    templates.generate(db, "TPL-TEST-PATHS", [params], admin.id)
    report, run = testing.run_stored(db, "WF-7100", 1, admin.id)
    assert report.passed and report.route_coverage == 1.0
    assert run.passed == len(report.results) and run.failed == 0
    # The product check is satisfied by steering the looked-up account's type.
    assert any("find_account.account_type='savings'" in m for r in report.results for m in r.mocked)


def test_it_finds_an_input_that_matches_no_route(db: Session, admin) -> None:
    doc = example("WF-1001", as_id="WF-1903")
    route = steps(doc)["route_by_reason"]
    route["transitions"].append(
        {"to": "colleague_review", "when": {"path": "input.reason", "op": "eq", "value": "moved"}}
    )
    del route["next"]
    doc["input_schema"]["properties"]["reason"]["enum"].append("deceased")  # a new reason
    record, _, _ = authoring.import_definition(db, doc, admin.id)  # a warning, not an error
    report = testing.run_path_tests(db, store.parsed(record))
    probe = next(r for r in report.results if r.name == "no-route probe at route_by_reason")
    assert probe.status == "failed" and "no_route" in probe.detail
    assert not report.passed


def test_it_finds_a_step_that_reads_the_wrong_record(db: Session, admin) -> None:
    doc = example("WF-1001", 2, as_id="WF-1904")
    # A typo-like defect validation cannot see: a name where a customer id belongs.
    steps(doc)["notify_updated"]["params"]["customer_id_path"] = "find_customer.name"
    record, _, _ = authoring.import_definition(db, doc, admin.id)
    report = testing.run_path_tests(db, store.parsed(record))
    failures = [r for r in report.results if r.status == "failed"]
    assert failures and all("notify_updated" in r.visited for r in failures)
    assert any("failed outside a failure step" in r.detail for r in failures)
    assert report.route_coverage < 1.0


def test_runs_are_recorded_and_served(client: TestClient, db: Session, admin) -> None:
    authoring.import_definition(db, example("WF-1001", as_id="WF-1905"), admin.id)
    headers = auth(admin)
    employee = auth(make_user(db, RoleCode.BANKING_EMPLOYEE))
    assert (
        client.post(
            "/api/v1/workflow-definitions/WF-1905/versions/1/tests", headers=employee
        ).status_code
        == 403
    )
    run = client.post("/api/v1/workflow-definitions/WF-1905/versions/1/tests", headers=headers)
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["failed"] == 0 and body["passed"] == len(body["cases"])
    assert body["step_coverage"] == 1.0 and body["route_coverage"] == 1.0
    assert {c["kind"] for c in body["cases"]} == {"happy", "route", "approval"}
    listed = client.get("/api/v1/workflow-definitions/WF-1905/tests", headers=employee).json()
    assert [r["id"] for r in listed] == [body["id"]]
    detail = client.get("/api/v1/workflows/WF-1905", headers=employee).json()
    assert detail["last_test"]["passed"] == body["passed"]
    assert db.execute(
        select(WorkflowTestRun).where(WorkflowTestRun.workflow_id == "WF-1905")
    ).scalar_one()
    assert (
        client.post(
            "/api/v1/workflow-definitions/WF-0001/versions/1/tests", headers=headers
        ).status_code
        == 404
    )
