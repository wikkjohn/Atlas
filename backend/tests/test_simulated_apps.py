"""Phase 64: the generic simulated application — contract, latency, failures and outages."""

import random
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation
from app.core.permissions import RoleCode
from app.modules.itops import estate, simulated
from app.modules.itops import service as itops
from app.modules.itops.models import Incident
from tests.factories import auth, make_org_tree, make_user


def _apps(db: Session, *names_tiers):
    tree = make_org_tree(db)
    return [itops.register_application(db, name=name, description="", tier=tier,
                                       department_id=tree.us_onboarding.id, actor_id=None)
            for name, tier in names_tiers]  # fmt: skip


def test_contract_latency_and_failures_are_deterministic(db: Session) -> None:
    ledger, portal = _apps(db, ("Ledger", 1), ("Portal", 3))
    estate.set_profile(db, ledger, owner_username=None, technology="cobol-mainframe",
                       hosting="on_premise", vendor=None, actor_id=None)  # fmt: skip
    estate.set_profile(db, portal, owner_username=None, technology="low-code",
                       hosting="saas", vendor="Demo", actor_id=None)  # fmt: skip
    estate.add_dependency(db, portal, ledger, "api", None)

    terms = simulated.contract(db, ledger)
    assert terms.median_ms == {"read": 40.0, "write": 60.0}
    assert terms.p95_ms["read"] == pytest.approx(40 * 2.277, abs=0.2)
    assert terms.error_rate == 0.0005  # tier 1, mainframe
    # The portal: low-code (200 ms) on SaaS (x1.5), plus 20 ms for its one API dependency.
    portal_terms = simulated.contract(db, portal)
    assert portal_terms.median_ms["read"] == 320.0 and portal_terms.sync_dependencies == 1
    assert portal_terms.error_rate == 0.02

    first = simulated.sample(db, portal, "read", 2000, seed=7)
    assert first == simulated.sample(db, portal, "read", 2000, seed=7)
    assert first != simulated.sample(db, portal, "read", 2000, seed=8)
    assert 250 < first["p50_ms"] < 400 and first["p95_ms"] > first["p50_ms"]
    assert 15 <= first["errors"].get("error", 0) <= 70  # about 2 % of 2,000
    assert first["state"] == {"status": "up", "cause": None, "path": []}
    with pytest.raises(BusinessRuleViolation) as refused:
        simulated.sample(db, portal, "delete", 1, seed=1)
    assert refused.value.details["rule"] == "operation_invalid"


