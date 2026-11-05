"""Phase 80: success thresholds per scenario — risk tiers, approved versions, resolution."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.core.permissions import RoleCode
from app.modules.experiments import thresholds
from app.modules.experiments.assumptions import SuccessThresholds
from app.modules.experiments.models import ScenarioThresholdVersion
from tests.factories import auth, make_user
from tests.test_experiments import _experiment, api, factory, lab  # noqa: F401, F811

URL = "/api/v1/scenario-thresholds"
WHY = "Leave is internal and easily corrected; friction costs more than errors."


def test_every_ai_scenario_has_a_tier_and_tiers_are_ordered(db: Session) -> None:
    rows = {r["scenario_id"]: r for r in thresholds.overview(db)}
    # Every AI scenario has a tier of its own, or its base scenario's.
    assert set(thresholds.SCENARIO_TIERS) <= set(rows)
    assert rows["domestic-payments-outage"]["risk_tier"] == "critical"
    assert rows["retail-onboarding"]["risk_tier"] == "critical"
    assert rows["leave-requests"]["risk_tier"] == "low"
    assert all(r["source"] == "tier_default" and r["version"] == 0 for r in rows.values())
    t = thresholds.TIERS
    for stricter, looser in (("critical", "high"), ("high", "medium"), ("medium", "low")):
        assert t[stricter].max_false_approval_rate < t[looser].max_false_approval_rate
        assert t[stricter].max_accuracy_drop <= t[looser].max_accuracy_drop
    assert t["medium"] == SuccessThresholds()  # the bank's former single standard
    # A scenario without a tier gets the default tier.
    values, source = thresholds.resolve(db, "unclassified")
    assert source["risk_tier"] == "medium" and values == SuccessThresholds()


def test_thresholds_take_effect_only_when_someone_else_approves(api: TestClient, db: Session):  # noqa: F811
    researcher = make_user(db, RoleCode.AI_RESEARCHER)
    executive = make_user(db, RoleCode.GLOBAL_EXECUTIVE)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    db.commit()
    looser = {**thresholds.TIERS["low"].model_dump(), "min_improvement": 0.1}
    body = {"scenario_id": "leave-requests", "risk_tier": "low", "rationale": WHY,
            "thresholds": looser}  # fmt: skip
    proposed = api.post(URL, json=body, headers=auth(researcher))
    assert proposed.status_code == 201, proposed.text
    v1 = proposed.json()
    assert (v1["version"], v1["status"], v1["proposed_by_username"]) == (
        1, "proposed", researcher.username
    )  # fmt: skip
    # Not yet in force; a second proposal waits for the first.
    assert thresholds.resolve(db, "leave-requests")[1]["source"] == "tier_default"
    assert api.post(URL, json=body, headers=auth(researcher)).status_code == 409
    # The researcher may not approve; an approver may not approve their own proposal.
    approve = f"{URL}/{v1['id']}/approve"
    assert api.post(approve, json={}, headers=auth(researcher)).status_code == 403
    own = api.post(URL, json={**body, "scenario_id": "change-approvals"}, headers=auth(admin))
    refused = api.post(f"{URL}/{own.json()['id']}/approve", json={}, headers=auth(admin))
    assert refused.status_code == 422 and "second person" in refused.text

    done = api.post(approve, json={"note": "Agreed."}, headers=auth(executive))
    assert done.status_code == 200 and done.json()["status"] == "active"
    values, source = thresholds.resolve(db, "leave-requests")
    assert (source["source"], source["version"], values.min_improvement) == ("scenario", 1, 0.1)
    assert api.post(approve, json={}, headers=auth(executive)).status_code == 409  # decided

    # Version 2 supersedes version 1; a rejection needs a reason and changes nothing.
    v2 = api.post(URL, json={**body, "thresholds": None}, headers=auth(researcher)).json()
    api.post(f"{URL}/{v2['id']}/approve", json={}, headers=auth(executive))
    v3 = api.post(URL, json={**body, "risk_tier": "medium"}, headers=auth(researcher)).json()
    reject = f"{URL}/{v3['id']}/reject"
    assert api.post(reject, json={"note": ""}, headers=auth(executive)).status_code == 422
    assert api.post(reject, json={"note": "Too loose."}, headers=auth(executive)).status_code == 200
    history = api.get(f"{URL}/leave-requests/history", headers=auth(researcher)).json()
    assert [(h["version"], h["status"]) for h in history] == [
        (3, "rejected"), (2, "active"), (1, "superseded")
    ]  # fmt: skip
    assert history[1]["thresholds"] == thresholds.TIERS["low"].model_dump(mode="json")
    listed = {
        r["scenario_id"]: r for r in api.get(URL, headers=auth(researcher)).json()["scenarios"]
    }
    assert (listed["leave-requests"]["source"], listed["leave-requests"]["version"]) == (
        "scenario", 2
    )  # fmt: skip
    assert listed["change-approvals"]["pending"]["proposed_by_username"] == admin.username
    actions = db.execute(
        select(AuditEvent.action).where(AuditEvent.entity_type == "scenario_thresholds")
    ).scalars().all()  # fmt: skip
    assert actions.count("scenario_thresholds.approved") == 2
    assert actions.count("scenario_thresholds.rejected") == 1
    assert (
        api.post(URL, json={**body, "scenario_id": "nope"}, headers=auth(researcher)).status_code
        == 404
    )


def test_experiments_use_and_record_their_scenarios_thresholds(
    api: TestClient,  # noqa: F811
    db: Session,
    lab: dict,  # noqa: F811
) -> None:
    # No version stored: retail onboarding is critical, so the tier's thresholds apply.
    first = _experiment(api, lab)
    config = first["configuration"]
    assert config["thresholds"] == thresholds.TIERS["critical"].model_dump(mode="json")
    assert config["thresholds_source"]["source"] == "tier_default"
    report = api.get(f"/api/v1/experiments/{first['id']}/report", headers=lab).text
    assert "defaults for retail-onboarding's risk tier, critical" in report
    # Thresholds given in the request win, and say so.
    given = _experiment(api, lab, thresholds={"max_false_approval_rate": 0.2}, seed=18)
    assert given["configuration"]["thresholds"]["max_false_approval_rate"] == 0.2
    assert given["configuration"]["thresholds_source"] == {
        "source": "request", "scenario_id": "retail-onboarding"
    }  # fmt: skip

    # An approved version that no experiment can meet: the stored verdict stays, the
    # re-assessment under the thresholds in force now fails on improvement.
    impossible = SuccessThresholds(min_improvement=1.0)
    record = thresholds.propose(
        db, scenario_id="retail-onboarding", risk_tier="critical", thresholds=impossible,
        rationale="Demand a 100 % improvement, to test the re-assessment.",
        actor_id=make_user(db, RoleCode.AI_RESEARCHER).id,
    )  # fmt: skip
    thresholds.approve(db, record.id, make_user(db, RoleCode.GLOBAL_EXECUTIVE).id)
    db.commit()
    again = api.get(
        f"/api/v1/experiments/{first['id']}/under-scenario-thresholds", headers=lab
    ).json()
    assert again["stored_thresholds"] == config["thresholds"]
    assert again["thresholds_source"]["source"] == "scenario"
    assert again["verdict"] == "not_successful"
    assert "measurable_improvement" in again["failed_criteria"]
    assert again["changed"] == (again["stored_verdict"] == "successful")
    stored = api.get(f"/api/v1/experiments/{first['id']}", headers=lab).json()
    assert stored["evaluation"]["verdict"] == again["stored_verdict"]  # nothing rewritten
    # The next experiment is judged by the approved version.
    later = _experiment(api, lab, seed=19)
    assert later["configuration"]["thresholds_source"]["version"] == 1
    assert later["evaluation"]["verdict"] == "not_successful"
    assert db.get(ScenarioThresholdVersion, uuid.UUID(again["thresholds_source"]["record_id"]))
