import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.permissions import RoleCode

USERNAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{2,63}$"
# Deliberately simple: one "@", no spaces, a dot in the domain.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str
    permissions: list[str] = []


class ScopeOut(BaseModel):
    countries: list[str] | None = None
    departments: list[str] | None = None


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    display_name: str
    role: str
    role_name: str
    employee_id: uuid.UUID | None
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    # A system principal (simulated staff, the policy engine) that can never sign in.
    is_service_account: bool = False
    mfa_enabled: bool = False
    # Where the user may act (Phase 84); null in a dimension means not limited in it.
    scope: ScopeOut = Field(default_factory=ScopeOut)


class ScopeUpdate(BaseModel):
    """Empty lists remove the limit in that dimension."""

    countries: list[str] = Field(default_factory=list, max_length=150)
    departments: list[str] = Field(default_factory=list, max_length=100)


class SessionOut(BaseModel):
    id: uuid.UUID
    method: str
    provider: str | None
    mfa: str
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    revoked_reason: str | None
    current: bool = False


class CurrentUserOut(UserOut):
    permissions: list[str]
    # The session the request came with: how it was opened and whether its second factor
    # is satisfied; `mfa_enrolment_required` means only enrolment is allowed until then.
    session: SessionOut | None = None
    mfa_enrolment_required: bool = False
    mfa_recovery_codes_left: int = 0


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    """Signed in (an access token and the user), or a second factor is owed: then only a
    short-lived `challenge_token` for `POST /auth/mfa/verify`."""

    status: Literal["signed_in", "mfa_required"] = "signed_in"
    access_token: str | None = None
    token_type: str = "bearer"
    expires_at: datetime | None = None
    user: CurrentUserOut | None = None
    challenge_token: str | None = None
    challenge_expires_at: datetime | None = None


class MfaVerifyRequest(BaseModel):
    challenge_token: str = Field(min_length=1, max_length=2000)
    code: str = Field(min_length=6, max_length=20, description="A TOTP code or a recovery code")


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=20)


class MfaEnrolmentOut(BaseModel):
    secret: str
    provisioning_uri: str


class RecoveryCodesOut(BaseModel):
    recovery_codes: list[str]


class SsoProviderOut(BaseModel):
    id: str
    name: str
    simulated: bool


class SsoStartOut(BaseModel):
    provider: str
    state: str
    nonce: str
    expires_at: datetime


class DirectorySignIn(BaseModel):
    """What the simulated directory's sign-in page sends it."""

    nonce: str = Field(min_length=1, max_length=64)
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    otp: str | None = Field(default=None, max_length=20)


class DirectoryResponse(BaseModel):
    id_token: str


class SsoCallback(BaseModel):
    state: str = Field(min_length=1, max_length=64)
    id_token: str = Field(min_length=1, max_length=4000)


class UserCreate(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    email: str = Field(pattern=EMAIL_PATTERN, max_length=254)
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=256)
    role: RoleCode
    employee_id: uuid.UUID | None = None

    @field_validator("username", "email", mode="before")
    @classmethod
    def _lowercase(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: RoleCode | None = None
    is_active: bool | None = None
