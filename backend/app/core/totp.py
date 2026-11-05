"""Time-based one-time passwords (RFC 6238, the scheme authenticator apps use).

Six digits from HMAC-SHA1 over 30-second time steps of a base32 secret. A code is accepted
for the current step and one step either side (clock drift); the caller records the step
it accepted so no code works twice.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6
DRIFT_STEPS = 1
ISSUER = "ATLAS Global Bank"


def new_secret() -> str:
    """160 random bits, base32 without padding (what authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    padded = secret.upper() + "=" * (-len(secret) % 8)
    return base64.b32decode(padded)


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP_SECONDS)


def matching_step(
    secret: str, code: str, *, last_step: int | None, now: float | None = None
) -> int | None:
    """The time step `code` belongs to, or None. Steps at or before `last_step` (already
    used) never match, so a code cannot be replayed."""
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    step = current_step(now)
    for candidate in range(step - DRIFT_STEPS, step + DRIFT_STEPS + 1):
        if last_step is not None and candidate <= last_step:
            continue
        if hmac.compare_digest(code_at(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(secret: str, account: str) -> str:
    label = quote(f"{ISSUER}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&digits={DIGITS}&period={STEP_SECONDS}"


# --- Recovery codes ---------------------------------------------------------------------

RECOVERY_CODE_COUNT = 8


def new_recovery_codes() -> list[str]:
    """Eight one-time codes such as `7KQ2-9XMD`, shown once and stored hashed."""
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(alphabet) for _ in range(8))
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def recovery_hash(code: str) -> str:
    normalised = code.strip().upper().replace("-", "").replace(" ", "")
    return hashlib.sha256(normalised.encode("ascii", "ignore")).hexdigest()
