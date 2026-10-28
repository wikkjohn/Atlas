"""Password hashing and access tokens.

Passwords use scrypt from the standard library (memory-hard, salted per user). Access
tokens are short-lived HS256 JWTs; every request re-loads the user, so deactivating a user
or changing their role takes effect immediately rather than when the token expires.
"""

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.core.errors import AuthenticationError

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_KEY_BYTES = 32
_ALGORITHM = "HS256"
TOKEN_ISSUER = "atlas-global-bank"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    key = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_KEY_BYTES
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, key_b64 = encoded.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(key_b64)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Stored for service accounts (such as simulated staff) that must never sign in. It is not
# a valid scrypt hash, so `verify_password` rejects every password against it.
UNUSABLE_PASSWORD_HASH = "!unusable"

# Verifying against a real hash when the username is unknown keeps response timing similar,
# so login timing does not reveal which usernames exist.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


@dataclass(frozen=True)
class IssuedToken:
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    token_id: str
    expires_at: datetime


def create_access_token(
    user_id: uuid.UUID, secret: str, ttl: timedelta, now: datetime | None = None
) -> IssuedToken:
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + ttl
    payload = {
        "sub": str(user_id),
        "iss": TOKEN_ISSUER,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": secrets.token_hex(8),
    }
    return IssuedToken(
        token=jwt.encode(payload, secret, algorithm=_ALGORITHM), expires_at=expires_at
    )


def decode_access_token(token: str, secret: str) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[_ALGORITHM],
            issuer=TOKEN_ISSUER,
            options={"require": ["sub", "exp", "iat", "iss"]},
        )
        user_id = uuid.UUID(payload["sub"])
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token has expired.") from exc
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise AuthenticationError("Access token is invalid.") from exc
    return TokenClaims(
        user_id=user_id,
        token_id=str(payload.get("jti", "")),
        expires_at=datetime.fromtimestamp(payload["exp"], UTC),
    )
