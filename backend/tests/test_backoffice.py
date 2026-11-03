"""Phase 61: thin departments — the registry, the request lifecycle, the API, the generated
workflows and the generic workload."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.permissions import RoleCode
from app.modules.backoffice import registry
from app.modules.backoffice import service as backoffice
from app.modules.backoffice.workflows import documents
from app.modules.workflows import authoring, validation
from app.simulation.models import SimulationRun, SimulationStatus
from app.simulation.runner import create_run, execute_run
from app.simulation.scenarios import get_scenario
from app.simulation.workloads import WORKLOADS
from tests.factories import auth, make_org_tree, make_user

NOW = datetime(2041, 3, 5, 9, 0, tzinfo=UTC)


def test_the_registry_and_its_generated_workflows() -> None:
    assert len(registry.DEPARTMENTS) == 17
    codes = [d.code for d in registry.DEPARTMENTS]
    assert len(set(codes)) == 17 and {"legal", "internal_audit", "marketing",
                                      "facilities"} <= set(codes)  # fmt: skip
    for department in registry.DEPARTMENTS:
        first = department.processes[0]
        # The workload drives each department's first process: it needs an amount and an
        # approval, with a budget below the executive threshold.
        assert first.approval and first.amount_label
        assert first.budget_usd * 2.4 < first.major_above_usd
        assert len({p.code for p in department.processes}) == 3
    docs = documents()
    ids = [d["workflow_id"] for d in docs]
    assert len(ids) == 51 and len(set(ids)) == 51
    assert ids[0] == "WF-1100" and ids[-1] == "WF-1150"
    assert registry.by_workflow("WF-1100") == (registry.BY_CODE["legal"],
                                               registry.BY_CODE["legal"].processes[0])  # fmt: skip
    for doc in docs:
        report = validation.validate(None, doc)
        assert report.valid, (doc["workflow_id"], report.errors)
        assert doc["catalogue"]["department"] == registry.by_workflow(doc["workflow_id"])[0].name
    no_approval = next(d for d in docs if d["workflow_id"] == "WF-1102")  # legal hold
    assert [s["id"] for s in no_approval["steps"]][:2] == ["submit", "complete"]


def test_the_request_lifecycle(db: Session) -> None:
    clerk = make_user(db, RoleCode.BANKING_EMPLOYEE)
    manager = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    with pytest.raises(NotFoundError):
        backoffice.submit(db, "legal", "nothing", title="Something", amount=None,
                          requested_by=clerk.id)  # fmt: skip
    with pytest.raises(BusinessRuleViolation, match="fee estimate") as refused:
        backoffice.submit(db, "legal", "outside_counsel", title="Lease dispute", amount=None,
                          requested_by=clerk.id)  # fmt: skip
    assert refused.value.details["rule"] == "amount_required"
    with pytest.raises(BusinessRuleViolation, match="no amount"):
        backoffice.submit(db, "legal", "contract_review", title="Supplier MSA", amount=100,
                          requested_by=clerk.id)  # fmt: skip
    request = backoffice.submit(db, "legal", "outside_counsel", title="Lease dispute",
                                amount=4_000_000, requested_by=clerk.id, now=NOW)  # fmt: skip
    assert request.request_number.startswith("DR-") and request.status == "submitted"
    assert request.due_at == NOW + timedelta(hours=72)
    assert not backoffice.over_budget(request) and not backoffice.needs_executive(request)
    with pytest.raises(ConflictError):
        backoffice.complete(db, request, clerk.id)
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        backoffice.decide(db, request, clerk.id, True)
    backoffice.decide(db, request, manager.id, True, note="Use the panel firm.")
    assert request.status == "approved" and request.note == "Use the panel firm."
    # Completed after its target: a breach.
    backoffice.complete(db, request, clerk.id, NOW + timedelta(hours=80))
    assert request.status == "completed" and request.breached

    # Over budget is a judgement; above the executive threshold only an executive approves.
    big = backoffice.submit(db, "legal", "outside_counsel", title="Class action defence",
                            amount=20_000_000, requested_by=clerk.id)  # fmt: skip
    assert backoffice.over_budget(big) and backoffice.needs_executive(big)
    with pytest.raises(BusinessRuleViolation, match="executive") as refused:
        backoffice.decide(db, big, manager.id, True)
    assert refused.value.details["rule"] == "needs_executive"
    backoffice.decide(db, big, manager.id, False)
    assert big.status == "rejected"
    # A process without approval is ready to complete at once.
    hold = backoffice.submit(db, "legal", "legal_hold", title="Preserve the lease emails",
                             amount=None, requested_by=clerk.id, now=NOW)  # fmt: skip
    assert hold.status == "approved"
    backoffice.complete(db, hold, clerk.id, NOW + timedelta(hours=2))
    assert hold.status == "completed" and not hold.breached
    legal = next(d for d in backoffice.departments(db) if d["code"] == "legal")
    assert legal["counts"]["completed"] == 2 and legal["counts"]["rejected"] == 1
    assert legal["counts"]["breached"] == 1
    assert [p["workflow_id"] for p in legal["processes"]] == ["WF-1100", "WF-1101", "WF-1102"]


def test_backoffice_api_and_permissions(client: TestClient, db: Session) -> None:
    clerk = make_user(db, RoleCode.BANKING_EMPLOYEE)
    manager = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    auditor = make_user(db, RoleCode.AUDITOR)
    body = {"department": "marketing", "process": "campaign", "title": "Spring savings drive",
            "amount": 60_000_000}  # fmt: skip
    assert client.post("/api/v1/backoffice/requests", json=body,
                       headers=auth(auditor)).status_code == 403  # fmt: skip
    created = client.post("/api/v1/backoffice/requests", json=body, headers=auth(clerk))
    assert created.status_code == 201, created.text
    request = created.json()
    assert request["process_name"] == "Campaign approval" and request["needs_executive"]
    url = f"/api/v1/backoffice/requests/{request['id']}"
    assert client.post(f"{url}/approve", json={}, headers=auth(clerk)).status_code == 403
    refused = client.post(f"{url}/approve", json={}, headers=auth(manager))
    assert refused.status_code == 422
    assert refused.json()["error"]["details"]["rule"] == "needs_executive"
    approved = client.post(f"{url}/approve", json={}, headers=auth(executive))
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    done = client.post(f"{url}/complete", headers=auth(clerk))
    assert done.json()["status"] == "completed"
    listed = client.get("/api/v1/backoffice/requests?department=marketing",
                        headers=auth(auditor))  # fmt: skip
    assert listed.json()["total"] == 1
    departments = client.get("/api/v1/backoffice/departments", headers=auth(auditor)).json()
    assert len(departments) == 17
    assert next(d for d in departments if d["code"] == "marketing")["counts"]["completed"] == 1


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


def test_a_department_run(db: Session, factory) -> None:
    make_org_tree(db)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    scenario = get_scenario("dept-internal-audit")
    doc = next(d for d in documents() if d["workflow_id"] == scenario.workflow_id)
    authoring.import_definition(db, json.loads(json.dumps(doc)), admin.id)
    creator = make_user(db, RoleCode.AI_RESEARCHER)
    run = create_run(db, scenario, profile="custom", applications=30, employees=8, seed=7,
                     created_by=creator.id, mode="baseline", tool=None)  # fmt: skip
    db.commit()
    execute_run(factory, run.id)
    db.expire_all()
    run = db.get(SimulationRun, run.id)
    assert run.status == SimulationStatus.COMPLETED, run.failure_reason
    assert run.results["completed"] == 30
    controls = WORKLOADS["department_requests"].check_controls(db, run.id)
    assert controls.decisions == 30 and controls.violations == []
    by_kind = run.results["by_kind"]
    assert set(by_kind) <= {"routine", "urgent", "over_budget", "duplicate"}
    assert 0 < run.results["ground_truth"]["accuracy"] <= 1


def test_milestone_d_exit(client: TestClient, db: Session) -> None:
    """35 or more departments, each with three base processes, a simulation workload and a
    dashboard that the frontend's navigation links to."""
    import re
    from pathlib import Path

    from app.modules.backoffice.coverage import coverage

    rows = coverage()
    incomplete = [r["department"] for r in rows if not r["complete"]]
    assert len(rows) >= 35 and incomplete == []
    assert all(len(r["workflows"]) >= 3 and r["scenarios"] for r in rows)
    navigation = Path(__file__).resolve().parents[2] / "frontend/src/app/navigation.ts"
    pages = set(re.findall(r'path: "(/[a-z-]*)"', navigation.read_text()))
    assert {r["dashboard"] for r in rows} <= pages
    by_name = {r["department"]: r for r in rows}
    assert by_name["Customer Onboarding"]["workflows"] == ["WF-0001", "WF-1001", "WF-1052"]
    assert by_name["Retail Lending"]["workflows"] == ["WF-0003", "WF-1053", "WF-1054"]
    assert "WF-0004" in by_name["Collections"]["workflows"]
    auditor = make_user(db, RoleCode.AUDITOR)
    body = client.get("/api/v1/backoffice/coverage", headers=auth(auditor)).json()
    assert body["total"] == len(rows) and body["complete"] == len(rows)
