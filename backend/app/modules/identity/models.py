import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.models import Timestamps, UUIDPrimaryKey


class Role(UUIDPrimaryKey, Base):
    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="RESTRICT"), nullable=True, unique=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # TOTP second factor (Phase 84): the confirmed secret, one awaiting confirmation, when it
    # was enabled, the last time step accepted (no code is accepted twice), and the hashed
    # one-time recovery codes ({"hash", "used_at"}).
    mfa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mfa_pending_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mfa_last_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mfa_recovery_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    role: Mapped[Role] = relationship(lazy="joined")
    scopes: Mapped[list["UserScope"]] = relationship(
        lazy="selectin", foreign_keys="UserScope.user_id", viewonly=True
    )


class SessionMethod:
    PASSWORD = "password"
    SSO = "sso"


class SessionMfa:
    NOT_REQUIRED = "not_required"  # no factor enrolled and the role does not require one
    PENDING = "pending"  # the password is right; the second factor is still owed
    VERIFIED = "verified"
    # The role requires a factor the user has not enrolled: only enrolment is allowed.
    ENROLMENT_REQUIRED = "enrolment_required"


class AuthSession(Base):
    """One sign-in (Phase 84). Every access token names its session; a revoked, idle or
    expired session ends the token at once."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint("method IN ('password', 'sso')", name="method"),
        CheckConstraint(
            "mfa IN ('not_required', 'pending', 'verified', 'enrolment_required')", name="mfa"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mfa: Mapped[str] = mapped_column(String(20), nullable=False)
    failed_mfa_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)


class SsoRequest(Base):
    """A sign-in sent to the simulated identity provider: its state and nonce, used once."""

    __tablename__ = "sso_requests"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserScope(Base):
    """Limits a user to countries and departments (Phase 84). A user without scopes of a
    kind is not limited in it."""

    __tablename__ = "user_scopes"
    __table_args__ = (
        CheckConstraint("kind IN ('country', 'department')", name="kind"),
        UniqueConstraint("user_id", "kind", "value", name="uq_user_scopes"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
