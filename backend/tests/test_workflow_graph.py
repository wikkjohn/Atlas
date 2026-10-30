"""Phase 21: workflows as graphs — layout, labels, live metrics and test coverage — and the
editor's preview of a draft."""

import copy

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.workflows import authoring, examples, graph, registry, testing
from app.modules.workflows.definition import WorkflowDefinition
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


def test_layers_follow_the_routes_and_routes_are_labelled() -> None:
    drawn = graph.layout(WorkflowDefinition.model_validate(example("WF-1002")))
    nodes = {n.id: n for n in drawn.nodes}
    assert nodes["assign_key"].layer == 0 and nodes["assign_key"].start
    for edge in drawn.edges:
        assert not edge.back
        assert nodes[edge.source].layer < nodes[edge.target].layer, edge.route
    # Within a layer every step has its own place.
    places = [(n.layer, n.order) for n in drawn.nodes]
    assert len(places) == len(set(places))
    labels = {(e.source, e.target): e.label for e in drawn.edges}
    assert labels[("fee_approval", "charge_fee")] == "approved"
    assert labels[("fee_approval", "notify_declined")] == "rejected"
    assert labels[("charge_fee", "notify_refused")] == "on failure"
    assert labels[("route_delivery", "produce")] == "input.delivery = email"
    assert labels[("route_delivery", "fee_approval")] == "otherwise"
    assert nodes["charge_fee"].effect == "moves_money"
    assert nodes["fee_approval"].permissions == ["accounts:manage"]
    assert drawn.layers == max(n.layer for n in drawn.nodes) + 1


def test_loops_are_drawn_as_back_routes() -> None:
    drawn = graph.layout(registry.get_definition("WF-0001", 1))
    back = [(e.source, e.target) for e in drawn.edges if e.back]
    assert back == [("await_documents", "validate_application")]
    nodes = {n.id: n for n in drawn.nodes}
    for edge in drawn.edges:
        if not edge.back:
            assert nodes[edge.source].layer < nodes[edge.target].layer, edge.route


def test_metrics_and_coverage_are_laid_over_it(client: TestClient, db: Session) -> None:
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    headers = auth(admin)
    authoring.import_definition(db, example("WF-1002", as_id="WF-1902"), admin.id)
    before = client.get("/api/v1/workflows/WF-1902/graph", headers=headers).json()
    assert before["tested_at"] is None and {e["covered"] for e in before["edges"]} == {None}
    assert {n["runs"] for n in before["nodes"]} == {0}

    report, run = testing.run_stored(db, "WF-1902", 1, admin.id)
    run.uncovered = [*run.uncovered, {"route": before["edges"][0]["route"], "reason": "test"}]
    db.flush()
    after = client.get("/api/v1/workflows/WF-1902/graph", headers=headers).json()
    assert after["tested_at"] is not None
    covered = {e["route"]: e["covered"] for e in after["edges"]}
    assert covered[before["edges"][0]["route"]] is False
    assert sum(covered.values()) == len(covered) - 1

    code = client.get("/api/v1/workflows/WF-0003/graph?version=2", headers=headers).json()
    assert code["version"] == 2 and code["tested_at"] is None


def test_the_editor_preview_validates_and_draws_drafts(client: TestClient, db: Session) -> None:
    admin = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))
    employee = auth(make_user(db, RoleCode.BANKING_EMPLOYEE))
    draft = example("WF-1002", as_id="WF-1906")
    url = "/api/v1/workflow-definitions/preview"
    assert client.post(url, json={"definition": draft}, headers=employee).status_code == 403
    clean = client.post(url, json={"definition": draft}, headers=admin).json()
    assert clean["report"]["valid"] and len(clean["graph"]["nodes"]) == len(draft["steps"])

    broken = copy.deepcopy(draft)
    broken["steps"][0]["next"] = "nowhere"
    shown = client.post(url, json={"definition": broken}, headers=admin).json()
    assert not shown["report"]["valid"]
    assert shown["report"]["errors"][0]["location"] == "steps.assign_key"
    # Still drawn (without the route to a missing step), so the editor can show where.
    assert shown["graph"] is not None
    assert all(e["target"] != "nowhere" for e in shown["graph"]["edges"])

    unparseable = client.post(url, json={"definition": {"steps": "?"}}, headers=admin).json()
    assert unparseable["graph"] is None and unparseable["report"]["errors"]
