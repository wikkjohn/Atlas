"""The TOTP second factor (Phase 84): enrolment, verification, recovery codes, reset.

Enrolment is two steps: a secret is issued (shown once, with an `otpauth://` URI for an
authenticator app) and becomes the user's factor only when a code from it is confirmed.
Confirming returns eight one-time recovery codes, stored hashed. A code is never accepted
twice: the last accepted time step is kept.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core import totp
from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation
from app.modules.identity.models import AuthSession, SessionMfa, User


def enabled(user: User) -> bool:
    return user.mfa_secret is not None


def _now() -> datetime:
    return datetime.now(UTC)


def verify(user: User, code: str) -> str | None:
    """Check `code` against the user's factor and consume it: "totp", "recovery" or None."""
    if not enabled(user):
        return None
    step = totp.matching_step(user.mfa_secret, code, last_step=user.mfa_last_step)
    if step is not None:
        user.mfa_last_step = step
        return "totp"
    digest = totp.recovery_hash(code)
    codes = [dict(c) for c in user.mfa_recovery_codes or []]
    for entry in codes:
        if entry["used_at"] is None and entry["hash"] == digest:
            entry["used_at"] = _now().isoformat()
            user.mfa_recovery_codes = codes  # reassigned so the change is saved
            return "recovery"
    return None


def begin_enrolment(db: Session, user: User) -> tuple[str, str]:
    """A new secret awaiting confirmation; returns it with its provisioning URI."""
    if enabled(user):
        raise BusinessRuleViolation("A second factor is already enrolled; remove it first.")
    secret = totp.new_secret()
    user.mfa_pending_secret = secret
    record_audit_event(
        db, actor_id=user.id, action="auth.mfa_enrolment_started", entity_type="user",
        entity_id=user.id,
    )  # fmt: skip
    return secret, totp.provisioning_uri(secret, user.username)


def confirm_enrolment(db: Session, user: User, code: str, session: AuthSession) -> list[str]:
    """Make the pending secret the user's factor; returns the recovery codes (shown once).
    The session that confirmed it counts as verified."""
    if enabled(user):
        raise BusinessRuleViolation("A second factor is already enrolled.")
    if user.mfa_pending_secret is None:
        raise BusinessRuleViolation("Start the enrolment first.")
    step = totp.matching_step(user.mfa_pending_secret, code, last_step=None)
    if step is None:
        raise BusinessRuleViolation("The code does not match; check the authenticator's clock.")
    codes = totp.new_recovery_codes()
    user.mfa_secret = user.mfa_pending_secret
    user.mfa_pending_secret = None
    user.mfa_enabled_at = _now()
    user.mfa_last_step = step
    user.mfa_recovery_codes = [{"hash": totp.recovery_hash(c), "used_at": None} for c in codes]
    session.mfa = SessionMfa.VERIFIED
    record_audit_event(
        db, actor_id=user.id, action="auth.mfa_enrolled", entity_type="user", entity_id=user.id
    )
    return codes


def regenerate_recovery_codes(db: Session, user: User, code: str) -> list[str]:
    if verify(user, code) != "totp":
        raise BusinessRuleViolation("Enter a current code from the authenticator.")
    codes = totp.new_recovery_codes()
    user.mfa_recovery_codes = [{"hash": totp.recovery_hash(c), "used_at": None} for c in codes]
    record_audit_event(
        db, actor_id=user.id, action="auth.mfa_recovery_codes_regenerated", entity_type="user",
        entity_id=user.id,
    )  # fmt: skip
    return codes


def clear(db: Session, user: User, actor_id, *, reason: str) -> None:
    """Remove the factor (by the user with a code, or reset by an administrator)."""
    user.mfa_secret = None
    user.mfa_pending_secret = None
    user.mfa_enabled_at = None
    user.mfa_last_step = None
    user.mfa_recovery_codes = []
    record_audit_event(
        db, actor_id=actor_id, action="auth.mfa_removed", entity_type="user", entity_id=user.id,
        metadata={"reason": reason},
    )  # fmt: skip


def recovery_codes_left(user: User) -> int:
    return sum(1 for c in user.mfa_recovery_codes or [] if c["used_at"] is None)
