"""Identity service: the public interface other modules use for users and roles."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.audit import diff, record_audit_event
from app.core.errors import (
    AuthenticationError,
    BusinessRuleViolation,
    ConflictError,
    NotFoundError,
)
from app.core.pagination import PageParams, paginate
from app.core.permissions import SERVICE_ROLES, Permission, RoleCode, permissions_for
from app.core.scope import UNRESTRICTED, Scope
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    UNUSABLE_PASSWORD_HASH,
    hash_password,
    verify_password,
)
from app.modules.identity.models import AuthSession, Role, User
from app.modules.identity.schemas import (
    CurrentUserOut,
    ScopeOut,
    SessionOut,
    UserCreate,
    UserOut,
    UserUpdate,
)

if TYPE_CHECKING:
    from app.modules.identity import sessions


@dataclass(frozen=True)
class AuthenticatedUser:
    """The caller of a request, resolved from a valid access token."""

    id: uuid.UUID
    username: str
    role: str
    permissions: frozenset[Permission]
    # Where the user may act (Phase 84); service principals are unrestricted.
    scope: Scope = UNRESTRICTED
    session_id: uuid.UUID | None = None

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions


def _scope_out(user: User) -> ScopeOut:
    countries = sorted(s.value for s in user.scopes if s.kind == "country")
    departments = sorted(s.value for s in user.scopes if s.kind == "department")
    return ScopeOut(countries=countries or None, departments=departments or None)


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        role=user.role.code,
        role_name=user.role.name,
        employee_id=user.employee_id,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        is_service_account=user.password_hash == UNUSABLE_PASSWORD_HASH,
        mfa_enabled=user.mfa_secret is not None,
        scope=_scope_out(user),
        locked_until=user.locked_until,
    )


def session_out(session: AuthSession, current: uuid.UUID | None = None) -> SessionOut:
    return SessionOut(
        id=session.id, method=session.method, provider=session.provider, mfa=session.mfa,
        ip_address=session.ip_address, user_agent=session.user_agent,
        created_at=session.created_at, last_seen_at=session.last_seen_at,
        expires_at=session.expires_at, revoked_at=session.revoked_at,
        revoked_reason=session.revoked_reason, current=session.id == current,
    )  # fmt: skip


def current_user_out(
    user: User, session: AuthSession | None = None, settings: Settings | None = None
) -> CurrentUserOut:
    from app.config import get_settings
    from app.modules.identity import sessions

    return CurrentUserOut(
        **user_out(user).model_dump(),
        permissions=sorted(p.value for p in permissions_for(user.role.code)),
        session=session_out(session, session.id) if session else None,
        mfa_enrolment_required=bool(
            session and sessions.enrolment_owed(session, user, settings or get_settings())
        ),
        mfa_recovery_codes_left=sum(
            1 for c in user.mfa_recovery_codes or [] if c.get("used_at") is None
        ),
    )


def get_role(db: Session, code: RoleCode | str) -> Role:
    role = db.execute(select(Role).where(Role.code == str(code))).scalar_one_or_none()
    if role is None:
        raise NotFoundError(f"Role '{code}' does not exist.")
    return role


def list_roles(db: Session) -> list[Role]:
    return list(db.execute(select(Role).order_by(Role.name)).scalars())


def authenticate(
    db: Session, username: str, password: str, settings: Settings,
    meta: "sessions.RequestMeta | None" = None,
) -> tuple[User, "sessions.SignIn"]:  # fmt: skip
    """Verify credentials and open a session: an access token, or (when the user has a
    second factor) a challenge to complete. Failed attempts are audited and committed."""
    from app.modules.identity import sessions

    user = db.execute(
        select(User).where(User.username == username.strip().lower())
    ).scalar_one_or_none()
    password_ok = verify_password(password, user.password_hash if user else DUMMY_PASSWORD_HASH)
    now = datetime.now(UTC)
    locked = user is not None and user.locked_until is not None and user.locked_until > now

    if user is None or not password_ok or not user.is_active or locked:
        reason = (
            "unknown_user" if user is None else "locked" if locked
            else "bad_password" if not password_ok else "inactive"
        )  # fmt: skip
        record_audit_event(
            db,
            actor_id=user.id if user else None,
            action="auth.login_failed",
            entity_type="user",
            entity_id=user.id if user else None,
            metadata={"username": username[:64], "reason": reason},
        )
        message = "Invalid username or password."
        if locked:
            minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
            message = (
                "This account is locked after repeated failed sign-ins; try again in "
                f"{minutes} minute(s) or ask an administrator to unlock it."
            )
        elif reason == "bad_password":
            # Phase 85: this many wrong passwords in a row lock the account for a while.
            user.failed_logins += 1
            if user.failed_logins >= settings.login_lockout_attempts:
                user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
                user.failed_logins = 0
                record_audit_event(
                    db, actor_id=None, action="auth.locked", entity_type="user",
                    entity_id=user.id,
                    metadata={"until": user.locked_until.isoformat(),
                              "attempts": settings.login_lockout_attempts},
                )  # fmt: skip
        # The failure is raised as an error, which rolls the request back; commit first so
        # the security record (and the count) survives.
        db.commit()
        raise AuthenticationError(message)

    user.failed_logins = 0
    user.locked_until = None
    record_audit_event(
        db, actor_id=user.id, action="auth.login", entity_type="user", entity_id=user.id,
        metadata={"method": "password"},
    )  # fmt: skip
    return user, sessions.start(db, user, settings, method="password", meta=meta)


def load_active_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("User account is not active.")
    return user


def get_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found.")
    return user


def list_users(
    db: Session, params: PageParams, *, kind: str | None = None, q: str | None = None
) -> tuple[list[User], int]:
    query = select(User).order_by(User.username)
    if kind == "people":
        query = query.where(User.password_hash != UNUSABLE_PASSWORD_HASH)
    elif kind == "service":
        query = query.where(User.password_hash == UNUSABLE_PASSWORD_HASH)
    if q:
        needle = f"%{q.strip().lower()}%"
        query = query.where(User.username.ilike(needle) | User.display_name.ilike(needle))
    return paginate(db, query, params)


def _require_person_role(role: RoleCode) -> None:
    if role in SERVICE_ROLES:
        raise BusinessRuleViolation(f"The {role.value} role belongs to system principals only.")


def create_user(db: Session, data: UserCreate, actor_id: uuid.UUID | None) -> User:
    _require_person_role(data.role)
    if data.employee_id is not None:
        # Imported here to keep identity free of a module-level dependency on employees.
        from app.modules.employees.models import Employee

        if db.get(Employee, data.employee_id) is None:
            raise BusinessRuleViolation("employee_id does not reference an existing employee.")

    user = User(
        username=data.username,
        email=data.email,
        display_name=data.display_name,
        password_hash=hash_password(data.password),
        role_id=get_role(db, data.role).id,
        employee_id=data.employee_id,
        is_active=True,
    )
    db.add(user)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "A user with this username, email or employee link already exists."
        ) from exc
    db.refresh(user)
    record_audit_event(
        db,
        actor_id=actor_id,
        action="user.created",
        entity_type="user",
        entity_id=user.id,
        metadata={"username": user.username, "role": str(data.role)},
    )
    return user


def create_service_account(
    db: Session,
    *,
    username: str,
    email: str,
    display_name: str,
    role: RoleCode,
    employee_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
) -> User:
    """A user that acts inside the system (e.g. simulated staff) but can never sign in."""
    user = User(
        username=username,
        email=email,
        display_name=display_name,
        password_hash=UNUSABLE_PASSWORD_HASH,
        role_id=get_role(db, role).id,
        employee_id=employee_id,
        is_active=True,
    )
    db.add(user)
    db.flush()
    record_audit_event(
        db,
        actor_id=actor_id,
        action="user.service_account_created",
        entity_type="user",
        entity_id=user.id,
        metadata={"username": username, "role": str(role)},
    )
    return user


def update_user(db: Session, user: User, data: UserUpdate, actor_id: uuid.UUID) -> User:
    before = {
        "display_name": user.display_name,
        "role": user.role.code,
        "is_active": user.is_active,
    }
    if data.display_name is not None:
        user.display_name = data.display_name
    if data.role is not None:
        _require_person_role(data.role)
        if user.password_hash == UNUSABLE_PASSWORD_HASH and data.role != user.role.code:
            raise BusinessRuleViolation(
                "Service accounts keep their role; deactivate the account instead."
            )
        if user.id == actor_id and data.role != RoleCode.PLATFORM_ADMINISTRATOR:
            raise BusinessRuleViolation("You cannot remove your own administrator role.")
        role = get_role(db, data.role)
        user.role_id = role.id
        user.role = role
    if data.is_active is not None:
        if user.id == actor_id and not data.is_active:
            raise BusinessRuleViolation("You cannot deactivate your own account.")
        user.is_active = data.is_active
        if not data.is_active:
            from app.modules.identity import sessions

            sessions.revoke_all(db, user.id, "deactivated", actor_id)
    db.flush()
    after = {"display_name": user.display_name, "role": user.role.code, "is_active": user.is_active}
    changes = diff(before, after)
    if changes:
        record_audit_event(
            db,
            actor_id=actor_id,
            action="user.updated",
            entity_type="user",
            entity_id=user.id,
            metadata={"changes": changes},
        )
    return user


def unlock_user(db: Session, user: User, actor_id: uuid.UUID) -> User:
    if user.locked_until is not None or user.failed_logins:
        user.locked_until = None
        user.failed_logins = 0
        record_audit_event(
            db, actor_id=actor_id, action="auth.unlocked", entity_type="user", entity_id=user.id
        )
    return user
