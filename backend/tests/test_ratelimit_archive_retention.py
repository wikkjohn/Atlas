"""Phase 85: rate limits, the sign-in lockout, the audit-log archive and data retention."""

import gzip
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import ratelimit
from app.core.audit import AuditEvent
from app.core.errors import BusinessRuleViolation, RateLimitedError
from app.core.permissions import RoleCode
from app.modules.audit import archive
from app.modules.identity.models import AuthSession, SsoRequest, User
from tests.factories import PASSWORD, auth, make_user


@pytest.fixture
def archive_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "audit_archive_dir", tmp_path)
    return tmp_path


def _old_events(db: Session, count: int, when: datetime, action: str = "test.old") -> list:
    events = [
        AuditEvent(
            action=action,
            entity_type="test",
            entity_id=str(i),
            timestamp=when + timedelta(minutes=i),
            event_metadata={"n": i},
        )
        for i in range(count)
    ]
    db.add_all(events)
    db.flush()
    return events


def _login(client: TestClient, username: str, password: str):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


# --- Rate limits -------------------------------------------------------------------------------


def test_a_window_counts_and_refuses_over_the_limit(db: Session) -> None:
    now = datetime(2026, 11, 5, 12, 0, 30, tzinfo=UTC)
    for n in range(1, 11):
        assert ratelimit.hit(db, "login.user", "someone", now) == n
    with pytest.raises(RateLimitedError) as refused:
        ratelimit.hit(db, "login.user", "someone", now)
    # The 15-minute window started at 12:00; it ends at 12:15.
    assert refused.value.retry_after == 15 * 60 - 30
    # Another key, or the next window, starts again.
    assert ratelimit.hit(db, "login.user", "someone-else", now) == 1
    assert ratelimit.hit(db, "login.user", "someone", now + timedelta(minutes=15)) == 1


def test_sign_ins_are_rate_limited_per_account(client: TestClient, db: Session) -> None:
    user = make_user(db, RoleCode.BANKING_EMPLOYEE)
    db.commit()
    for _ in range(10):
        assert _login(client, user.username, PASSWORD).status_code == 200
    refused = _login(client, user.username, PASSWORD)
    assert refused.status_code == 429 and refused.json()["error"]["code"] == "rate_limited"
    assert int(refused.headers["Retry-After"]) > 0
    assert "sign-in attempts for this account" in refused.text


# --- Lockout -----------------------------------------------------------------------------------


def test_repeated_wrong_passwords_lock_the_account(client: TestClient, db: Session) -> None:
    user = make_user(db, RoleCode.BANKING_EMPLOYEE)
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    db.commit()
    for _ in range(4):
        assert _login(client, user.username, "wrong-password-x").status_code == 401
    db.refresh(user)
    assert user.failed_logins == 4 and user.locked_until is None
    fifth = _login(client, user.username, "wrong-password-x")
    assert fifth.status_code == 401
    db.refresh(user)
    assert user.locked_until is not None and user.failed_logins == 0
    # Locked: even the right password is refused, and says why.
    locked = _login(client, user.username, PASSWORD)
    assert locked.status_code == 401 and "locked after repeated failed sign-ins" in locked.text
    listed = client.get(f"/api/v1/users/{user.id}", headers=auth(admin)).json()
    assert listed["locked_until"] is not None
    actions = [
        e.action
        for e in db.execute(
            select(AuditEvent)
            .where(AuditEvent.entity_id == str(user.id))
            .order_by(AuditEvent.timestamp)
        ).scalars()
    ]
    assert "auth.locked" in actions
    reasons = [
        e.event_metadata.get("reason")
        for e in db.execute(
            select(AuditEvent).where(
                AuditEvent.action == "auth.login_failed", AuditEvent.entity_id == str(user.id)
            )
        ).scalars()
    ]
    assert reasons.count("bad_password") == 5 and "locked" in reasons

    unlocked = client.post(f"/api/v1/users/{user.id}/unlock", headers=auth(admin))
    assert unlocked.status_code == 200 and unlocked.json()["locked_until"] is None
    assert _login(client, user.username, PASSWORD).status_code == 200


