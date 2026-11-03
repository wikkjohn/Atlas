"""Phase 63: the application registry — profiles, dependencies, impact and the generated
estate."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.permissions import RoleCode
from app.modules.itops import estate
from app.modules.itops import service as itops
from app.modules.itops.models import Application, ApplicationDependency
from tests.factories import auth, make_org_tree, make_user


def _apps(db: Session, *names_tiers):
    tree = make_org_tree(db)
    return [itops.register_application(db, name=name, description="", tier=tier,
                                       department_id=tree.us_onboarding.id, actor_id=None)
            for name, tier in names_tiers]  # fmt: skip


def test_profiles_dependencies_and_cycles(db: Session) -> None:
    ledger, gateway, portal, report = _apps(db, ("Ledger", 1), ("Gateway", 1), ("Portal", 2),
                                            ("Reports", 3))  # fmt: skip
    owner = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    estate.set_profile(db, ledger, owner_username=owner.username, technology="COBOL-Mainframe",
                       hosting="on_premise", vendor=None, actor_id=None)  # fmt: skip
    assert ledger.owner_id == owner.id and ledger.technology == "cobol-mainframe"
    with pytest.raises(BusinessRuleViolation, match="Hosting"):
        estate.set_profile(db, ledger, owner_username=None, technology="java",
                           hosting="moon", vendor=None, actor_id=None)  # fmt: skip
    with pytest.raises(NotFoundError):
        estate.set_profile(db, ledger, owner_username="nobody", technology="java",
                           hosting="saas", vendor=None, actor_id=None)  # fmt: skip

    estate.add_dependency(db, gateway, ledger, "api", None)
    estate.add_dependency(db, portal, gateway, "api", None)
    estate.add_dependency(db, report, portal, "data", None)
    with pytest.raises(ConflictError):
        estate.add_dependency(db, gateway, ledger, "data", None)
    with pytest.raises(BusinessRuleViolation, match="itself") as refused:
        estate.add_dependency(db, ledger, ledger, "api", None)
    assert refused.value.details["rule"] == "not_self"
    # The ledger relying on the reports would close a cycle through all four.
    with pytest.raises(BusinessRuleViolation, match="cycle") as refused:
        estate.add_dependency(db, ledger, report, "batch", None)
    assert refused.value.details["rule"] == "cycle"
    with pytest.raises(BusinessRuleViolation, match="kind"):
        estate.add_dependency(db, report, ledger, "magic", None)
    ledger.status = "retired"
    with pytest.raises(BusinessRuleViolation, match="retired"):
        estate.add_dependency(db, report, ledger, "data", None)
    ledger.status = "active"

    assert [o.name for _, o in estate.dependencies(db, gateway)] == ["Ledger"]
    assert [o.name for _, o in estate.dependents(db, gateway)] == ["Portal"]
    # The ledger stopping reaches the gateway, then the portal, then the reports.
    hit = estate.impact(db, ledger)
    assert hit["affected"] == 3 and hit["direct"] == 1 and hit["depth"] == 3
    assert hit["by_tier"] == {"1": 1, "2": 1, "3": 1}
    assert [s["name"] for s in hit["sample"]] == ["Gateway", "Portal", "Reports"]
    assert estate.impact(db, report)["affected"] == 0
    dependency_id = estate.dependencies(db, portal)[0][0].id
    estate.remove_dependency(db, dependency_id, None)
    assert estate.impact(db, ledger)["affected"] == 1


def test_the_generated_estate_is_deterministic_acyclic_and_idempotent(db: Session) -> None:
    make_org_tree(db)
    make_user(db, RoleCode.DEPARTMENT_MANAGER)
    first = estate.generate_estate(db, 300, 7)
    assert first["created"] == 300 and first["dependencies_added"] > 300
    tagged = Application.generated_from == "estate-v1:7"
    apps = {a.id: a for a in db.execute(select(Application).where(tagged)).scalars()}
    assert len(apps) == 300
    # Every application relies only on ones generated before it: no cycles.
    order = {a.id: int(a.name[-4:]) for a in apps.values()}
    for app_id, depends_on in db.execute(
            select(ApplicationDependency.application_id, ApplicationDependency.depends_on_id)
            .where(ApplicationDependency.application_id.in_(list(apps)))).tuples():  # fmt: skip
        assert depends_on not in apps or order[depends_on] < order[app_id]
    tiers = {t: sum(1 for a in apps.values() if a.tier == t) for t in (1, 2, 3)}
    assert tiers[3] > tiers[2] > tiers[1] > 0
    assert all(a.owner_id is not None for a in apps.values())
    assert {a.hosting for a in apps.values()} <= set(estate.HOSTING)
    # Again with the same seed: nothing new.
    again = estate.generate_estate(db, 300, 7)
    assert again["created"] == 0 and again["dependencies_added"] == 0
    total = db.execute(select(func.count()).select_from(Application).where(tagged)).scalar_one()
    assert total == 300
    with pytest.raises(BusinessRuleViolation, match="1 to 10,000"):
        estate.generate_estate(db, 0, 7)
    summary = estate.summary(db)
    assert summary["generated"] == 300 and summary["dependencies"] >= first["dependencies_added"]


def test_registry_api_and_permissions(client: TestClient, db: Session) -> None:
    ledger, gateway = _apps(db, ("Ledger", 1), ("Gateway", 1))
    manager = make_user(db, RoleCode.DEPARTMENT_MANAGER)
    executive = make_user(db, RoleCode.REGIONAL_EXECUTIVE)
    auditor = make_user(db, RoleCode.AUDITOR)
    url = f"/api/v1/itops/applications/{gateway.id}"
    body = {"depends_on": ledger.application_number, "kind": "api"}
    assert client.post(f"{url}/dependencies", json=body,
                       headers=auth(manager)).status_code == 403  # fmt: skip
    assert client.post(f"{url}/dependencies", json=body,
                       headers=auth(executive)).status_code == 201  # fmt: skip
    profile = client.put(f"{url}/profile", headers=auth(executive), json={
        "owner_username": manager.username, "technology": "java-spring",
        "hosting": "private_cloud"})  # fmt: skip
    assert profile.status_code == 200 and profile.json()["owner"] == manager.username
    detail = client.get(f"/api/v1/itops/applications/{ledger.id}", headers=auth(auditor)).json()
    assert detail["dependents"][0]["name"] == "Gateway"
    assert detail["impact"]["affected"] == 1
    listed = client.get("/api/v1/itops/applications?tier=1&q=Gate", headers=auth(auditor)).json()
    assert listed["total"] == 1 and listed["items"][0]["technology"] == "java-spring"
    assert client.post("/api/v1/itops/estate/generate", json={"count": 5, "seed": 1},
                       headers=auth(manager)).status_code == 403  # fmt: skip
    generated = client.post("/api/v1/itops/estate/generate", json={"count": 5, "seed": 1},
                            headers=auth(executive))  # fmt: skip
    assert generated.status_code == 200 and generated.json()["created"] == 5
    summary = client.get("/api/v1/itops/estate/summary", headers=auth(auditor)).json()
    assert summary["generated"] == 5 and summary["applications"] == 7
