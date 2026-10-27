"""Employee assignment, reporting structure and country-driven compensation currency."""

import re

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.core.permissions import RoleCode
from tests.factories import auth, country, make_employee, make_org_tree, make_user

URL = "/api/v1/employees"


def _admin(db: Session) -> dict[str, str]:
    return auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))


def test_hiring_into_a_team_assigns_department_and_country(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)

    response = client.post(
        URL,
        json={
            "first_name": "Mira",
            "last_name": "Okafor",
            "organization_id": str(tree.us_kyc_team.id),
            "job_title": "KYC Analyst",
            "annual_compensation": 8_250_000,
        },
        headers=_admin(db),
    )

    assert response.status_code == 201
    body = response.json()
    assert re.fullmatch(r"AGB-\d{7}", body["employee_number"])
    assert body["email"] == "mira.okafor@atlasbank.example"
    assert body["organization_name"] == "KYC Review Team"
    assert body["department_id"] == str(tree.us_onboarding.id)
    assert body["department_name"] == "Customer Onboarding"
    assert body["country_code"] == "US"
    assert body["compensation_currency"] == "USD"
    assert body["annual_compensation"] == 8_250_000
    assert body["role"] == "banking_employee"


def test_country_configuration_sets_compensation_currency(db: Session) -> None:
    tree = make_org_tree(db)

    employee = make_employee(db, tree.jp_onboarding, compensation=950_000_000)

    assert employee.country.iso_country_code == "JP"
    assert employee.compensation_currency == "JPY"


def test_employees_join_departments_or_teams_only(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)

    response = client.post(
        URL,
        json={
            "first_name": "Sam",
            "last_name": "Lee",
            "organization_id": str(tree.us_retail.id),
            "job_title": "Analyst",
            "annual_compensation": 1,
        },
        headers=_admin(db),
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"] == {"organization_type": "business_division"}


def test_employees_cannot_be_placed_in_suspended_countries(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)
    country(db, "US").operational_status = "suspended"
    db.flush()

    response = client.post(
        URL,
        json={
            "first_name": "Ana",
            "last_name": "Diaz",
            "organization_id": str(tree.us_onboarding.id),
            "job_title": "Analyst",
            "annual_compensation": 1,
        },
        headers=_admin(db),
    )

    assert response.status_code == 422


def test_only_synthetic_email_addresses_are_accepted(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)

    response = client.post(
        URL,
        json={
            "first_name": "Real",
            "last_name": "Person",
            "email": "real.person@gmail.com",
            "organization_id": str(tree.us_onboarding.id),
            "job_title": "Analyst",
            "annual_compensation": 1,
        },
        headers=_admin(db),
    )

    assert response.status_code == 422


def test_generated_emails_stay_unique(db: Session) -> None:
    tree = make_org_tree(db)

    first = make_employee(db, tree.us_onboarding, first_name="Lee", last_name="Chen")
    second = make_employee(db, tree.jp_onboarding, first_name="Lee", last_name="Chen")

    assert first.email == "lee.chen@atlasbank.example"
    assert second.email == "lee.chen2@atlasbank.example"


def test_reporting_structure(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)
    head = make_employee(db, tree.us_onboarding, first_name="Dana", job_title="Head of Onboarding")
    lead = make_employee(
        db, tree.us_kyc_team, first_name="Eli", manager=head, job_title="Team Lead"
    )
    analyst = make_employee(db, tree.us_kyc_team, first_name="Fay", manager=lead)
    headers = auth(make_user(db, RoleCode.BANKING_EMPLOYEE))

    chain = client.get(f"{URL}/{analyst.id}/reporting-chain", headers=headers).json()
    reports = client.get(f"{URL}/{head.id}/direct-reports", headers=headers).json()
    managed = client.get(f"{URL}?manager_id={lead.id}", headers=headers).json()
    detail = client.get(f"{URL}/{analyst.id}", headers=headers).json()

    assert [e["id"] for e in chain] == [str(lead.id), str(head.id)]
    assert [e["id"] for e in reports] == [str(lead.id)]
    assert [e["id"] for e in managed["items"]] == [str(analyst.id)]
    assert detail["manager"]["full_name"].startswith("Eli ")


def test_reporting_cycles_are_rejected(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)
    a = make_employee(db, tree.us_onboarding)
    b = make_employee(db, tree.us_onboarding, manager=a)
    c = make_employee(db, tree.us_onboarding, manager=b)
    headers = _admin(db)

    cycle = client.patch(f"{URL}/{a.id}", json={"manager_id": str(c.id)}, headers=headers)
    self_managed = client.patch(f"{URL}/{a.id}", json={"manager_id": str(a.id)}, headers=headers)

    assert cycle.status_code == 422
    assert "cycle" in cycle.json()["error"]["message"]
    assert self_managed.status_code == 422


def test_manager_can_be_cleared_and_changes_are_audited(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)
    manager = make_employee(db, tree.us_onboarding)
    employee = make_employee(db, tree.us_onboarding, manager=manager, compensation=100)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)

    response = client.patch(
        f"{URL}/{employee.id}",
        json={
            "manager_id": None,
            "organization_id": str(tree.us_kyc_team.id),
            "annual_compensation": 200,
        },
        headers={**auth(admin), "X-Correlation-ID": "transfer-42"},
    )

    assert response.status_code == 200
    assert response.json()["manager"] is None
    assert response.json()["organization_id"] == str(tree.us_kyc_team.id)
    event = db.execute(
        select(AuditEvent).where(
            AuditEvent.action == "employee.updated", AuditEvent.entity_id == str(employee.id)
        )
    ).scalar_one()
    assert event.actor_id == admin.id
    assert event.correlation_id == "transfer-42"
    changes = event.event_metadata["changes"]
    assert changes["manager_id"] == {"from": str(manager.id), "to": None}
    assert changes["organization_id"]["to"] == str(tree.us_kyc_team.id)
    # Compensation is recorded as changed, never with its values.
    assert changes["annual_compensation"] == {"changed": True}
    assert "department_id" not in changes  # same department


