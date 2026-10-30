"""Country configuration registry."""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.core.permissions import RoleCode
from app.modules.countries.models import Country
from tests.factories import auth, make_user

# A country outside the reference data (Phase 23) of the 120-country footprint.
KOSOVO = {
    "iso_country_code": "xk",
    "country_name": "Kosovo",
    "region": "europe",
    "default_currency": "eur",
    "default_timezone": "Europe/Belgrade",
    "supported_languages": ["sq-XK", "sr"],
}


def test_initial_countries_are_configured(client: TestClient, db: Session) -> None:
    response = client.get(
        "/api/v1/countries?operational_status=active",
        headers=auth(make_user(db, RoleCode.AI_RESEARCHER)),
    )

    assert response.status_code == 200
    countries = {c["iso_country_code"]: c for c in response.json()["items"]}
    assert set(countries) == {"US", "GB", "DE", "SG", "JP"}
    assert countries["JP"]["default_currency"] == "JPY"
    assert countries["SG"]["region"] == "asia_pacific"
    assert countries["DE"]["default_timezone"] == "Europe/Berlin"
    assert all(c["operational_status"] == "active" for c in countries.values())


def test_admin_adds_a_country_and_it_is_audited(client: TestClient, db: Session) -> None:
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)

    response = client.post("/api/v1/countries", json=KOSOVO, headers=auth(admin))

    assert response.status_code == 201
    body = response.json()
    assert body["iso_country_code"] == "XK"
    assert body["default_currency"] == "EUR"
    assert body["operational_status"] == "planned"
    event = db.execute(
        select(AuditEvent).where(AuditEvent.action == "country.created")
    ).scalar_one()
    assert event.actor_id == admin.id
    assert event.entity_id == body["id"]


def test_invalid_country_configuration_is_rejected(client: TestClient, db: Session) -> None:
    headers = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))
    invalid = [
        {"default_timezone": "Mars/Olympus_Mons"},
        {"default_currency": "EURO"},
        {"iso_country_code": "XKX"},
        {"supported_languages": []},
        {"supported_languages": ["French"]},
        {"region": "antarctica"},
    ]
    for override in invalid:
        response = client.post("/api/v1/countries", json={**KOSOVO, **override}, headers=headers)
        assert response.status_code == 422, override
        assert response.json()["error"]["code"] == "validation_error"


def test_duplicate_country_code_conflicts(client: TestClient, db: Session) -> None:
    headers = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))

    response = client.post(
        "/api/v1/countries", json={**KOSOVO, "iso_country_code": "JP"}, headers=headers
    )

    assert response.status_code == 409


def test_a_new_country_needs_a_known_currency(client: TestClient, db: Session) -> None:
    headers = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))

    response = client.post(
        "/api/v1/countries", json={**KOSOVO, "default_currency": "XTS"}, headers=headers
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "business_rule_violation"
    assert response.json()["error"]["details"] == {"currency": "XTS"}


def test_status_change_is_audited_with_a_diff(client: TestClient, db: Session) -> None:
    headers = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))
    kosovo = client.post("/api/v1/countries", json=KOSOVO, headers=headers).json()

    response = client.patch(
        f"/api/v1/countries/{kosovo['id']}", json={"operational_status": "active"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["operational_status"] == "active"
    event = db.execute(
        select(AuditEvent).where(AuditEvent.action == "country.updated")
    ).scalar_one()
    assert event.event_metadata == {
        "changes": {"operational_status": {"from": "planned", "to": "active"}}
    }


def test_registry_holds_the_120_country_target(client: TestClient, db: Session) -> None:
    headers = auth(make_user(db, RoleCode.AUDITOR))

    page = client.get("/api/v1/countries?limit=200", headers=headers).json()
    filtered = client.get(
        "/api/v1/countries?region=europe&operational_status=active", headers=headers
    ).json()
    euro = client.get("/api/v1/countries?currency=eur&limit=200", headers=headers).json()

    assert db.execute(select(func.count()).select_from(Country)).scalar_one() == 120
    assert page["total"] == 120
    assert len(page["items"]) == 120
    assert {c["iso_country_code"] for c in filtered["items"]} == {"GB", "DE"}
    assert {"DE", "FR", "IE", "BG", "HR"} <= {c["iso_country_code"] for c in euro["items"]}
    assert all(c["default_currency"] == "EUR" for c in euro["items"])
