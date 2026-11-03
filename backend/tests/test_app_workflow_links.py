"""Phase 65: the application ↔ workflow dependency graph and what an outage stops."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import RoleCode
from app.modules.itops import estate, links
from app.modules.itops import service as itops
from app.modules.itops.models import Application
from app.modules.workflows.models import WorkflowDefinitionRecord
from tests.factories import auth, make_org_tree, make_user


def _workflow(db: Session, workflow_id: str, owner: str, *handlers: str,
              version: int = 1, status: str = "active") -> None:  # fmt: skip
    steps = [{"id": f"s{i}", "name": f"Step {i}", "type": "service_task", "handler": h}
             for i, h in enumerate(handlers, 1)]  # fmt: skip
    db.add(WorkflowDefinitionRecord(
        workflow_id=workflow_id, version=version, name=f"Workflow {workflow_id}",
        definition={"workflow_id": workflow_id, "business_owner": owner, "steps": steps},
        content_hash=f"{workflow_id}-{version}".ljust(64, "0"), source="stored",
        status=status))  # fmt: skip
    db.flush()


def _app(db: Session, name: str) -> Application:
    return db.execute(select(Application).where(Application.name == name)).scalar_one()


def _setup(db: Session) -> None:
    make_org_tree(db)
    itops.ensure_applications(db)
    _workflow(db, "WF-9901", "Retail Banking", "accounts.lookup", "core.check",
              "compliance.screen_customer")  # fmt: skip
    _workflow(db, "WF-9902", "Retail Lending", "lending.loan_profile")
    # Only the latest active version counts: version 2 calls cards, version 1 treasury.
    _workflow(db, "WF-9903", "Cards", "treasury.place")
    _workflow(db, "WF-9903", "Cards", "cards.block", version=2)
    _workflow(db, "WF-9904", "Cards", "cards.block", status="retired")


def test_steps_call_the_core_systems_their_handlers_belong_to(db: Session) -> None:
    _setup(db)
    # Phase 65 gave every department with workflows a core system: 25 in all.
    assert _app(db, "Treasury Dealing System").tier == 1
    calls = links.workflow_applications(db, "WF-9901")
    assert {a["name"]: a["steps"] for a in calls["applications"]} == {
        "Core Banking Ledger": ["Step 1"], "Sanctions Screening": ["Step 3"],
        "AML Monitoring": ["Step 3"]}  # fmt: skip
    assert [a["name"] for a in links.workflow_applications(db, "WF-9903")["applications"]] \
        == ["Card Authorisation"]  # fmt: skip
    assert links.workflow_applications(db, "WF-9904")["name"] is None  # retired

    ledger = links.application_workflows(db, _app(db, "Core Banking Ledger"))
    ours = [w for w in ledger["workflows"] if w["workflow_id"].startswith("WF-99")]
    assert [w["workflow_id"] for w in ours] == ["WF-9901", "WF-9902"]


def test_an_outage_stops_the_workflows_that_call_what_fails(db: Session) -> None:
    _setup(db)
    # Sanctions Screening down: the Payments Gateway waits on it, and Online Banking,
    # Treasury and Procurement on the gateway. Only WF-9901 screens; loans and cards go on.
    screening = links.outage_impact(db, _app(db, "Sanctions Screening"))
    ours = {w["workflow_id"]: w for w in screening["workflows"]
            if w["workflow_id"].startswith("WF-99")}  # fmt: skip
    assert list(ours) == ["WF-9901"]
    assert ours["WF-9901"]["steps"] == ["Step 3"]
    assert ours["WF-9901"]["via"] == [_app(db, "Sanctions Screening").application_number]
    assert screening["applications_failing"] >= 5

    # The ledger down: everything that waits on it fails, so all three workflows stop.
    ledger = links.outage_impact(db, _app(db, "Core Banking Ledger"))
    stopped = {w["workflow_id"] for w in ledger["workflows"]}
    assert {"WF-9901", "WF-9902", "WF-9903"} <= stopped
    card = next(w for w in ledger["workflows"] if w["workflow_id"] == "WF-9903")
    assert card["via"] == [_app(db, "Card Authorisation").application_number]
    assert ledger["by_department"]["Cards"] >= 1

    # The Staff Intranet stops no banking workflow (only HR and IT systems sign in with it).
    intranet = links.outage_impact(db, _app(db, "Staff Intranet"))
    assert not [w for w in intranet["workflows"] if w["workflow_id"].startswith("WF-99")]


def test_the_estate_is_wired_deterministically(db: Session) -> None:
    _setup(db)
    estate.generate_estate(db, 400, seed=7)
    first = [x for x in links.links(db) if x.workflow_id.startswith("WF-99")]
    assert first == [x for x in links.links(db) if x.workflow_id.startswith("WF-99")]
    chosen = [x for x in first if x.source == "estate"]
    # Each linked step also calls one critical estate application from its domain.
    assert len(chosen) == 4  # WF-9901's two linked steps, WF-9902's and WF-9903's
    for link in chosen:
        app = db.get(Application, link.application_id)
        assert app.generated_from and app.tier <= 2
    ledger_step = next(x for x in chosen if x.handler == "accounts.lookup")
    assert db.get(Application, ledger_step.application_id).name.startswith("Ledger ")

    wiring = links.summary(db)
    assert wiring["called_directly"] <= wiring["wired"] <= wiring["applications"]
    assert wiring["wired"] + wiring["unwired"] == wiring["applications"]
    assert wiring["workflows_linked"] >= 3


def test_the_api(client: TestClient, db: Session) -> None:
    _setup(db)
    auditor = make_user(db, RoleCode.AUDITOR)
    db.commit()
    headers = auth(auditor)
    screening = _app(db, "Sanctions Screening")
    body = client.get(f"/api/v1/itops/applications/{screening.id}/workflows",
                      headers=headers).json()  # fmt: skip
    assert "WF-9901" in [w["workflow_id"] for w in body["workflows"]]
    assert "WF-9901" in [w["workflow_id"] for w in body["outage"]["workflows"]]
    calls = client.get("/api/v1/itops/workflows/WF-9902/applications", headers=headers)
    assert [a["name"] for a in calls.json()["applications"]] == ["Core Banking Ledger",
                                                                "Loan Origination"]  # fmt: skip
    assert client.get("/api/v1/itops/workflows/WF-0000/applications",
                      headers=headers).status_code == 404  # fmt: skip
    wiring = client.get("/api/v1/itops/estate/wiring", headers=headers).json()
    assert wiring["workflows_linked"] >= 3
