"""Synthetic customers: onboarding, KYC transitions and risk rating."""

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.core.permissions import RoleCode
from app.modules.customers.models import KycStatus
from tests.factories import auth, country, make_customer, make_user

URL = "/api/v1/customers"


def _new(client: TestClient, headers: dict, **overrides: object):
    body = {
        "customer_type": "individual",
        "name": "Avery Quinn",
        "date_of_birth_or_incorporation": "1990-04-02",
        "country_id": str(overrides.pop("country_id")),
        **overrides,
    }
    return client.post(URL, json=body, headers=headers)


def test_onboarding_individuals_and_businesses(client: TestClient, db: Session) -> None:
    headers = auth(make_user(db, RoleCode.BANKING_EMPLOYEE))

    person = _new(client, headers, country_id=country(db, "JP").id)
    company = _new(
        client,
        headers,
        country_id=country(db, "DE").id,
        customer_type="business",
        name="Nordlicht Logistik GmbH",
        date_of_birth_or_incorporation="2011-09-01",
    )

    assert person.status_code == company.status_code == 201
    assert person.json()["customer_number"].startswith("CUS-")
    assert person.json()["currency"] == "JPY"
    assert person.json()["kyc_status"] == "not_started"
    assert person.json()["risk_rating"] == "unrated"
    assert company.json()["customer_type"] == "business"
    assert company.json()["currency"] == "EUR"
    events = db.execute(select(AuditEvent).where(AuditEvent.action == "customer.created")).all()
    assert len(events) == 2


def test_onboarding_rules(client: TestClient, db: Session) -> None:
    headers = auth(make_user(db, RoleCode.BANKING_EMPLOYEE))
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    germany = country(db, "DE")
    germany.operational_status = "suspended"
    db.flush()

    future = _new(
        client, headers, country_id=country(db, "US").id, date_of_birth_or_incorporation=tomorrow
    )
    suspended = _new(client, headers, country_id=germany.id)
    bad_type = _new(client, headers, country_id=country(db, "US").id, customer_type="trust")

    assert future.status_code == 422
    assert future.json()["error"]["code"] == "business_rule_violation"
    assert suspended.status_code == 422
    assert bad_type.status_code == 422


def test_kyc_follows_its_transitions(client: TestClient, db: Session) -> None:
    customer = make_customer(db, kyc=None)
    headers = auth(make_user(db, RoleCode.COMPLIANCE_OFFICER))
    review = f"{URL}/{customer.id}/review"

    skipped = client.post(review, json={"kyc_status": "verified"}, headers=headers)
    pending = client.post(review, json={"kyc_status": "pending"}, headers=headers)
    unrated = client.post(review, json={"kyc_status": "verified"}, headers=headers)
    verified = client.post(
        review,
        json={"kyc_status": "verified", "risk_rating": "medium", "note": "docs ok"},
        headers=headers,
    )
    unrate = client.post(review, json={"risk_rating": "unrated"}, headers=headers)
    reopened = client.post(review, json={"kyc_status": "pending"}, headers=headers)

    assert skipped.status_code == 422
    assert skipped.json()["error"]["details"]["allowed"] == ["pending"]
    assert pending.status_code == 200
    assert unrated.status_code == 422  # a risk rating is required before verification
    assert verified.status_code == 200
    assert verified.json()["kyc_status"] == "verified"
    assert verified.json()["risk_rating"] == "medium"
    assert unrate.status_code == 422
    assert reopened.json()["kyc_status"] == KycStatus.PENDING
    reviews = (
        db.execute(
            select(AuditEvent).where(
                AuditEvent.action == "customer.reviewed", AuditEvent.entity_id == str(customer.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(reviews) == 3


def test_only_reviewers_make_kyc_decisions(client: TestClient, db: Session) -> None:
    customer = make_customer(db, kyc=None)

    response = client.post(
        f"{URL}/{customer.id}/review",
        json={"kyc_status": "pending"},
        headers=auth(make_user(db, RoleCode.BANKING_EMPLOYEE)),
    )

    assert response.status_code == 403
    assert response.json()["error"]["details"]["required_permission"] == "customers:review"


def test_search_and_filters(client: TestClient, db: Session) -> None:
    make_customer(
        db,
        name="Helios Trading Pte Ltd",
        country_code="SG",
        customer_type="business",
        born=date(2015, 1, 1),
    )
    make_customer(db, name="Mara Lindqvist", kyc=KycStatus.PENDING)
    headers = auth(make_user(db, RoleCode.AI_RESEARCHER))

    by_name = client.get(f"{URL}?q=helios", headers=headers).json()
    pending = client.get(f"{URL}?kyc_status=pending", headers=headers).json()
    businesses = client.get(f"{URL}?customer_type=business", headers=headers).json()

    assert [c["name"] for c in by_name["items"]] == ["Helios Trading Pte Ltd"]
    assert [c["name"] for c in pending["items"]] == ["Mara Lindqvist"]
    assert [c["country_code"] for c in businesses["items"]] == ["SG"]
