"""Country configuration registry."""

import itertools
import string

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.core.permissions import RoleCode
from app.modules.countries.models import Country, OperationalStatus, Region
from app.modules.countries.schemas import CountryCreate
from app.modules.countries.service import create_country
from tests.factories import auth, make_user

FRANCE = {
    "iso_country_code": "fr",
    "country_name": "France",
    "region": "europe",
    "default_currency": "eur",
    "default_timezone": "Europe/Paris",
    "supported_languages": ["fr-FR", "en"],
}


def test_initial_countries_are_configured(client: TestClient, db: Session) -> None:
    response = client.get("/api/v1/countries", headers=auth(make_user(db, RoleCode.AI_RESEARCHER)))

    assert response.status_code == 200
    countries = {c["iso_country_code"]: c for c in response.json()["items"]}
    assert set(countries) == {"US", "GB", "DE", "SG", "JP"}
    assert countries["JP"]["default_currency"] == "JPY"
    assert countries["SG"]["region"] == "asia_pacific"
    assert countries["DE"]["default_timezone"] == "Europe/Berlin"
    assert all(c["operational_status"] == "active" for c in countries.values())


def test_admin_adds_a_country_and_it_is_audited(client: TestClient, db: Session) -> None:
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)

    response = client.post("/api/v1/countries", json=FRANCE, headers=auth(admin))

    assert response.status_code == 201
    body = response.json()
    assert body["iso_country_code"] == "FR"
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
        {"iso_country_code": "FRA"},
        {"supported_languages": []},
        {"supported_languages": ["French"]},
        {"region": "antarctica"},
    ]
    for override in invalid:
        response = client.post("/api/v1/countries", json={**FRANCE, **override}, headers=headers)
        assert response.status_code == 422, override
        assert response.json()["error"]["code"] == "validation_error"


def test_duplicate_country_code_conflicts(client: TestClient, db: Session) -> None:
    headers = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))

    response = client.post(
        "/api/v1/countries", json={**FRANCE, "iso_country_code": "JP"}, headers=headers
    )

    assert response.status_code == 409


def test_status_change_is_audited_with_a_diff(client: TestClient, db: Session) -> None:
    headers = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))
    france = client.post("/api/v1/countries", json=FRANCE, headers=headers).json()

    response = client.patch(
        f"/api/v1/countries/{france['id']}", json={"operational_status": "active"}, headers=headers
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
    existing = set(db.execute(select(Country.iso_country_code)).scalars())
    codes = (
        a + b
        for a, b in itertools.product(string.ascii_uppercase, repeat=2)
        if a + b not in existing
    )
    for code in itertools.islice(codes, 120 - len(existing)):
        create_country(
            db,
            CountryCreate(
                iso_country_code=code,
                country_name=f"Synthetic Country {code}",
                region=Region.MIDDLE_EAST_AFRICA,
                default_currency="XTS",  # ISO 4217 code reserved for testing
                default_timezone="UTC",
                supported_languages=["en"],
                operational_status=OperationalStatus.PLANNED,
            ),
            actor_id=None,
        )
    headers = auth(make_user(db, RoleCode.AUDITOR))

    page = client.get("/api/v1/countries?limit=200", headers=headers).json()
    filtered = client.get(
        "/api/v1/countries?region=europe&operational_status=active", headers=headers
    ).json()

    assert db.execute(select(func.count()).select_from(Country)).scalar_one() == 120
    assert page["total"] == 120
    assert len(page["items"]) == 120
    assert {c["iso_country_code"] for c in filtered["items"]} == {"GB", "DE"}
