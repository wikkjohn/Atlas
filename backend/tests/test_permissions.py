"""Role-based authorization is enforced by the backend for every protected route."""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import ROLE_PERMISSIONS, Permission, RoleCode
from app.modules.identity.models import Role
from tests.factories import auth, make_employee, make_org_tree, make_user

PUBLIC_ROUTES = {("POST", "/api/v1/auth/login")}


def test_every_role_is_defined_in_code_and_database(db: Session) -> None:
    assert set(ROLE_PERMISSIONS) == set(RoleCode)
    assert set(db.execute(select(Role.code)).scalars()) == {r.value for r in RoleCode}
    assert ROLE_PERMISSIONS[RoleCode.PLATFORM_ADMINISTRATOR] == frozenset(Permission)


def test_every_v1_route_rejects_anonymous_requests(client: TestClient) -> None:
    # The OpenAPI document is the authoritative list of published endpoints.
    paths = client.get("/api/openapi.json").json()["paths"]
    checked = 0
    for template, operations in paths.items():
        if not template.startswith("/api/v1"):
            continue
        path = re.sub(r"\{[^}]+\}", "00000000-0000-0000-0000-000000000000", template)
        for method in operations:
            if (method.upper(), template) in PUBLIC_ROUTES:
                continue
            response = client.request(method.upper(), path, json={})
            assert response.status_code == 401, f"{method} {template} -> {response.status_code}"
            checked += 1
    assert checked >= 15


ALLOWED = 200
DENIED = 403


@pytest.mark.parametrize(
    ("role", "audit", "users", "create_org"),
    [
        (RoleCode.PLATFORM_ADMINISTRATOR, ALLOWED, ALLOWED, 201),
        (RoleCode.GLOBAL_EXECUTIVE, DENIED, ALLOWED, DENIED),
        (RoleCode.REGIONAL_EXECUTIVE, DENIED, DENIED, DENIED),
        (RoleCode.DEPARTMENT_MANAGER, DENIED, DENIED, DENIED),
        (RoleCode.BANKING_EMPLOYEE, DENIED, DENIED, DENIED),
        (RoleCode.COMPLIANCE_OFFICER, ALLOWED, DENIED, DENIED),
        (RoleCode.AI_RESEARCHER, DENIED, DENIED, DENIED),
        (RoleCode.AUDITOR, ALLOWED, ALLOWED, DENIED),
    ],
)
def test_role_permission_matrix(
    client: TestClient, db: Session, role: RoleCode, audit: int, users: int, create_org: int
) -> None:
    headers = auth(make_user(db, role))

    assert client.get("/api/v1/employees", headers=headers).status_code == ALLOWED
    assert client.get("/api/v1/organizations", headers=headers).status_code == ALLOWED
    assert client.get("/api/v1/countries", headers=headers).status_code == ALLOWED
    assert client.get("/api/v1/audit-events", headers=headers).status_code == audit
    assert client.get("/api/v1/users", headers=headers).status_code == users
    response = client.post(
        "/api/v1/organizations",
        json={"name": "ATLAS Global Bank", "organization_type": "global_bank"},
        headers=headers,
    )
    assert response.status_code == create_org


def test_forbidden_response_names_the_missing_permission(client: TestClient, db: Session) -> None:
    headers = auth(make_user(db, RoleCode.BANKING_EMPLOYEE))

    response = client.post(
        "/api/v1/countries",
        json={
            "iso_country_code": "FR",
            "country_name": "France",
            "region": "europe",
            "default_currency": "EUR",
            "default_timezone": "Europe/Paris",
            "supported_languages": ["fr-FR"],
        },
        headers=headers,
    )

    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "forbidden"
    assert error["details"] == {
        "required_permission": "countries:manage",
        "role": "banking_employee",
    }


def test_compensation_is_only_visible_with_permission(client: TestClient, db: Session) -> None:
    tree = make_org_tree(db)
    employee = make_employee(db, tree.us_onboarding, compensation=12_345_678)

    as_employee = client.get(
        f"/api/v1/employees/{employee.id}", headers=auth(make_user(db, RoleCode.BANKING_EMPLOYEE))
    ).json()
    as_auditor = client.get(
        f"/api/v1/employees/{employee.id}", headers=auth(make_user(db, RoleCode.AUDITOR))
    ).json()

    assert as_employee["annual_compensation"] is None
    assert as_employee["compensation_currency"] is None
    assert as_auditor["annual_compensation"] == 12_345_678
    assert as_auditor["compensation_currency"] == "USD"
