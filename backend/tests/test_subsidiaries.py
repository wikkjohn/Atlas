"""Phase 27: country subsidiaries generated from a versioned blueprint."""

from collections import Counter

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.core.errors import BusinessRuleViolation
from app.core.permissions import RoleCode
from app.modules.countries.models import Country, OperationalStatus, Region
from app.modules.employees.models import Employee
from app.modules.organizations import blueprint
from app.modules.organizations.models import Organization, OrganizationType
from app.simulation.router import get_simulation_sessionmaker
from tests.factories import auth, make_org_tree, make_user


def _country(db: Session, code: str) -> Country:
    return db.execute(select(Country).where(Country.iso_country_code == code)).scalar_one()


def _tree(db: Session, subsidiary: Organization) -> list[Organization]:
    found, frontier = [], [subsidiary]
    while frontier:
        children = list(
            db.execute(
                select(Organization).where(
                    Organization.parent_organization_id.in_([o.id for o in frontier])
                )
            ).scalars()
        )
        found += children
        frontier = children
    return found


def test_the_blueprint_describes_a_subsidiary() -> None:
    described = blueprint.describe()
    assert described["version"] == 1 and described["generated_from"] == "subsidiary-blueprint/1"
    # The subsidiary, 3 divisions, 4 departments and 4 teams; 2 staff per department and
    # a lead and 3 analysts per team.
    assert described["units_per_subsidiary"] == 12
    assert described["staff_per_subsidiary"] == 24
    assert set(described["regional_headquarters"]) == {r.value for r in Region}
    assert blueprint.salary_band("USD") == (62_000, 240_000)
    assert blueprint.salary_band("KWD")[1] < 100_000  # a dinar is worth about 3 dollars


def test_launching_a_country_builds_its_subsidiary(db: Session) -> None:
    make_org_tree(db)  # no Middle East & Africa headquarters yet
    kenya = _country(db, "KE")
    assert kenya.operational_status == OperationalStatus.PLANNED

    result = blueprint.launch_country(db, kenya, None)
    db.flush()
    assert result.activated and kenya.operational_status == OperationalStatus.ACTIVE
    # The regional headquarters and the 12 units of the subsidiary.
    assert result.organizations_created == 13 and result.employees_hired == 24
    subsidiary = db.get(Organization, result.subsidiary_id)
    assert subsidiary.name == "ATLAS Bank Kenya" and subsidiary.country_id == kenya.id
    hq = db.get(Organization, subsidiary.parent_organization_id)
    assert hq.name == "Middle East & Africa Regional Headquarters"
    assert hq.region == Region.MIDDLE_EAST_AFRICA

    units = _tree(db, subsidiary)
    assert Counter(u.organization_type for u in units) == {
        OrganizationType.BUSINESS_DIVISION: 3,
        OrganizationType.DEPARTMENT: 4,
        OrganizationType.TEAM: 4,
    }
    assert all(u.generated_from == blueprint.GENERATED_FROM for u in [subsidiary, hq, *units])
    staff = list(
        db.execute(
            select(Employee).where(Employee.organization_id.in_([u.id for u in units]))
        ).scalars()
    )
    assert len(staff) == 24
    assert {e.compensation_currency for e in staff} == {"KES"}
    low, high = blueprint.salary_band("KES")
    assert all(low * 100 <= e.annual_compensation <= high * 100 for e in staff)
    heads = [e for e in staff if e.job_title.startswith("Head of")]
    assert len(heads) == 4 and all(e.role.code == RoleCode.DEPARTMENT_MANAGER for e in heads)
    actions = set(
        db.execute(
            select(AuditEvent.action).where(
                AuditEvent.entity_id.in_([str(kenya.id), str(subsidiary.id)])
            )
        ).scalars()
    )
    assert {"country.launched", "organization.subsidiary_generated"} <= actions


def test_launching_again_adds_only_what_is_missing(db: Session) -> None:
    tree = make_org_tree(db)
    # The US subsidiary exists with part of the structure; launching completes it.
    us = _country(db, "US")
    before = db.execute(select(func.count()).select_from(Employee)).scalar_one()
    result = blueprint.launch_country(db, us, None)
    assert result.subsidiary_id == tree.us.id and not result.activated
    # Retail Banking and Customer Onboarding exist; the KYC team is named differently.
    assert "Retail Banking" not in result.created and "Customer Onboarding" not in result.created
    assert result.organizations_created == 12 - 3
    # Staff only for the new units: Branch Network (2), the two new teams (2 × 4), and the
    # two departments of the new divisions (2 × 2) plus their teams (2 × 4).
    assert result.employees_hired == 2 + 8 + 4 + 8
    assert db.execute(select(func.count()).select_from(Employee)).scalar_one() == before + 22

    again = blueprint.launch_country(db, us, None)
    assert (again.organizations_created, again.employees_hired) == (0, 0)