def test_outages_fail_callers_through_synchronous_links_only(db: Session) -> None:
    ledger, gateway, portal, reports, other = _apps(
        db, ("Ledger", 1), ("Gateway", 1), ("Portal", 2), ("Reports", 3), ("Other", 3)
    )
    sre = make_user(db, RoleCode.BANKING_EMPLOYEE).id
    estate.add_dependency(db, gateway, ledger, "api", None)
    estate.add_dependency(db, portal, gateway, "auth", None)
    estate.add_dependency(db, reports, ledger, "batch", None)
    now = datetime(2026, 11, 3, 10, tzinfo=UTC)
    outage = simulated.declare_outage(db, ledger, "down", "Storage array failed", sre, now=now)
    assert outage.outage_number.startswith("OUT-") and outage.ends_at is None
    # A started outage opens a high-urgency incident; a tier-1 application's is a P1.
    assert db.get(Incident, outage.incident_id).priority == 1

    view = simulated.Estate(db, now + timedelta(minutes=5))
    assert view.state(ledger) == simulated.State("down", ledger.application_number,
                                                 (ledger.application_number,))  # fmt: skip
    portal_state = view.state(portal)
    assert portal_state.status == "down" and portal_state.path == (
        portal.application_number,
        gateway.application_number,
        ledger.application_number,
    )
    assert view.state(reports).status == "up"  # a batch feed does not fail a call
    assert view.state(other).status == "up"
    rng = random.Random(1)
    calls = [view.call(portal, "write", rng) for _ in range(50)]
    assert all(not c.ok and c.error == "outage" and c.cause == ledger.application_number
               for c in calls)  # fmt: skip
    # Before it started, all was well.
    assert simulated.Estate(db, now - timedelta(minutes=1)).state(portal).status == "up"

    with pytest.raises(BusinessRuleViolation) as refused:
        simulated.declare_outage(db, ledger, "degraded", "Slow disks again", sre,
                                 now=now + timedelta(minutes=1))  # fmt: skip
    assert refused.value.details["rule"] == "outage_overlap"
    simulated.end_outage(db, outage, sre, now=now + timedelta(hours=1))
    assert simulated.Estate(db, now + timedelta(hours=2)).state(portal).status == "up"
    with pytest.raises(BusinessRuleViolation) as refused:
        simulated.end_outage(db, outage, sre, now=now + timedelta(hours=3))
    assert refused.value.details["rule"] == "outage_not_active"

    # A degraded gateway slows the portal and fails more of its calls.
    later = now + timedelta(days=1)
    simulated.declare_outage(db, gateway, "degraded", "Connection pool exhausted", sre,
                             now=later, ends_at=later + timedelta(hours=2))  # fmt: skip
    slow = simulated.sample(db, portal, "read", 1000, seed=3, at=later + timedelta(minutes=1))
    fast = simulated.sample(db, portal, "read", 1000, seed=3, at=later + timedelta(hours=3))
    assert slow["state"]["status"] == "degraded" and fast["state"]["status"] == "up"
    assert slow["p50_ms"] == pytest.approx(fast["p50_ms"] * 4, rel=0.01)
    assert slow["failed"] > fast["failed"] + 50

    # A planned outage opens no incident until it happens.
    planned = simulated.declare_outage(
        db,
        reports,
        "down",
        "Planned upgrade",
        None,
        now=now,
        starts_at=now + timedelta(days=7),
        ends_at=now + timedelta(days=7, hours=4),
    )
    assert planned.incident_id is None
    for kind, reason, rule in (("gone", "Storage array", "kind_invalid"),
                               ("down", "x", "reason_required")):  # fmt: skip
        with pytest.raises(BusinessRuleViolation) as refused:
            simulated.declare_outage(db, other, kind, reason, sre, now=now)
        assert refused.value.details["rule"] == rule
    with pytest.raises(BusinessRuleViolation) as refused:
        simulated.declare_outage(db, other, "down", "Backwards window", sre, now=now,
                                 starts_at=now, ends_at=now - timedelta(hours=1))  # fmt: skip
    assert refused.value.details["rule"] == "window_invalid"


def test_outage_and_call_api(client: TestClient, db: Session) -> None:
    ledger, portal = _apps(db, ("Ledger", 1), ("Portal", 2))
    estate.add_dependency(db, portal, ledger, "api", None)
    engineer = make_user(db, RoleCode.BANKING_EMPLOYEE)
    auditor = make_user(db, RoleCode.AUDITOR)
    db.commit()
    headers = auth(engineer)

    contract = client.get(f"/api/v1/itops/applications/{portal.id}/contract", headers=headers)
    assert contract.status_code == 200, contract.text
    body = contract.json()
    assert body["sync_dependencies"] == 1 and body["state"]["status"] == "up"
    assert body["blast_radius"] == 0

    declared = client.post("/api/v1/itops/outages", headers=headers, json={
        "application_number": ledger.application_number, "kind": "down",
        "reason": "Storage array failed"})  # fmt: skip
    assert declared.status_code == 201, declared.text
    outage = declared.json()
    assert outage["status"] == "in_force" and outage["incident_number"].startswith("INC-")
    assert outage["failing"] == 1  # the portal waits on the ledger

    calls = client.post(f"/api/v1/itops/applications/{portal.id}/calls", headers=headers,
                        json={"operation": "read", "count": 20, "seed": 1})  # fmt: skip
    assert calls.status_code == 200, calls.text
    assert calls.json()["failed"] == 20 and calls.json()["errors"] == {"outage": 20}
    assert calls.json()["state"]["cause"] == ledger.application_number

    listed = client.get("/api/v1/itops/outages?active=true", headers=auth(auditor))
    assert [o["outage_number"] for o in listed.json()["items"]] == [outage["outage_number"]]
    # The auditor reads but does not declare or end outages.
    assert client.post(f"/api/v1/itops/outages/{outage['id']}/end",
                       headers=auth(auditor)).status_code == 403  # fmt: skip
    ended = client.post(f"/api/v1/itops/outages/{outage['id']}/end", headers=headers)
    assert ended.status_code == 200 and ended.json()["status"] == "ended"
    assert client.get("/api/v1/itops/outages?active=true",
                      headers=headers).json()["items"] == []  # fmt: skip
