"""Sign-in sessions (Phase 84).

A successful password or SSO sign-in creates a session. If the user has a second factor,
the session waits for it (`pending`) and the caller receives a short-lived challenge
instead of an access token. If the role requires a factor the user has not enrolled, the
session may only enrol (`enrolment_required`). Access tokens name their session; a revoked,
idle or expired session ends them at once, and a refresh never outlives the session.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.audit import record_audit_event
from app.core.errors import AuthenticationError, NotFoundError
from app.core.security import (
    MFA_CHALLENGE,
    IssuedToken,
    TokenClaims,
    create_access_token,
    decode_access_token,
)
from app.modules.identity import mfa
from app.modules.identity.models import AuthSession, SessionMethod, SessionMfa, User

CHALLENGE_TTL = timedelta(minutes=5)
MAX_MFA_ATTEMPTS = 5
# A session's last use is written at most this often, not on every request.
TOUCH_INTERVAL = timedelta(seconds=60)


@dataclass(frozen=True)
class RequestMeta:
    ip_address: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True)
class SignIn:
    """The outcome of a first factor: an access token, or a second-factor challenge."""

    session: AuthSession
    access: IssuedToken | None = None
    challenge: IssuedToken | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _secret(settings: Settings) -> str:
    return settings.jwt_secret.get_secret_value()


def requires_mfa(user: User, settings: Settings) -> bool:
    return user.role.code in settings.mfa_required_roles


def access_token(
    session: AuthSession, settings: Settings, now: datetime | None = None
) -> IssuedToken:
    """An access token for `session`, never valid past the session's own end."""
    now = now or _now()
    ttl = min(timedelta(minutes=settings.access_token_ttl_minutes), session.expires_at - now)
    return create_access_token(session.user_id, _secret(settings), ttl, now, session_id=session.id)


def start(
    db: Session,
    user: User,
    settings: Settings,
    *,
    method: str,
    provider: str | None = None,
    factor_asserted: bool = False,
    meta: RequestMeta | None = None,
) -> SignIn:
    """Open a session after the first factor. `factor_asserted`: an identity provider has
    already checked a second factor (SSO with `amr` including `otp`)."""
    now = _now()
    if factor_asserted:
        state = SessionMfa.VERIFIED
    elif mfa.enabled(user):
        state = SessionMfa.PENDING
    elif requires_mfa(user, settings):
        state = SessionMfa.ENROLMENT_REQUIRED
    else:
        state = SessionMfa.NOT_REQUIRED
    meta = meta or RequestMeta()
    session = AuthSession(
        id=uuid.uuid4(),
        user_id=user.id,
        method=method,
        provider=provider,
        mfa=state,
        ip_address=meta.ip_address,
        user_agent=(meta.user_agent or "")[:300] or None,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_absolute_hours),
    )
    db.add(session)
    db.flush()
    record_audit_event(
        db, actor_id=user.id, action="auth.session_started", entity_type="auth_session",
        entity_id=session.id, metadata={"method": method, "provider": provider, "mfa": state},
    )  # fmt: skip
    if state == SessionMfa.PENDING:
        challenge = create_access_token(
            user.id, _secret(settings), CHALLENGE_TTL, now, session_id=session.id,
            token_type=MFA_CHALLENGE,
        )  # fmt: skip
        return SignIn(session=session, challenge=challenge)
    user.last_login_at = now
    return SignIn(session=session, access=access_token(session, settings, now))


def revoke(db: Session, session: AuthSession, reason: str, actor_id: uuid.UUID | None) -> None:
    if session.revoked_at is not None:
        return
    session.revoked_at = _now()
    session.revoked_reason = reason
    record_audit_event(
        db, actor_id=actor_id, action="auth.session_revoked", entity_type="auth_session",
        entity_id=session.id, metadata={"user_id": str(session.user_id), "reason": reason},
    )  # fmt: skip


def revoke_all(
    db: Session, user_id: uuid.UUID, reason: str, actor_id: uuid.UUID | None,
    *, keep: uuid.UUID | None = None,
) -> int:  # fmt: skip
    """End every active session of the user (but `keep`); returns how many."""
    active = db.execute(
        select(AuthSession).where(
            AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
        )
    ).scalars().all()  # fmt: skip
    count = 0
    for session in active:
        if session.id != keep:
            revoke(db, session, reason, actor_id)
            count += 1
    return count


