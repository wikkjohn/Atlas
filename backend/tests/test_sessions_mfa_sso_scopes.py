"""Phase 84: sign-in sessions, the TOTP second factor, simulated SSO and scoped access."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import totp
from app.core.permissions import RoleCode
from app.core.security import create_access_token
from app.modules.identity import sso
from app.modules.identity.models import AuthSession, User
from app.modules.organizations.models import OrganizationType
from tests.factories import (
    PASSWORD,
    auth,
    make_customer,
    make_employee,
    make_org,
    make_org_tree,
    make_staff,
    make_user,
    open_account,
)


def _login(client: TestClient, user: User, password: str = PASSWORD) -> dict:
    response = client.post(
        "/api/v1/auth/login", json={"username": user.username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _code(secret: str, offset: int = 0) -> str:
    return totp.code_at(secret, totp.current_step() + offset)


def _enrol(client: TestClient, headers: dict[str, str]) -> tuple[str, list[str]]:
    started = client.post("/api/v1/auth/mfa/enrol", headers=headers)
    assert started.status_code == 200, started.text
    secret = started.json()["secret"]
    assert started.json()["provisioning_uri"].startswith("otpauth://totp/")
    confirmed = client.post(
        "/api/v1/auth/mfa/confirm", json={"code": _code(secret)}, headers=headers
    )
    assert confirmed.status_code == 200, confirmed.text
    return secret, confirmed.json()["recovery_codes"]


# --- TOTP ------------------------------------------------------------------------------------


def test_totp_matches_the_rfc_6238_test_vector() -> None:
    # RFC 6238 appendix B, SHA-1: the ASCII secret "12345678901234567890" at T = 59 s.
    import base64

    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    assert totp.code_at(secret, 59 // 30) == "287082"  # the low six digits of 94287082
    assert totp.code_at(secret, 1111111109 // 30) == "081804"
    step = totp.matching_step(secret, "287082", last_step=None, now=59)
    assert step == 1
    assert totp.matching_step(secret, "287082", last_step=1, now=59) is None  # no replay
    assert totp.matching_step(secret, "28708", last_step=None, now=59) is None


# --- Sessions --------------------------------------------------------------------------------


def test_sign_in_opens_a_session_that_signing_out_ends(client: TestClient, db: Session) -> None:
    user = make_user(db, RoleCode.BANKING_EMPLOYEE)
    db.commit()
    signed_in = _login(client, user)
    assert signed_in["status"] == "signed_in"
    headers = _bearer(signed_in["access_token"])
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert me["session"]["method"] == "password" and me["session"]["mfa"] == "not_required"
    assert me["scope"] == {"countries": None, "departments": None}

    # A second sign-in is a second session; ending the other one leaves this one.
    other = _bearer(_login(client, user)["access_token"])
    listed = client.get("/api/v1/auth/sessions", headers=headers).json()
    assert len(listed) == 2 and sum(s["current"] for s in listed) == 1
    assert client.post("/api/v1/auth/sessions/revoke-others", headers=headers).json() == {
        "revoked": 1
    }
    assert client.get("/api/v1/auth/me", headers=other).status_code == 401

    refreshed = client.post("/api/v1/auth/refresh", headers=headers)
    assert refreshed.status_code == 200 and refreshed.json()["access_token"]
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    gone = client.get("/api/v1/auth/me", headers=headers)
    assert gone.status_code == 401 and "signed out" in gone.text
    # The refreshed token named the same session, so it ended too.
    assert (
        client.get("/api/v1/auth/me", headers=_bearer(refreshed.json()["access_token"])).status_code
        == 401
    )


def test_tokens_without_a_live_session_are_refused(client: TestClient, db: Session) -> None:
    user = make_user(db, RoleCode.BANKING_EMPLOYEE)
    db.commit()
    secret = get_settings().jwt_secret.get_secret_value()
    sessionless = create_access_token(user.id, secret, timedelta(minutes=5)).token
    assert client.get("/api/v1/auth/me", headers=_bearer(sessionless)).status_code == 401

    headers = _bearer(_login(client, user)["access_token"])
    session = db.execute(select(AuthSession).where(AuthSession.user_id == user.id)).scalar_one()
    session.last_seen_at = datetime.now(UTC) - timedelta(minutes=31)  # the idle limit is 30
    db.commit()
    idle = client.get("/api/v1/auth/me", headers=headers)
    assert idle.status_code == 401 and "inactivity" in idle.text
    db.refresh(session)
    assert session.revoked_reason == "idle"

    headers = _bearer(_login(client, user)["access_token"])
    latest = db.execute(
        select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
    ).scalar_one()
    latest.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert "expired" in client.get("/api/v1/auth/me", headers=headers).text

    # Deactivating a user ends their sessions.
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    db.commit()
    headers = _bearer(_login(client, user)["access_token"])
    assert (
        client.patch(
            f"/api/v1/users/{user.id}", json={"is_active": False}, headers=auth(admin)
        ).status_code
        == 200
    )
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    reasons = {
        s["revoked_reason"]
        for s in client.get(f"/api/v1/users/{user.id}/sessions", headers=auth(admin)).json()
    }
    assert {"idle", "expired", "deactivated"} <= reasons


# --- Second factor ---------------------------------------------------------------------------


def test_enrolled_users_sign_in_with_a_code(client: TestClient, db: Session) -> None:
    user = make_user(db, RoleCode.BANKING_EMPLOYEE)
    db.commit()
    first = _bearer(_login(client, user)["access_token"])
    second = _bearer(_login(client, user)["access_token"])
    secret, recovery = _enrol(client, first)
    assert len(recovery) == 8 and len(set(recovery)) == 8
    # Enrolling signs the other sessions out; the enrolling one counts as verified.
    assert client.get("/api/v1/auth/me", headers=second).status_code == 401
    me = client.get("/api/v1/auth/me", headers=first).json()
    assert me["mfa_enabled"] and me["session"]["mfa"] == "verified"
    assert me["mfa_recovery_codes_left"] == 8

    challenge = _login(client, user)
    assert challenge["status"] == "mfa_required" and challenge["access_token"] is None
    token = challenge["challenge_token"]
    # The challenge is not an access token.
    assert client.get("/api/v1/auth/me", headers=_bearer(token)).status_code == 401
    wrong = client.post(
        "/api/v1/auth/mfa/verify", json={"challenge_token": token, "code": "000000"}
    )
    assert wrong.status_code == 401 and "not valid" in wrong.text
    good = client.post(
        "/api/v1/auth/mfa/verify", json={"challenge_token": token, "code": _code(secret, 1)}
    )
    assert good.status_code == 200, good.text
    assert good.json()["user"]["session"]["mfa"] == "verified"

    # The same code never works twice; a recovery code works once.
    again = _login(client, user)["challenge_token"]
    assert (
        client.post(
            "/api/v1/auth/mfa/verify", json={"challenge_token": again, "code": _code(secret, 1)}
        ).status_code
        == 401
    )
    used = client.post(
        "/api/v1/auth/mfa/verify", json={"challenge_token": again, "code": recovery[0].lower()}
    )
    assert used.status_code == 200
    third = _login(client, user)["challenge_token"]
    assert (
        client.post(
            "/api/v1/auth/mfa/verify", json={"challenge_token": third, "code": recovery[0]}
        ).status_code
        == 401
    )
    me = client.get("/api/v1/auth/me", headers=_bearer(used.json()["access_token"])).json()
    assert me["mfa_recovery_codes_left"] == 7


def test_five_wrong_codes_end_the_sign_in(client: TestClient, db: Session) -> None:
    user = make_user(db, RoleCode.BANKING_EMPLOYEE)
    db.commit()
    secret, _ = _enrol(client, _bearer(_login(client, user)["access_token"]))
    token = _login(client, user)["challenge_token"]
    for _ in range(5):
        client.post("/api/v1/auth/mfa/verify", json={"challenge_token": token, "code": "123456"})
    late = client.post(
        "/api/v1/auth/mfa/verify", json={"challenge_token": token, "code": _code(secret)}
    )
    assert late.status_code == 401 and "sign in again" in late.text


def test_a_role_that_requires_mfa_can_only_enrol_until_it_has(
    app, client: TestClient, db: Session
) -> None:
    settings = get_settings().model_copy(update={"mfa_required_roles": ["platform_administrator"]})
    app.dependency_overrides[get_settings] = lambda: settings
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    other = make_user(db, RoleCode.BANKING_EMPLOYEE)
    db.commit()
    signed_in = _login(client, admin)
    assert signed_in["user"]["mfa_enrolment_required"] is True
    headers = _bearer(signed_in["access_token"])
    blocked = client.get("/api/v1/users", headers=headers)
    assert blocked.status_code == 403 and "enrol" in blocked.text
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    secret, _ = _enrol(client, headers)
    assert client.get("/api/v1/users", headers=headers).status_code == 200
    # The factor cannot be removed while the role requires it; other roles are unaffected.
    removed = client.post(
        "/api/v1/auth/mfa/remove", json={"code": _code(secret, 1)}, headers=headers
    )
    assert removed.status_code == 422
    assert _login(client, other)["user"]["mfa_enrolment_required"] is False

    # An administrator resets a lost factor: it is gone and the user is signed out.
    peer = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    db.commit()
    peer_headers = _bearer(_login(client, peer)["access_token"])
    _enrol(client, peer_headers)
    assert client.post(f"/api/v1/users/{peer.id}/mfa/reset", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=peer_headers).status_code == 401
    assert _login(client, peer)["user"]["mfa_enrolment_required"] is True
    own = client.post(f"/api/v1/users/{admin.id}/mfa/reset", headers=headers)
    assert own.status_code == 422


# --- Simulated SSO ---------------------------------------------------------------------------


def _sso(client: TestClient, user: User, *, otp: str | None = None) -> tuple[dict, dict]:
    start = client.post("/api/v1/auth/sso/atlas-directory/start").json()
    token = client.post(
        "/api/v1/simulated-directory/atlas-directory/sign-in",
        json={"nonce": start["nonce"], "username": user.username, "password": PASSWORD, "otp": otp},
    )
    assert token.status_code == 200, token.text
    return start, token.json()


def test_single_sign_on_through_the_simulated_directory(client: TestClient, db: Session) -> None:
    user = make_user(db, RoleCode.BANKING_EMPLOYEE)
    db.commit()
    assert client.get("/api/v1/auth/sso/providers").json() == [
        {"id": "atlas-directory", "name": "ATLAS Corporate Directory", "simulated": True}
    ]
    start, token = _sso(client, user)
    body = {"state": start["state"], "id_token": token["id_token"]}
    signed_in = client.post("/api/v1/auth/sso/atlas-directory/callback", json=body)
    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json()["user"]["session"]["method"] == "sso"
    assert signed_in.json()["user"]["session"]["provider"] == "atlas-directory"
    # A state is used once.
    replay = client.post("/api/v1/auth/sso/atlas-directory/callback", json=body)
    assert replay.status_code == 401 and "used" in replay.text

    # A token for another sign-in's nonce, a tampered token, an unknown provider: refused.
    other_start, _ = _sso(client, user)
    _, stale = _sso(client, user)
    mismatched = client.post(
        "/api/v1/auth/sso/atlas-directory/callback",
        json={"state": other_start["state"], "id_token": stale["id_token"]},
    )
    assert mismatched.status_code == 401
    forged_start = client.post("/api/v1/auth/sso/atlas-directory/start").json()
    forged = jwt.encode(
        {
            "iss": sso.PROVIDERS["atlas-directory"]["issuer"],
            "aud": sso.CLIENT_ID,
            "sub": str(user.id),
            "email": user.email,
            "nonce": forged_start["nonce"],
            "amr": ["pwd", "otp"],
            "iat": 0,
            "exp": 2_000_000_000,
        },
        "not-the-directory-key-but-long-enough-to-sign",
        algorithm="HS256",
    )
    assert (
        client.post(
            "/api/v1/auth/sso/atlas-directory/callback",
            json={"state": forged_start["state"], "id_token": forged},
        ).status_code
        == 401
    )
    assert client.post("/api/v1/auth/sso/nowhere/start").status_code == 404
    bad = client.post(
        "/api/v1/simulated-directory/atlas-directory/sign-in",
        json={"nonce": "n", "username": user.username, "password": "wrong-one"},
    )
    assert bad.status_code == 401


def test_a_directory_that_checked_the_factor_satisfies_the_bank(
    client: TestClient, db: Session
) -> None:
    user = make_user(db, RoleCode.BANKING_EMPLOYEE)
    db.commit()
    secret, _ = _enrol(client, _bearer(_login(client, user)["access_token"]))
    # Without the code at the directory, the bank asks for its own.
    start, token = _sso(client, user)
    owed = client.post(
        "/api/v1/auth/sso/atlas-directory/callback",
        json={"state": start["state"], "id_token": token["id_token"]},
    ).json()
    assert owed["status"] == "mfa_required"
    start, token = _sso(client, user, otp=_code(secret, 1))
    assert jwt.decode(token["id_token"], options={"verify_signature": False})["amr"] == [
        "pwd",
        "otp",
    ]
    done = client.post(
        "/api/v1/auth/sso/atlas-directory/callback",
        json={"state": start["state"], "id_token": token["id_token"]},
    ).json()
    assert done["status"] == "signed_in" and done["user"]["session"]["mfa"] == "verified"


# --- Scoped access ---------------------------------------------------------------------------


@pytest.fixture
def scoped(client: TestClient, db: Session):
    tree = make_org_tree(db)
    staff = make_staff(db)
    gb = make_customer(db, country_code="GB", name="Customer In Britain")
    jp = make_customer(db, country_code="JP", name="Customer In Japan")
    jp_account = open_account(db, staff, jp)
    db.commit()
    admin = auth(staff.admin)
    response = client.put(
        f"/api/v1/users/{staff.employee.id}/scopes", json={"countries": ["gb"]}, headers=admin
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"countries": ["GB"], "departments": None}
    return tree, staff, gb, jp, jp_account, admin


def test_a_country_scope_limits_customers_and_accounts(client: TestClient, db: Session, scoped):
    _, staff, gb, jp, jp_account, admin = scoped
    teller = auth(staff.employee)
    names = [
        c["name"] for c in client.get("/api/v1/customers?limit=200", headers=teller).json()["items"]
    ]
    assert "Customer In Britain" in names and "Customer In Japan" not in names
    assert client.get(f"/api/v1/customers/{gb.id}", headers=teller).status_code == 200
    # Outside the scope a record does not exist for the user; acting on it is refused alike.
    assert client.get(f"/api/v1/customers/{jp.id}", headers=teller).status_code == 404
    assert client.get(f"/api/v1/accounts/{jp_account.id}", headers=teller).status_code == 404
    deposit = client.post(
        f"/api/v1/accounts/{jp_account.id}/deposits",
        json={"amount": 100, "memo": "test"},
        headers={**teller, "Idempotency-Key": "scope-dep-1"},
    )
    assert deposit.status_code == 404
    request = client.post(
        "/api/v1/account-requests",
        json={"customer_id": str(jp.id), "account_type": "savings"},
        headers=teller,
    )
    assert request.status_code == 404
    accounts = client.get("/api/v1/accounts?limit=200", headers=teller).json()["items"]
    assert all(a["id"] != str(jp_account.id) for a in accounts)
    onboard = client.post(
        "/api/v1/customers",
        json={
            "customer_type": "individual",
            "name": "New In Japan",
            "date_of_birth_or_incorporation": "1990-01-01",
            "country_id": str(jp.country_id),
        },
        headers=teller,
    )
    assert onboard.status_code == 403 and "limited to GB" in onboard.text
    # Unscoped users see everything; the scope is on the user's record and in the audit log.
    assert client.get(f"/api/v1/customers/{jp.id}", headers=auth(staff.manager)).status_code == 200
    me = client.get("/api/v1/auth/me", headers=teller).json()
    assert me["scope"] == {"countries": ["GB"], "departments": None}
    audit = client.get("/api/v1/audit-events?action=user.scopes_changed", headers=admin).json()
    assert audit["items"][0]["metadata"]["after"]["countries"] == ["GB"]


def test_a_department_scope_limits_employees(client: TestClient, db: Session, scoped):
    tree, staff, *_ = scoped
    payments = make_org(db, "Payments Operations", OrganizationType.DEPARTMENT, tree.us_retail)
    onboarding = make_employee(db, tree.us_onboarding, first_name="Onboarding")
    in_payments = make_employee(db, payments, first_name="Payments")
    hr = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)  # may hire
    db.commit()
    admin = auth(staff.admin)
    assert (
        client.put(
            f"/api/v1/users/{hr.id}/scopes",
            json={"departments": ["Payments Operations"]},
            headers=admin,
        ).status_code
        == 200
    )
    headers = auth(hr)
    listed = client.get("/api/v1/employees?limit=200", headers=headers).json()["items"]
    assert {e["id"] for e in listed} == {str(in_payments.id)}
    assert client.get(f"/api/v1/employees/{onboarding.id}", headers=headers).status_code == 404
    hire = client.post(
        "/api/v1/employees",
        headers=headers,
        json={
            "first_name": "Outside",
            "last_name": "Scope",
            "organization_id": str(tree.us_onboarding.id),
            "job_title": "Analyst",
            "role": "banking_employee",
            "annual_compensation": 1,
        },
    )
    assert hire.status_code == 403 and "Payments Operations" in hire.text

    # Validation, and a scoped administrator cannot hand out scopes.
    for body in ({"countries": ["XX"]}, {"departments": ["No Such Department"]}):
        assert (
            client.put(f"/api/v1/users/{hr.id}/scopes", json=body, headers=admin).status_code == 422
        )
    scoped_admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    db.commit()
    client.put(f"/api/v1/users/{scoped_admin.id}/scopes", json={"countries": ["US"]}, headers=admin)
    refused = client.put(
        f"/api/v1/users/{hr.id}/scopes", json={"countries": []}, headers=auth(scoped_admin)
    )
    assert refused.status_code == 422
    cleared = client.put(f"/api/v1/users/{hr.id}/scopes", json={}, headers=admin)
    assert cleared.json() == {"countries": None, "departments": None}
    assert len(client.get("/api/v1/employees?limit=200", headers=headers).json()["items"]) >= 2
