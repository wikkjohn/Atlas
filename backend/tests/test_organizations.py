"""Organization hierarchy rules, country rules, auditing and idempotency."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.core.permissions import RoleCode
from app.modules.countries.models import Region
from app.modules.organizations.models import Organization, OrganizationType
from tests.factories import auth, country, make_employee, make_org, make_org_tree, make_user

URL = "/api/v1/organizations"


def _admin(db: Session) -> dict[str, str]:
    return auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))


def test_full_hierarchy_can_be_built_through_the_api(client: TestClient, db: Session) -> None:
    headers = _admin(db)

    def create(**body: object) -> dict:
        response = client.post(URL, json=body, headers=headers)
        assert response.status_code == 201, response.json()
        return response.json()

    bank = create(name="ATLAS Global Bank", organization_type="global_bank")
    europe = create(
        name="Europe HQ",
        organization_type="regional_headquarters",
        parent_organization_id=bank["id"],
        region="europe",
    )
    germany = create(
        name="ATLAS Deutschland",
        organization_type="country_subsidiary",
        parent_organization_id=europe["id"],
        country_id=str(country(db, "DE").id),
    )
    retail = create(
        name="Retail Banking",
        organization_type="business_division",
        parent_organization_id=germany["id"],
    )
    onboarding = create(
        name="Onboarding", organization_type="department", parent_organization_id=retail["id"]
    )
    team = create(
        name="KYC Team", organization_type="team", parent_organization_id=onboarding["id"]
    )

    # Country configuration flows down the hierarchy.
    assert germany["region"] == "europe"
    assert team["country_code"] == "DE"
    assert team["currency"] == "EUR"
    assert team["region"] == "europe"

    ancestors = client.get(f"{URL}/{team['id']}/ancestors", headers=headers).json()
    assert [a["name"] for a in ancestors] == [
        "ATLAS Global Bank",
        "Europe HQ",
        "ATLAS Deutschland",
        "Retail Banking",
        "Onboarding",
    ]
    bank_out = client.get(f"{URL}/{bank['id']}", headers=headers).json()
    assert bank_out["child_count"] == 1
    roots = client.get(f"{URL}?root_only=true", headers=headers).json()
    assert [r["id"] for r in roots["items"]] == [bank["id"]]
    children = client.get(f"{URL}?parent_id={retail['id']}", headers=headers).json()
    assert [c["name"] for c in children["items"]] == ["Onboarding"]
    assert (
        db.execute(
            select(func.count()).where(AuditEvent.action == "organization.created")
        ).scalar_one()
        == 6
    )


def _violation(client: TestClient, headers: dict[str, str], body: dict, status: int = 422) -> dict:
    response = client.post(URL, json=body, headers=headers)
    assert response.status_code == status, response.json()
    return response.json()["error"]


def test_invalid_parent_relationships_are_rejected(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)
    headers = _admin(db)

    # A department directly under a subsidiary (skipping the division).
    error = _violation(
        client,
        headers,
        {
            "name": "Ops",
            "organization_type": "department",
            "parent_organization_id": str(tree.us.id),
        },
    )
    assert error["code"] == "business_rule_violation"
    assert error["details"]["required_parent_type"] == "business_division"

    # Missing and non-existent parents.
    _violation(client, headers, {"name": "Lonely Team", "organization_type": "team"})
    _violation(
        client,
        headers,
        {"name": "Ghost", "organization_type": "team", "parent_organization_id": str(uuid.uuid4())},
    )
    # The global bank is unique and is the only root.
    _violation(
        client, headers, {"name": "Second Bank", "organization_type": "global_bank"}, status=409
    )
    _violation(
        client,
        headers,
        {
            "name": "Nested Bank",
            "organization_type": "global_bank",
            "parent_organization_id": str(tree.bank.id),
        },
    )
    # A team cannot contain another team.
    _violation(
        client,
        headers,
        {
            "name": "Sub Team",
            "organization_type": "team",
            "parent_organization_id": str(tree.us_kyc_team.id),
        },
    )


def test_country_rules_constrain_the_hierarchy(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)
    headers = _admin(db)

    # Japan is in Asia-Pacific, so it cannot sit under the European headquarters.
    error = _violation(
        client,
        headers,
        {
            "name": "ATLAS Japan West",
            "organization_type": "country_subsidiary",
            "parent_organization_id": str(tree.europe.id),
            "country_id": str(country(db, "JP").id),
        },
    )
    assert error["details"] == {"country_region": "asia_pacific", "parent_region": "europe"}

    # A subsidiary must name its country, and only one per country is allowed.
    _violation(
        client,
        headers,
        {
            "name": "Unnamed",
            "organization_type": "country_subsidiary",
            "parent_organization_id": str(tree.europe.id),
        },
    )
    _violation(
        client,
        headers,
        {
            "name": "ATLAS US Two",
            "organization_type": "country_subsidiary",
            "parent_organization_id": str(tree.americas.id),
            "country_id": str(country(db, "US").id),
        },
        status=409,
    )
    # Divisions inherit their country and cannot override it.
    _violation(
        client,
        headers,
        {
            "name": "Markets",
            "organization_type": "business_division",
            "parent_organization_id": str(tree.us.id),
            "country_id": str(country(db, "GB").id),
        },
    )


def test_inactive_countries_block_new_organizations(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)
    headers = _admin(db)
    germany = country(db, "DE")
    germany.operational_status = "suspended"
    db.flush()

    error = _violation(
        client,
        headers,
        {
            "name": "ATLAS Deutschland",
            "organization_type": "country_subsidiary",
            "parent_organization_id": str(tree.europe.id),
            "country_id": str(germany.id),
        },
    )

    assert error["details"] == {"country": "DE", "status": "suspended"}


def test_sibling_names_must_be_unique(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)

    _violation(
        client,
        _admin(db),
        {
            "name": "Retail Banking",
            "organization_type": "business_division",
            "parent_organization_id": str(tree.us.id),
        },
        status=409,
    )
    # The same name under a different parent is fine (Japan also has "Retail Banking").
    assert tree.jp_retail.name == tree.us_retail.name


def test_deactivation_rules(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)
    headers = _admin(db)
    make_employee(db, tree.us_kyc_team)

    blocked = client.patch(
        f"{URL}/{tree.us_onboarding.id}", json={"status": "inactive"}, headers=headers
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["details"] == {"active_children": 1, "active_employees": 0}

    empty_team = make_org(db, "Empty Team", OrganizationType.TEAM, tree.jp_onboarding)
    response = client.patch(f"{URL}/{empty_team.id}", json={"status": "inactive"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "inactive"

    # Nothing can be created under an inactive organization.
    _violation(
        client,
        headers,
        {"name": "X", "organization_type": "team", "parent_organization_id": str(empty_team.id)},
    )


def test_idempotency_key_prevents_duplicate_creation(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)
    headers = {**_admin(db), "Idempotency-Key": "create-markets-1"}
    body = {
        "name": "Markets",
        "organization_type": "business_division",
        "parent_organization_id": str(tree.us.id),
    }

    first = client.post(URL, json=body, headers=headers)
    retry = client.post(URL, json=body, headers=headers)
    reused = client.post(URL, json={**body, "name": "Treasury"}, headers=headers)

    assert first.status_code == retry.status_code == 201
    assert retry.json() == first.json()
    assert retry.headers["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in first.headers
    assert reused.status_code == 409
    assert (
        db.execute(
            select(func.count()).where(Organization.name.in_(["Markets", "Treasury"]))
        ).scalar_one()
        == 1
    )
    created_events = db.execute(
        select(func.count()).where(
            AuditEvent.action == "organization.created",
            AuditEvent.entity_id == first.json()["id"],
        )
    ).scalar_one()
    assert created_events == 1


def test_failed_idempotent_request_can_be_retried(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)
    headers = {**_admin(db), "Idempotency-Key": "retry-after-failure"}
    body = {
        "name": "Retail Banking",  # duplicate sibling name -> 409, nothing stored
        "organization_type": "business_division",
        "parent_organization_id": str(tree.us.id),
    }

    assert client.post(URL, json=body, headers=headers).status_code == 409
    response = client.post(URL, json={**body, "name": "Wealth"}, headers=headers)

    assert response.status_code == 201


def test_regional_headquarters_requires_region(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)

    _violation(
        client,
        _admin(db),
        {
            "name": "Middle East HQ",
            "organization_type": "regional_headquarters",
            "parent_organization_id": str(tree.bank.id),
        },
    )
    assert tree.asia.region == Region.ASIA_PACIFIC
