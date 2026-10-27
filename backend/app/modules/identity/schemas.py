import uuid
from datetime import datetime

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


class CurrentUserOut(UserOut):
    permissions: list[str]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: CurrentUserOut


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
