"""Identity service: the public interface other modules use for users and roles."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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
from app.core.permissions import Permission, RoleCode, permissions_for
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    IssuedToken,
    create_access_token,
    hash_password,
    verify_password,
)
from app.modules.identity.models import Role, User
from app.modules.identity.schemas import CurrentUserOut, UserCreate, UserOut, UserUpdate


@dataclass(frozen=True)
class AuthenticatedUser:
    """The caller of a request, resolved from a valid access token."""

    id: uuid.UUID
    username: str
    role: str
    permissions: frozenset[Permission]

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions


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
    )


def current_user_out(user: User) -> CurrentUserOut:
    return CurrentUserOut(
        **user_out(user).model_dump(),
        permissions=sorted(p.value for p in permissions_for(user.role.code)),
    )


def get_role(db: Session, code: RoleCode | str) -> Role:
    role = db.execute(select(Role).where(Role.code == str(code))).scalar_one_or_none()
    if role is None:
        raise NotFoundError(f"Role '{code}' does not exist.")
    return role


def list_roles(db: Session) -> list[Role]:
    return list(db.execute(select(Role).order_by(Role.name)).scalars())


def authenticate(
    db: Session, username: str, password: str, settings: Settings
) -> tuple[User, IssuedToken]:
    """Verify credentials and issue a token. Failed attempts are audited and committed."""
    user = db.execute(
        select(User).where(User.username == username.strip().lower())
    ).scalar_one_or_none()
    password_ok = verify_password(password, user.password_hash if user else DUMMY_PASSWORD_HASH)

    if user is None or not password_ok or not user.is_active:
        reason = (
            "unknown_user" if user is None else ("bad_password" if not password_ok else "inactive")
        )
        record_audit_event(
            db,
            actor_id=user.id if user else None,
            action="auth.login_failed",
            entity_type="user",
            entity_id=user.id if user else None,
            metadata={"username": username[:64], "reason": reason},
        )
        # The failure is raised as an error, which rolls the request back; commit first so
        # the security record survives.
        db.commit()
        raise AuthenticationError("Invalid username or password.")

    user.last_login_at = datetime.now(UTC)
    record_audit_event(
        db, actor_id=user.id, action="auth.login", entity_type="user", entity_id=user.id
    )
    token = create_access_token(
        user.id,
        settings.jwt_secret.get_secret_value(),
        timedelta(minutes=settings.access_token_ttl_minutes),
    )
    return user, token


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


def list_users(db: Session, params: PageParams) -> tuple[list[User], int]:
    return paginate(db, select(User).order_by(User.username), params)


def create_user(db: Session, data: UserCreate, actor_id: uuid.UUID | None) -> User:
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


def update_user(db: Session, user: User, data: UserUpdate, actor_id: uuid.UUID) -> User:
    before = {
        "display_name": user.display_name,
        "role": user.role.code,
        "is_active": user.is_active,
    }
    if data.display_name is not None:
        user.display_name = data.display_name
    if data.role is not None:
        if user.id == actor_id and data.role != RoleCode.PLATFORM_ADMINISTRATOR:
            raise BusinessRuleViolation("You cannot remove your own administrator role.")
        role = get_role(db, data.role)
        user.role_id = role.id
        user.role = role
    if data.is_active is not None:
        if user.id == actor_id and not data.is_active:
            raise BusinessRuleViolation("You cannot deactivate your own account.")
        user.is_active = data.is_active
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