def test_launch_refusals_and_targets(db: Session) -> None:
    with pytest.raises(BusinessRuleViolation, match="no global bank"):
        blueprint.launch_country(db, _country(db, "KE"), None)
    make_org_tree(db)
    france = _country(db, "FR")
    france.operational_status = OperationalStatus.SUSPENDED.value
    db.flush()
    with pytest.raises(BusinessRuleViolation, match="suspended"):
        blueprint.launch_country(db, france, None)
    with pytest.raises(BusinessRuleViolation, match="Unknown countries: ZZ"):
        blueprint.targets(db, ["KE", "ZZ"])
    with pytest.raises(BusinessRuleViolation, match="Suspended"):
        blueprint.targets(db, ["FR"])

    europe = [c.iso_country_code for c in blueprint.targets(db, region=Region.EUROPE)]
    assert "FR" not in europe and "DE" in europe and "GB" in europe
    everywhere = {c.iso_country_code for c in blueprint.targets(db)}
    assert "US" not in everywhere and "JP" not in everywhere and len(everywhere) == 120 - 3
    coverage = {row["region"]: row for row in blueprint.coverage(db)}
    assert coverage["americas"]["subsidiaries"] == 1
    assert coverage["middle_east_africa"]["subsidiaries"] == 0
    assert sum(row["countries"] for row in coverage.values()) == 120


def test_the_names_of_generated_staff_are_reproducible(db: Session) -> None:
    make_org_tree(db)
    kenya = _country(db, "KE")
    first = blueprint._Builder(db, kenya, None, True)
    second = blueprint._Builder(db, kenya, None, True)
    assert [first.names.name() for _ in range(24)] == [second.names.name() for _ in range(24)]
    other = blueprint._Builder(db, _country(db, "GH"), None, True)
    assert [first.names.name() for _ in range(5)] != [other.names.name() for _ in range(5)]


# --- API ------------------------------------------------------------------------------------------


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


@pytest.fixture
def api(app: FastAPI, factory) -> TestClient:
    app.dependency_overrides[get_simulation_sessionmaker] = lambda: factory
    with TestClient(app) as client:
        yield client


def test_the_generation_api(api: TestClient, db: Session) -> None:
    make_org_tree(db)
    db.commit()
    admin = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))
    auditor = auth(make_user(db, RoleCode.AUDITOR))

    described = api.get("/api/v1/organizations/blueprint", headers=auditor).json()
    assert described["staff_per_subsidiary"] == 24
    regions = {row["region"]: row for row in described["coverage"]}
    assert "KE" in regions["middle_east_africa"]["without_subsidiary"]

    body = {"country_codes": ["ke", "GH"]}
    assert api.post("/api/v1/organizations/generate", json=body, headers=auditor).status_code == 403
    unknown = api.post(
        "/api/v1/organizations/generate", json={"country_codes": ["ZZ"]}, headers=admin
    )
    assert unknown.status_code == 422 and "ZZ" in unknown.text

    queued = api.post("/api/v1/organizations/generate", json=body, headers=admin)
    assert queued.status_code == 202
    assert queued.json()["payload"] == {"country_codes": ["GH", "KE"], "staff": True}
    # No worker in tests: the API ran the job itself after responding.
    job = api.get(f"/api/v1/jobs/{queued.json()['id']}", headers=admin).json()
    assert job["status"] == "succeeded", job
    assert job["result"]["launched"] == ["GH", "KE"] and job["result"]["employees_hired"] == 48

    listed = api.get(
        "/api/v1/organizations",
        params={"organization_type": "country_subsidiary", "q": "Ghana"},
        headers=auditor,
    ).json()["items"]
    assert listed[0]["name"] == "ATLAS Bank Ghana"
    assert listed[0]["generated_from"] == "subsidiary-blueprint/1"
    assert listed[0]["employee_count"] == 0 and listed[0]["child_count"] == 3
