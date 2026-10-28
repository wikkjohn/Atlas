"""Audit log: append-only, protected, searchable."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent, record_audit_event
from app.core.permissions import RoleCode
from tests.factories import auth, make_org_tree, make_user

URL = "/api/v1/audit-events"


def test_database_rejects_modifying_audit_events(db: Session) -> None:
    event = record_audit_event(
        db, actor_id=None, action="test.event", entity_type="test", entity_id="1"
    )

    for statement in (
        f"UPDATE audit_events SET action = 'tampered' WHERE id = '{event.id}'",
        f"DELETE FROM audit_events WHERE id = '{event.id}'",
        "TRUNCATE audit_events",
    ):
        with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
            db.execute(text(statement))

    db.expire_all()
    assert db.get(AuditEvent, event.id).action == "test.event"


def test_api_has_no_write_operations(client: TestClient, db: Session) -> None:
    headers = auth(make_user(db, RoleCode.PLATFORM_ADMINISTRATOR))
    event = record_audit_event(
        db, actor_id=None, action="test.event", entity_type="test", entity_id="1"
    )

    assert client.post(URL, json={}, headers=headers).status_code == 405
    assert client.patch(f"{URL}/{event.id}", json={}, headers=headers).status_code in {404, 405}
    assert client.delete(f"{URL}/{event.id}", headers=headers).status_code in {404, 405}


def test_audit_search_filters(client: TestClient, db: Session) -> None:
    make_org_tree(db)
    auditor = make_user(db, RoleCode.AUDITOR)
    headers = auth(auditor)

    org_events = client.get(f"{URL}?action=organization.*&limit=100", headers=headers).json()
    user_events = client.get(f"{URL}?entity_type=user", headers=headers).json()
    by_id = client.get(
        f"{URL}?entity_id={org_events['items'][0]['entity_id']}", headers=headers
    ).json()

    assert org_events["total"] == 11
    assert {e["action"] for e in org_events["items"]} == {"organization.created"}
    # Newest first.
    timestamps = [e["timestamp"] for e in org_events["items"]]
    assert timestamps == sorted(timestamps, reverse=True)
    assert {e["action"] for e in user_events["items"]} == {"user.created"}
    assert by_id["total"] == 1


def test_api_requests_record_actor_and_correlation_id(client: TestClient, db: Session) -> None:
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR, "admin-one")

    client.post(
        "/api/v1/organizations",
        json={"name": "ATLAS Global Bank", "organization_type": "global_bank"},
        headers={**auth(admin), "X-Correlation-ID": "trace-org-1"},
    )
    page = client.get(f"{URL}?correlation_id=trace-org-1", headers=auth(admin)).json()

    [event] = page["items"]
    assert event["action"] == "organization.created"
    assert event["actor_id"] == str(admin.id)
    assert event["actor_username"] == "admin-one"
    assert event["metadata"]["organization_type"] == "global_bank"


def test_users_api_creates_audited_accounts_without_leaking_passwords(
    client: TestClient, db: Session
) -> None:
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    headers = auth(admin)
    body = {
        "username": "New.Auditor",
        "email": "new.auditor@atlasbank.example",
        "display_name": "New Auditor",
        "password": "a-long-enough-password",
        "role": "auditor",
    }

    created = client.post("/api/v1/users", json=body, headers=headers)
    duplicate = client.post("/api/v1/users", json=body, headers=headers)
    weak = client.post(
        "/api/v1/users", json={**body, "username": "weak", "password": "short"}, headers=headers
    )

    assert created.status_code == 201
    assert created.json()["username"] == "new.auditor"
    assert "password" not in created.text and "password_hash" not in created.json()
    assert duplicate.status_code == 409
    assert weak.status_code == 422
    event = db.execute(
        select(AuditEvent)
        .where(AuditEvent.action == "user.created")
        .where(AuditEvent.entity_id == created.json()["id"])
    ).scalar_one()
    assert event.actor_id == admin.id
    assert "a-long-enough-password" not in str(event.event_metadata)


def test_administrators_cannot_lock_themselves_out(client: TestClient, db: Session) -> None:
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    headers = auth(admin)

    deactivate = client.patch(
        f"/api/v1/users/{admin.id}", json={"is_active": False}, headers=headers
    )
    demote = client.patch(f"/api/v1/users/{admin.id}", json={"role": "auditor"}, headers=headers)

    assert deactivate.status_code == 422
    assert demote.status_code == 422
