"""Simulated single sign-on (Phase 84).

The bank trusts one simulated corporate identity provider, the ATLAS Corporate Directory.
The flow follows OpenID Connect's shape:

1. The bank starts a sign-in: a random `state` and `nonce`, stored, valid for 10 minutes.
2. The directory authenticates the employee (here: the same synthetic credentials, and the
   TOTP factor when one is enrolled) and returns a signed ID token: issuer, audience (the
   bank), subject, email, the nonce, and `amr` (the methods used: `pwd`, plus `otp` when a
   second factor was checked).
3. The bank's callback accepts the token only with the stored, unused, unexpired state, a
   valid signature from the directory's key, the right issuer and audience, an unexpired
   token and the matching nonce; then it signs the matching user in. A directory that
   checked a second factor satisfies the bank's; otherwise the bank asks for its own.

The directory is simulated: it runs inside the API and signs with a key derived from the
bank's secret. A real one would be a separate system with its own published keys.
"""

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.audit import record_audit_event
from app.core.errors import AuthenticationError, NotFoundError
from app.core.security import DUMMY_PASSWORD_HASH, TOKEN_ISSUER, verify_password
from app.modules.identity import mfa, sessions
from app.modules.identity.models import SessionMethod, SsoRequest, User

PROVIDERS: dict[str, dict[str, str]] = {
    "atlas-directory": {
        "name": "ATLAS Corporate Directory",
        "issuer": "https://directory.atlas-global-bank.example/simulated",
    },
}
CLIENT_ID = TOKEN_ISSUER  # the bank, as the directory knows it
REQUEST_TTL = timedelta(minutes=10)
ID_TOKEN_TTL = timedelta(minutes=5)


def _provider(provider: str) -> dict[str, str]:
    if provider not in PROVIDERS:
        raise NotFoundError(f"No identity provider '{provider}'.")
    return PROVIDERS[provider]


def _directory_key(provider: str, settings: Settings) -> bytes:
    return hmac.new(
        settings.jwt_secret.get_secret_value().encode(), f"sim-idp:{provider}".encode(),
        hashlib.sha256,
    ).digest()  # fmt: skip


def providers() -> list[dict]:
    return [{"id": k, "name": v["name"], "simulated": True} for k, v in PROVIDERS.items()]


def start(db: Session, provider: str) -> SsoRequest:
    _provider(provider)
    now = datetime.now(UTC)
    request = SsoRequest(
        state=secrets.token_urlsafe(24), nonce=secrets.token_urlsafe(24), provider=provider,
        created_at=now, expires_at=now + REQUEST_TTL,
    )  # fmt: skip
    db.add(request)
    db.flush()
    return request


def directory_sign_in(
    db: Session, provider: str, *, nonce: str, username: str, password: str,
    otp: str | None, settings: Settings,
) -> str:  # fmt: skip
    """The simulated directory: authenticate the employee and sign an ID token."""
    info = _provider(provider)
    user = db.execute(
        select(User).where(User.username == username.strip().lower())
    ).scalar_one_or_none()
    password_ok = verify_password(password, user.password_hash if user else DUMMY_PASSWORD_HASH)
    if user is None or not password_ok or not user.is_active:
        record_audit_event(
            db, actor_id=user.id if user else None, action="sso.directory_login_failed",
            entity_type="user", entity_id=user.id if user else None,
            metadata={"provider": provider, "username": username[:64]},
        )  # fmt: skip
        db.commit()
        raise AuthenticationError("The directory rejected the username or password.")
    amr = ["pwd"]
    if otp and mfa.enabled(user):
        if mfa.verify(user, otp) is None:
            db.commit()  # keep the consumed step out of reach either way
            raise AuthenticationError("The directory rejected the one-time code.")
        amr.append("otp")
    now = datetime.now(UTC)
    claims = {
        "iss": info["issuer"], "aud": CLIENT_ID, "sub": str(user.id), "email": user.email,
        "name": user.display_name, "nonce": nonce, "amr": amr,
        "iat": int(now.timestamp()), "exp": int((now + ID_TOKEN_TTL).timestamp()),
        "jti": secrets.token_hex(8),
    }  # fmt: skip
    return jwt.encode(claims, _directory_key(provider, settings), algorithm="HS256")


def callback(
    db: Session, provider: str, *, state: str, id_token: str, settings: Settings,
    meta: sessions.RequestMeta | None = None,
) -> tuple[User, sessions.SignIn]:  # fmt: skip
    """The bank's side: check the request and the token, then sign the user in."""
    info = _provider(provider)
    now = datetime.now(UTC)
    request = db.get(SsoRequest, state, with_for_update=True)
    if (
        request is None or request.provider != provider or request.used_at is not None
        or request.expires_at <= now
    ):  # fmt: skip
        raise AuthenticationError("This single sign-on request is unknown, used or expired.")
    request.used_at = now
    try:
        claims = jwt.decode(
            id_token, _directory_key(provider, settings), algorithms=["HS256"],
            audience=CLIENT_ID, issuer=info["issuer"],
            options={"require": ["iss", "aud", "sub", "exp", "iat", "nonce"]},
        )  # fmt: skip
    except jwt.InvalidTokenError as exc:
        db.commit()  # the request stays used
        raise AuthenticationError("The identity provider's token is not valid.") from exc
    if not hmac.compare_digest(str(claims["nonce"]), request.nonce):
        db.commit()
        raise AuthenticationError("The identity provider's token is not valid.")
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except ValueError as exc:
        raise AuthenticationError("The identity provider's token is not valid.") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active or user.email != claims.get("email"):
        db.commit()
        raise AuthenticationError("No active user matches this directory account.")
    record_audit_event(
        db, actor_id=user.id, action="auth.login", entity_type="user", entity_id=user.id,
        metadata={"method": "sso", "provider": provider, "amr": claims.get("amr", [])},
    )  # fmt: skip
    sign_in = sessions.start(
        db, user, settings, method=SessionMethod.SSO, provider=provider,
        factor_asserted="otp" in (claims.get("amr") or []), meta=meta,
    )  # fmt: skip
    return user, sign_in