def _end_reason(session: AuthSession, settings: Settings, now: datetime) -> str | None:
    if session.revoked_at is not None:
        return "revoked"
    if session.expires_at <= now:
        return "expired"
    if session.last_seen_at + timedelta(minutes=settings.session_idle_minutes) <= now:
        return "idle"
    return None


_MESSAGES = {
    "revoked": "This session has been signed out.",
    "expired": "This session has expired.",
    "idle": "This session ended after a period of inactivity.",
}


def validate(db: Session, claims: TokenClaims, settings: Settings) -> AuthSession:
    """The live session behind an access token; refreshes its last use."""
    if claims.session_id is None:
        raise AuthenticationError("Access token is invalid.")
    session = db.get(AuthSession, claims.session_id)
    if session is None or session.user_id != claims.user_id:
        raise AuthenticationError("Access token is invalid.")
    now = _now()
    reason = _end_reason(session, settings, now)
    if reason is not None:
        if reason in ("expired", "idle"):
            # Recorded so the session list says why it ended; committed separately because
            # the failed request is rolled back.
            db.execute(
                update(AuthSession)
                .where(AuthSession.id == session.id, AuthSession.revoked_at.is_(None))
                .values(revoked_at=now, revoked_reason=reason)
            )
            db.commit()
        raise AuthenticationError(_MESSAGES[reason])
    if session.mfa == SessionMfa.PENDING:
        raise AuthenticationError("The second factor has not been verified.")
    if now - session.last_seen_at >= TOUCH_INTERVAL:
        session.last_seen_at = now
    return session


def verify_challenge(
    db: Session, challenge_token: str, code: str, settings: Settings
) -> tuple[User, AuthSession, IssuedToken]:
    """Complete a sign-in with the second factor (a TOTP or a recovery code)."""
    claims = decode_access_token(challenge_token, _secret(settings), token_type=MFA_CHALLENGE)
    session = db.get(AuthSession, claims.session_id) if claims.session_id else None
    if (
        session is None or session.user_id != claims.user_id or session.revoked_at is not None
        or session.mfa != SessionMfa.PENDING
    ):  # fmt: skip
        raise AuthenticationError("This sign-in can no longer be completed; sign in again.")
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("User account is not active.")
    kind = mfa.verify(user, code)
    if kind is None:
        session.failed_mfa_attempts += 1
        exhausted = session.failed_mfa_attempts >= MAX_MFA_ATTEMPTS
        if exhausted:
            revoke(db, session, "mfa_failed", user.id)
        record_audit_event(
            db, actor_id=user.id, action="auth.mfa_failed", entity_type="auth_session",
            entity_id=session.id, metadata={"attempts": session.failed_mfa_attempts},
        )  # fmt: skip
        db.commit()  # the error rolls the request back; the attempt must count
        raise AuthenticationError(
            "Too many wrong codes; sign in again." if exhausted else "The code is not valid."
        )
    session.mfa = SessionMfa.VERIFIED
    user.last_login_at = _now()
    record_audit_event(
        db, actor_id=user.id, action="auth.mfa_verified", entity_type="auth_session",
        entity_id=session.id, metadata={"factor": kind},
    )  # fmt: skip
    return user, session, access_token(session, settings)


def get_own(db: Session, user_id: uuid.UUID, session_id: uuid.UUID) -> AuthSession:
    session = db.get(AuthSession, session_id)
    if session is None or session.user_id != user_id:
        raise NotFoundError("Session not found.")
    return session


def list_for(db: Session, user_id: uuid.UUID, *, limit: int = 50) -> list[AuthSession]:
    return list(
        db.execute(
            select(AuthSession)
            .where(AuthSession.user_id == user_id)
            .order_by(AuthSession.revoked_at.is_not(None), AuthSession.created_at.desc())
            .limit(limit)
        ).scalars()
    )


def issue_for(db: Session, user: User, settings: Settings) -> str:
    """A session and access token without a sign-in (tests and the performance suite)."""
    now = _now()
    session = AuthSession(
        id=uuid.uuid4(), user_id=user.id, method=SessionMethod.PASSWORD,
        mfa=SessionMfa.NOT_REQUIRED, created_at=now, last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_absolute_hours),
    )  # fmt: skip
    db.add(session)
    db.flush()
    return access_token(session, settings, now).token
