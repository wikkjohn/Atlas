"""Phase 59: IT operations — applications, incidents and change management."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError
from app.core.permissions import RoleCode
from app.modules.itops import service as itops
from tests.factories import auth, make_org_tree, make_user

NOW = datetime(2041, 3, 5, 9, 0, tzinfo=UTC)  # a Tuesday, well clear of the month-end freeze


def _apps(db: Session):
    tree = make_org_tree(db)
    dept = tree.us_onboarding.id
    return (itops.register_application(db, name="Core Ledger", description="", tier=1,
                                       department_id=dept, actor_id=None),
            itops.register_application(db, name="Loan Desk", description="", tier=2,
                                       department_id=dept, actor_id=None),
            itops.register_application(db, name="Intranet", description="", tier=3,
                                       department_id=dept, actor_id=None))  # fmt: skip


def test_priorities_targets_and_the_incident_lifecycle(db: Session) -> None:
    core, desk, _ = _apps(db)
    engineer = make_user(db, RoleCode.BANKING_EMPLOYEE)
    manager = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    assert [itops.priority(i, u) for i, u in [("high", "high"), ("high", "medium"),
            ("medium", "high"), ("medium", "medium"), ("low", "high"), ("medium", "low"),
            ("low", "low")]] == [1, 2, 2, 3, 3, 4, 4]  # fmt: skip
    with pytest.raises(BusinessRuleViolation, match="Say what"):
        itops.open_incident(db, core, "x", "high", "high", engineer.id, now=NOW)
    p1 = itops.open_incident(db, core, "Ledger postings failing", "high", "high", engineer.id,
                             now=NOW)  # fmt: skip
    assert p1.incident_number.startswith("INC-") and p1.priority == 1
    assert p1.respond_by == NOW + timedelta(minutes=15)
    assert p1.resolve_by == NOW + timedelta(hours=4)
    with pytest.raises(ConflictError, match="acknowledge"):
        itops.resolve(db, p1, "Restarted the posting service.", engineer.id, now=NOW)
    # Acknowledged after 20 minutes: the response target was missed.
    itops.acknowledge(db, p1, engineer.id, NOW + timedelta(minutes=20))
    assert p1.status == "acknowledged" and p1.response_breached
    with pytest.raises(BusinessRuleViolation, match="how"):
        itops.resolve(db, p1, "fixed", engineer.id, now=NOW + timedelta(hours=1))
    itops.resolve(db, p1, "Restarted the posting service.", engineer.id,
                  now=NOW + timedelta(hours=1))  # fmt: skip
    assert p1.status == "resolved" and not p1.resolution_breached
    # A P1 closes with a post-incident review, by someone other than whoever resolved it.
    with pytest.raises(BusinessRuleViolation, match="review") as refused:
        itops.close(db, p1, manager.id)
    assert refused.value.details["rule"] == "review_required"
    review = "Root cause: a full disk on the posting host; alerting added."
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        itops.close(db, p1, engineer.id, review)
    itops.close(db, p1, manager.id, review)
    assert p1.status == "closed" and p1.review == review

    # A P4 closes without a review; the sweep marks what is past its targets.
    p4 = itops.open_incident(db, desk, "Report export slow", "low", "low", engineer.id, now=NOW)
    assert p4.priority == 4 and p4.resolve_by == NOW + timedelta(hours=120)
    p3 = itops.open_incident(db, desk, "Screen misaligned", "medium", "medium", engineer.id,
                             now=NOW)  # fmt: skip
    swept = itops.sla_sweep(db, NOW + timedelta(hours=5))
    assert swept == {"swept_at": (NOW + timedelta(hours=5)).isoformat(),
                     "response_breaches": 1, "resolution_breaches": 0}  # fmt: skip
    assert p3.response_breached and not p4.response_breached
    itops.acknowledge(db, p4, engineer.id, NOW + timedelta(hours=1))
    itops.resolve(db, p4, "Added an index to the export query.", engineer.id,
                  now=NOW + timedelta(hours=2))  # fmt: skip
    itops.close(db, p4, engineer.id)
    assert p4.status == "closed" and p4.review is None


def test_change_risk_approval_freeze_and_conflicts(db: Session) -> None:
    core, desk, intranet = _apps(db)
    engineer = make_user(db, RoleCode.BANKING_EMPLOYEE)
    manager = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    plan = "Redeploy the previous release."
    start = NOW + timedelta(days=2)

    def raise_(app, kind="normal", backout=plan, at=start, hours=2, incident=None):
        return itops.raise_change(db, app, title="Upgrade the driver", kind=kind,
                                  backout_plan=backout, planned_start=at,
                                  planned_end=at + timedelta(hours=hours),
                                  requested_by=engineer.id, incident=incident,
                                  now=NOW)  # fmt: skip

    assert itops.change_risk("standard", 2, plan) == "low"
    assert itops.change_risk("normal", 1, plan) == "high"
    assert itops.change_risk("normal", 3, plan) == "low"
    assert itops.change_risk("normal", 2, "") == "high"  # no backout plan
    # A standard change is pre-approved, but only when it is low risk.
    standard = raise_(intranet, "standard")
    assert standard.status == "approved" and standard.approved_by is None
    with pytest.raises(BusinessRuleViolation, match="standard") as refused:
        raise_(desk, "standard", backout="")
    assert refused.value.details["rule"] == "not_standard"
    with pytest.raises(BusinessRuleViolation, match="past"):
        raise_(desk, at=NOW - timedelta(days=1))

    change = raise_(desk)
    assert change.change_number.startswith("CHG-") and change.risk == "medium"
    with pytest.raises(BusinessRuleViolation, match="Four-eyes"):
        itops.decide_change(db, change, engineer.id, True)
    itops.decide_change(db, change, manager.id, True)
    assert change.status == "approved"
    # An overlapping change on the same application cannot be approved.
    clash = raise_(desk, at=start + timedelta(hours=1))
    with pytest.raises(BusinessRuleViolation, match="already approved") as refused:
        itops.decide_change(db, clash, manager.id, True)
    assert refused.value.details["rule"] == "window_conflict"
    itops.decide_change(db, clash, manager.id, False)
    assert clash.status == "rejected"

    # Tier 1: an executive approves, and nothing but an emergency goes in at month end.
    tier1 = raise_(core)
    with pytest.raises(BusinessRuleViolation, match="executive") as refused:
        itops.decide_change(db, tier1, manager.id, True)
    assert refused.value.details["rule"] == "needs_cab"
    itops.decide_change(db, tier1, executive.id, True, executive=True)
    month_end = datetime(2041, 3, 29, 22, 0, tzinfo=UTC)
    with pytest.raises(BusinessRuleViolation, match="frozen") as refused:
        raise_(core, at=month_end)
    assert refused.value.details["rule"] == "change_freeze"
    raise_(desk, at=month_end)  # tier 2 is never frozen
    with pytest.raises(BusinessRuleViolation, match="P1 or P2") as refused:
        raise_(core, "emergency", at=month_end)
    assert refused.value.details["rule"] == "emergency_needs_incident"
    p3 = itops.open_incident(db, core, "Slow statements", "medium", "medium", engineer.id,
                             now=NOW)  # fmt: skip
    with pytest.raises(BusinessRuleViolation, match="P1 or P2"):
        raise_(core, "emergency", at=month_end, incident=p3)
    p1 = itops.open_incident(db, core, "Ledger down", "high", "high", engineer.id, now=NOW)
    emergency = raise_(core, "emergency", at=month_end, incident=p1)
    assert emergency.risk == "high" and emergency.status == "requested"


def test_a_failed_change_opens_an_incident(db: Session) -> None:
    core, desk, _ = _apps(db)
    engineer = make_user(db, RoleCode.BANKING_EMPLOYEE)
    manager = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    change = itops.raise_change(db, desk, title="Patch the loan desk", kind="normal",
                                backout_plan="Roll back the patch.",
                                planned_start=NOW + timedelta(days=1),
                                planned_end=NOW + timedelta(days=1, hours=1),
                                requested_by=engineer.id, now=NOW)  # fmt: skip
    with pytest.raises(ConflictError):
        itops.implement(db, change, engineer.id, True)
    itops.decide_change(db, change, manager.id, True)
    _, incident = itops.implement(db, change, engineer.id, False, NOW + timedelta(days=1))
    assert change.status == "failed" and incident is not None
    assert incident.change_id == change.id and incident.application_id == desk.id
    assert (incident.impact, incident.urgency, incident.priority) == ("medium", "high", 2)
    assert incident.title.startswith(f"Failed change {change.change_number}")
    # Resolving names the change that caused it; another application's change is refused.
    other = itops.raise_change(db, core, title="Core patch", kind="emergency",
                               backout_plan="Roll back.", planned_start=NOW,
                               planned_end=NOW + timedelta(hours=1), requested_by=engineer.id,
                               incident=itops.open_incident(db, core, "Core down", "high",
                                                            "high", engineer.id, now=NOW),
                               now=NOW)  # fmt: skip
    itops.acknowledge(db, incident, engineer.id, NOW + timedelta(days=1))
    with pytest.raises(BusinessRuleViolation, match="another application"):
        itops.resolve(db, incident, "Rolled back the patch.", engineer.id, change=other)


def test_itops_api_and_permissions(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)
    engineer = make_user(db, RoleCode.BANKING_EMPLOYEE)
    manager = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    auditor = make_user(db, RoleCode.AUDITOR)
    body = {"name": "Payments Hub", "description": "Payments", "tier": 2,
            "department_id": str(tree.us_onboarding.id)}  # fmt: skip
    assert client.post("/api/v1/itops/applications", json=body,
                       headers=auth(manager)).status_code == 403  # fmt: skip
    app = client.post("/api/v1/itops/applications", json=body, headers=auth(executive))
    assert app.status_code == 201, app.text
    number = app.json()["application_number"]

    incident = client.post("/api/v1/itops/incidents", headers=auth(engineer), json={
        "application_number": number, "title": "Payments are timing out",
        "impact": "high", "urgency": "medium"})  # fmt: skip
    assert incident.status_code == 201, incident.text
    incident = incident.json()
    assert incident["priority"] == 2 and incident["application"] == "Payments Hub"
    assert client.post("/api/v1/itops/incidents", headers=auth(auditor), json={
        "application_number": number, "title": "Payments are timing out",
        "impact": "high", "urgency": "medium"}).status_code == 403  # fmt: skip
    url = f"/api/v1/itops/incidents/{incident['id']}"
    assert client.post(f"{url}/acknowledge", headers=auth(engineer)).json()["status"] == (
        "acknowledged")  # fmt: skip
    resolved = client.post(f"{url}/resolve", headers=auth(engineer),
                           json={"resolution": "Raised the connection pool size."})  # fmt: skip
    assert resolved.json()["status"] == "resolved"
    assert client.post(f"{url}/close", headers=auth(engineer), json={}).status_code == 403
    assert client.post(f"{url}/close", headers=auth(manager), json={}).json()["status"] == (
        "closed")  # fmt: skip

    start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=3)
    while start.day >= 26 or start.day <= 2:  # keep clear of the freeze, whatever today is
        start += timedelta(days=1)
    change = client.post("/api/v1/itops/changes", headers=auth(engineer), json={
        "application_number": number, "title": "Raise the pool size", "kind": "normal",
        "backout_plan": "Restore the previous configuration.",
        "planned_start": start.isoformat(),
        "planned_end": (start + timedelta(hours=1)).isoformat()})  # fmt: skip
    assert change.status_code == 201, change.text
    change = change.json()
    assert change["risk"] == "medium" and not change["needs_cab"]
    curl = f"/api/v1/itops/changes/{change['id']}"
    refused = client.post(f"{curl}/approve", headers=auth(engineer))
    assert refused.status_code == 403
    assert client.post(f"{curl}/approve", headers=auth(manager)).json()["status"] == "approved"
    failed = client.post(f"{curl}/implement", headers=auth(engineer), json={"success": False})
    assert failed.json()["status"] == "failed"
    listed = client.get("/api/v1/itops/incidents?status=open", headers=auth(auditor)).json()
    assert any(i["change_number"] == change["change_number"] for i in listed["items"])
    counts = client.get("/api/v1/itops/summary/counts", headers=auth(auditor)).json()
    assert counts["incidents_open"] >= 1 and counts["changes_failed_30d"] >= 1
    apps = client.get("/api/v1/itops/applications?q=Payments Hub",
                      headers=auth(auditor)).json()["items"]  # fmt: skip
    assert next(a for a in apps if a["application_number"] == number)["open_incidents"] == 1
