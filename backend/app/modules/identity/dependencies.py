"""Authentication and authorization dependencies used by every protected router."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.dependencies import DbSession, SettingsDep
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.permissions import Permission, permissions_for
from app.core.security import decode_access_token
from app.modules.identity.service import AuthenticatedUser, load_active_user

_bearer = HTTPBearer(auto_error=False, description="Access token from POST /api/v1/auth/login")


def get_current_user(
    db: DbSession,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Authentication required.")
    claims = decode_access_token(credentials.credentials, settings.jwt_secret.get_secret_value())
    user = load_active_user(db, claims.user_id)
    return AuthenticatedUser(
        id=user.id,
        username=user.username,
        role=user.role.code,
        permissions=permissions_for(user.role.code),
    )


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]


def require(permission: Permission) -> Callable[[AuthenticatedUser], AuthenticatedUser]:
    """Dependency factory: reject the request with 403 unless the caller has `permission`."""

    def _check(user: CurrentUser) -> AuthenticatedUser:
        if not user.can(permission):
            raise PermissionDeniedError(
                f"Your role does not grant the '{permission.value}' permission.",
                {"required_permission": permission.value, "role": user.role},
            )
        return user

    return _check


def Authorized(permission: Permission) -> type[AuthenticatedUser]:  # noqa: N802
    """`user: Authorized(Permission.X)` — the authenticated caller, checked for X."""
    return Annotated[AuthenticatedUser, Depends(require(permission))]  # type: ignore[return-value]
