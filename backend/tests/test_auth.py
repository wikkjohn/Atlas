"""Authentication: login, token validation, expiry and account state."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.audit import AuditEvent
from app.core.permissions import RoleCode
from app.core.security import create_access_token
from app.modules.identity.schemas import UserUpdate
from app.modules.identity.service import get_role, update_user
from tests.factories import PASSWORD, auth, make_user


def _audit(db: Session, action: str) -> list[AuditEvent]:
    return list(db.execute(select(AuditEvent).where(AuditEvent.action == action)).scalars())


def test_successful_login_returns_token_and_permissions(client: TestClient, db: Session) -> None:
    user = make_user(db, RoleCode.AI_RESEARCHER, "researcher")

    response = client.post(
        "/api/v1/auth/login", json={"username": "Researcher", "password": PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["username"] == "researcher"
    assert body["user"]["role"] == "ai_researcher"
    assert "organizations:read" in body["user"]["permissions"]
    assert "organizations:manage" not in body["user"]["permissions"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["id"] == str(user.id)
    assert me.json()["last_login_at"] is not None
    assert [e.actor_id for e in _audit(db, "auth.login")] == [user.id]


def test_invalid_password_is_rejected_and_audited(client: TestClient, db: Session) -> None:
    user = make_user(db, RoleCode.BANKING_EMPLOYEE, "teller")

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "teller", "password": "wrong-password"},
        headers={"X-Correlation-ID": "login-attempt-1"},
    )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.json()["error"]["message"] == "Invalid username or password."
    [failure] = _audit(db, "auth.login_failed")
    assert failure.actor_id == user.id
    assert failure.event_metadata["reason"] == "bad_password"
    assert failure.correlation_id == "login-attempt-1"
    assert "wrong-password" not in str(failure.event_metadata)


def test_unknown_user_gets_the_same_response(client: TestClient, db: Session) -> None:
    response = client.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"})

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid username or password."
    assert _audit(db, "auth.login_failed")[0].event_metadata["reason"] == "unknown_user"


def test_inactive_user_cannot_log_in(client: TestClient, db: Session) -> None:
    user = make_user(db, RoleCode.AUDITOR, "former-auditor")
    user.is_active = False
    db.flush()

    response = client.post(
        "/api/v1/auth/login", json={"username": "former-auditor", "password": PASSWORD}
    )

    assert response.status_code == 401


def test_protected_endpoint_requires_a_token(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Authentication required."


def test_malformed_and_forged_tokens_are_rejected(client: TestClient, db: Session) -> None:
    user = make_user(db, RoleCode.AUDITOR)
    forged = create_access_token(user.id, "some-other-secret-that-is-long-enough!!", timedelta(5))

    for token in ("not-a-jwt", forged.token):
        response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.json()["error"]["message"] == "Access token is invalid."


def test_expired_token_is_rejected(client: TestClient, db: Session) -> None:
    user = make_user(db, RoleCode.AUDITOR)
    expired = create_access_token(
        user.id,
        get_settings().jwt_secret.get_secret_value(),
        timedelta(minutes=5),
        now=datetime.now(UTC) - timedelta(hours=1),
    )

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired.token}"})

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Access token has expired."


def test_deactivation_revokes_existing_tokens(client: TestClient, db: Session) -> None:
    user = make_user(db, RoleCode.AUDITOR)
    headers = auth(user)
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    user.is_active = False
    db.flush()

    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_role_changes_apply_to_existing_tokens(client: TestClient, db: Session) -> None:
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    auditor = make_user(db, RoleCode.AUDITOR)
    headers = auth(auditor)
    assert client.get("/api/v1/audit-events", headers=headers).status_code == 200

    update_user(db, auditor, UserUpdate(role=RoleCode.BANKING_EMPLOYEE), admin.id)
    db.expire_all()

    assert client.get("/api/v1/audit-events", headers=headers).status_code == 403
    assert get_role(db, RoleCode.BANKING_EMPLOYEE).id == auditor.role_id