def test_termination_requires_reassigning_reports(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)
    manager = make_employee(db, tree.us_onboarding)
    report = make_employee(db, tree.us_onboarding, manager=manager)
    headers = _admin(db)

    blocked = client.patch(
        f"{URL}/{manager.id}", json={"employment_status": "terminated"}, headers=headers
    )
    client.patch(f"{URL}/{report.id}", json={"manager_id": None}, headers=headers)
    allowed = client.patch(
        f"{URL}/{manager.id}", json={"employment_status": "terminated"}, headers=headers
    )
    as_manager = client.patch(
        f"{URL}/{report.id}", json={"manager_id": str(manager.id)}, headers=headers
    )

    assert blocked.status_code == 422
    assert allowed.status_code == 200
    assert as_manager.status_code == 422  # terminated employees cannot manage


def test_search_and_filters(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)
    make_employee(db, tree.us_onboarding, first_name="Quinn", last_name="Harper")
    make_employee(db, tree.jp_onboarding, first_name="Haruto", last_name="Sato")
    make_employee(db, tree.us_kyc_team, first_name="Rae", last_name="Morgan")
    headers = auth(make_user(db, RoleCode.BANKING_EMPLOYEE))

    by_name = client.get(f"{URL}?q=quinn harp", headers=headers).json()
    by_country = client.get(f"{URL}?country_id={country(db, 'JP').id}", headers=headers).json()
    by_department = client.get(
        f"{URL}?department_id={tree.us_onboarding.id}", headers=headers
    ).json()
    paged = client.get(f"{URL}?limit=1&offset=1", headers=headers).json()

    assert [e["full_name"] for e in by_name["items"]] == ["Quinn Harper"]
    assert [e["full_name"] for e in by_country["items"]] == ["Haruto Sato"]
    assert by_department["total"] == 2  # department includes its team
    assert paged["total"] == 3 and len(paged["items"]) == 1 and paged["offset"] == 1


def test_pagination_limits_are_validated(client: TestClient, db: Session) -> None:
    headers = auth(make_user(db, RoleCode.BANKING_EMPLOYEE))

    assert client.get(f"{URL}?limit=0", headers=headers).status_code == 422
    assert client.get(f"{URL}?limit=500", headers=headers).status_code == 422
    assert client.get(f"{URL}?offset=-1", headers=headers).status_code == 422


def test_cross_country_transfers_are_rejected(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)
    employee = make_employee(db, tree.us_onboarding)

    response = client.patch(
        f"{URL}/{employee.id}",
        json={"organization_id": str(tree.jp_onboarding.id)},
        headers=_admin(db),
    )

    assert response.status_code == 422
    db.refresh(employee)
    assert employee.organization_id == tree.us_onboarding.id
    assert employee.compensation_currency == "USD"