def test_a_success_resets_the_count(client: TestClient, db: Session) -> None:
    user = make_user(db, RoleCode.BANKING_EMPLOYEE)
    db.commit()
    for _ in range(3):
        _login(client, user.username, "wrong-password-x")
    assert _login(client, user.username, PASSWORD).status_code == 200
    db.refresh(user)
    assert user.failed_logins == 0
    # A lock that has run out no longer refuses.
    user.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert _login(client, user.username, PASSWORD).status_code == 200


# --- The audit-log archive ---------------------------------------------------------------------


def test_the_audit_log_still_refuses_updates_and_deletes(db: Session) -> None:
    (event,) = _old_events(db, 1, datetime(2019, 1, 1, tzinfo=UTC))
    db.commit()
    for statement in (
        "UPDATE audit_events SET action = 'x' WHERE id = :id",
        "DELETE FROM audit_events WHERE id = :id",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            with db.begin_nested():
                db.execute(text(statement), {"id": event.id})


def test_old_events_move_to_a_verified_chain_of_archives(
    client: TestClient, db: Session, archive_dir
) -> None:
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    auditor = make_user(db, RoleCode.AUDITOR)
    first = _old_events(db, 5, datetime(2018, 3, 1, tzinfo=UTC))
    second = _old_events(db, 3, datetime(2018, 9, 1, tzinfo=UTC), action="test.later")
    recent = _old_events(db, 2, datetime.now(UTC) - timedelta(days=1), action="test.recent")
    db.commit()

    # Too recent a cut-off is refused: events stay online for 90 days at least.
    with pytest.raises(BusinessRuleViolation, match="at least 90 days"):
        archive.archive_before(db, datetime.now(UTC) - timedelta(days=10), admin.id)

    one = archive.archive_before(db, datetime(2018, 6, 1, tzinfo=UTC), admin.id)
    db.commit()
    assert one.events == 5 and one.previous_sha256 is None
    two = archive.archive_before(db, datetime(2019, 1, 1, tzinfo=UTC), admin.id)
    db.commit()
    assert two.events == 3 and two.previous_sha256 == one.sha256
    assert archive.archive_before(db, datetime(2019, 1, 1, tzinfo=UTC), admin.id) is None

    live = {
        e.id
        for e in db.execute(
            select(AuditEvent).where(AuditEvent.id.in_([e.id for e in first + second + recent]))
        ).scalars()
    }
    assert live == {e.id for e in recent}  # archived events left the table; recent ones stayed
    with gzip.open(archive_dir / one.location, "rt") as lines:
        archived = [json.loads(line) for line in lines]
    assert [a["id"] for a in archived] == [str(e.id) for e in first]
    assert archived[0]["metadata"] == {"n": 0} and archived[0]["action"] == "test.old"
    moved = db.execute(select(AuditEvent).where(AuditEvent.action == "audit.archived")).scalars()
    assert {m.event_metadata["events"] for m in moved} >= {5, 3}

    # Auditors read and verify archives through the API; only administrators archive.
    headers = auth(auditor)
    db.commit()
    listed = client.get("/api/v1/audit-archives", headers=headers).json()
    assert [a["archive_number"] for a in listed][:2] == [two.archive_number, one.archive_number]
    found = client.get(f"/api/v1/audit-archives/{one.id}/events?entity_id=3", headers=headers)
    assert found.json()["total"] == 1 and found.json()["items"][0]["metadata"] == {"n": 3}
    prefix = client.get(f"/api/v1/audit-archives/{two.id}/events?action=test.*", headers=headers)
    assert prefix.json()["total"] == 3
    ok = client.post(f"/api/v1/audit-archives/{two.id}/verify", headers=headers).json()
    assert ok == {"ok": True, "problems": [], "sha256": two.sha256, "events": 3}
    refused = client.post("/api/v1/audit-archives", json={"older_than_days": 400}, headers=headers)
    assert refused.status_code == 403

    # A tampered file, or a broken chain, shows when verified.
    with gzip.open(archive_dir / one.location, "at") as out:
        out.write('{"id": "forged"}\n')
    bad = client.post(f"/api/v1/audit-archives/{one.id}/verify", headers=headers).json()
    assert bad["ok"] is False and "digest does not match" in " ".join(bad["problems"])
    assert "holds 6 events" in " ".join(bad["problems"])
    db.execute(
        text("UPDATE audit_archives SET previous_sha256 = 'x' WHERE id = :id"), {"id": two.id}
    )
    db.commit()
    broken = client.post(f"/api/v1/audit-archives/{two.id}/verify", headers=headers).json()
    assert "chain is broken" in " ".join(broken["problems"])


# --- Retention ---------------------------------------------------------------------------------


def test_the_retention_review_and_its_application(
    client: TestClient, db: Session, archive_dir
) -> None:
    admin = make_user(db, RoleCode.PLATFORM_ADMINISTRATOR)
    auditor = make_user(db, RoleCode.AUDITOR)
    now = datetime.now(UTC)
    old = now - timedelta(days=200)
    db.add_all(
        [
            AuthSession(
                id=uuid.uuid4(),
                user_id=auditor.id,
                method="password",
                mfa="not_required",
                created_at=old,
                last_seen_at=old,
                expires_at=old + timedelta(hours=12),
            ),
            AuthSession(
                id=uuid.uuid4(),
                user_id=auditor.id,
                method="password",
                mfa="not_required",
                created_at=now,
                last_seen_at=now,
                expires_at=now + timedelta(hours=12),
            ),
            SsoRequest(
                state=uuid.uuid4().hex,
                nonce="n",
                provider="atlas-directory",
                created_at=now - timedelta(days=2),
                expires_at=now - timedelta(days=2),
            ),
        ]
    )
    db.execute(
        text("INSERT INTO rate_limit_counters VALUES ('test:old', :t, 3)"),
        {"t": now - timedelta(days=3)},
    )
    _old_events(db, 4, now - timedelta(days=500), action="test.ancient")
    db.commit()

    review = client.get("/api/v1/data-retention", headers=auth(auditor)).json()
    by_id = {c["id"]: c for c in review["classes"]}
    assert by_id["auth_sessions"]["due"] >= 1 and by_id["auth_sessions"]["action"] == "delete"
    assert by_id["sso_requests"]["due"] >= 1 and by_id["rate_limit_counters"]["due"] >= 1
    assert by_id["audit_events"]["due"] >= 4 and by_id["audit_events"]["action"] == "archive"
    assert by_id["customers"]["action"] == "keep" and by_id["customers"]["due"] == 0
    assert by_id["jobs"]["action"] == "review"
    assert client.post("/api/v1/data-retention/apply", headers=auth(auditor)).status_code == 403

    applied = client.post("/api/v1/data-retention/apply", headers=auth(admin))
    assert applied.status_code == 200, applied.text
    results = applied.json()["results"]
    assert results["auth_sessions"]["deleted"] >= 1 and results["sso_requests"]["deleted"] >= 1
    assert results["rate_limit_counters"]["deleted"] >= 1
    assert results["audit_events"]["archived"] >= 4
    after = {
        c["id"]: c
        for c in client.get("/api/v1/data-retention", headers=auth(auditor)).json()["classes"]
    }
    assert after["auth_sessions"]["due"] == after["sso_requests"]["due"] == 0
    assert after["audit_events"]["due"] == 0
    # The current session is untouched.
    assert (
        db.execute(
            select(func.count())
            .select_from(AuthSession)
            .where(AuthSession.user_id == auditor.id, AuthSession.created_at >= now)
        ).scalar_one()
        >= 1
    )
    last = client.get("/api/v1/data-retention", headers=auth(auditor)).json()["last_run"]
    assert last["results"]["audit_events"]["archived"] >= 4
    assert db.execute(select(User).where(User.id == admin.id)).scalar_one()
