import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response, status

from app.core import ratelimit
from app.core.dependencies import DbSession, SettingsDep
from app.core.errors import BusinessRuleViolation
from app.core.idempotency import IdempotencyKey, run_idempotent
from app.core.pagination import Page, PageParamsDep
from app.core.permissions import Permission, permissions_for
from app.modules.identity import mfa, scopes, service, sessions, sso
from app.modules.identity.dependencies import Authorized, CurrentUser
from app.modules.identity.models import AuthSession
from app.modules.identity.schemas import (
    CurrentUserOut,
    DirectoryResponse,
    DirectorySignIn,
    LoginRequest,
    LoginResponse,
    MfaCodeRequest,
    MfaEnrolmentOut,
    MfaVerifyRequest,
    RecoveryCodesOut,
    RoleOut,
    ScopeOut,
    ScopeUpdate,
    SessionOut,
    SsoCallback,
    SsoProviderOut,
    SsoStartOut,
    UserCreate,
    UserOut,
    UserUpdate,
)

auth_router = APIRouter(prefix="/auth", tags=["auth"])
# The simulated corporate identity provider (Phase 84): not the bank, though it runs here.
directory_router = APIRouter(prefix="/simulated-directory", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])
roles_router = APIRouter(prefix="/roles", tags=["users"])


def _meta(request: Request) -> sessions.RequestMeta:
    return sessions.RequestMeta(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


def _signed_in(db, user, sign_in: sessions.SignIn) -> LoginResponse:
    if sign_in.challenge is not None:
        return LoginResponse(
            status="mfa_required",
            challenge_token=sign_in.challenge.token,
            challenge_expires_at=sign_in.challenge.expires_at,
        )
    return LoginResponse(
        access_token=sign_in.access.token,
        expires_at=sign_in.access.expires_at,
        user=service.current_user_out(user, sign_in.session),
    )


@auth_router.post("/login", response_model=LoginResponse, summary="Sign in")
def login(
    body: LoginRequest, request: Request, db: DbSession, settings: SettingsDep
) -> LoginResponse:
    """A password sign-in. With a second factor enrolled, the answer is `mfa_required` and a
    challenge for `POST /auth/mfa/verify`; no access token is issued until then."""
    ratelimit.hit(db, "login.ip", ratelimit.client_address(request))
    ratelimit.hit(db, "login.user", body.username.strip().lower())
    user, sign_in = service.authenticate(db, body.username, body.password, settings, _meta(request))
    return _signed_in(db, user, sign_in)


@auth_router.post("/mfa/verify", response_model=LoginResponse, summary="Complete a sign-in")
def verify_mfa(
    body: MfaVerifyRequest, request: Request, db: DbSession, settings: SettingsDep
) -> LoginResponse:
    """The second factor: a code from the authenticator or a one-time recovery code. Five
    wrong codes end the sign-in."""
    ratelimit.hit(db, "mfa.ip", ratelimit.client_address(request))
    user, session, token = sessions.verify_challenge(db, body.challenge_token, body.code, settings)
    return LoginResponse(
        access_token=token.token, expires_at=token.expires_at,
        user=service.current_user_out(user, session),
    )  # fmt: skip


@auth_router.get("/me", response_model=CurrentUserOut, summary="The signed-in user")
def me(user: CurrentUser, db: DbSession, settings: SettingsDep) -> CurrentUserOut:
    return service.current_user_out(
        service.get_user(db, user.id), db.get(AuthSession, user.session_id), settings
    )


@auth_router.post("/refresh", response_model=LoginResponse, summary="A new access token")
def refresh(user: CurrentUser, db: DbSession, settings: SettingsDep) -> LoginResponse:
    """A fresh access token for the same session; never valid past the session's end."""
    session = db.get(AuthSession, user.session_id)
    token = sessions.access_token(session, settings)
    return LoginResponse(
        access_token=token.token, expires_at=token.expires_at,
        user=service.current_user_out(service.get_user(db, user.id), session),
    )  # fmt: skip


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out")
def logout(user: CurrentUser, db: DbSession) -> Response:
    sessions.revoke(db, db.get(AuthSession, user.session_id), "signed_out", user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@auth_router.get("/sessions", response_model=list[SessionOut], summary="My sessions")
def my_sessions(user: CurrentUser, db: DbSession) -> list[SessionOut]:
    return [service.session_out(s, user.session_id) for s in sessions.list_for(db, user.id)]


@auth_router.delete(
    "/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="End a session"
)
def end_session(session_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    sessions.revoke(db, sessions.get_own(db, user.id, session_id), "signed_out", user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@auth_router.post("/sessions/revoke-others", summary="Sign out everywhere else")
def end_other_sessions(user: CurrentUser, db: DbSession) -> dict[str, int]:
    return {"revoked": sessions.revoke_all(db, user.id, "signed_out", user.id,
                                           keep=user.session_id)}  # fmt: skip


# --- Second factor -------------------------------------------------------------------------


@auth_router.post("/mfa/enrol", response_model=MfaEnrolmentOut, summary="Start enrolling")
def start_mfa_enrolment(user: CurrentUser, db: DbSession) -> MfaEnrolmentOut:
    """A new TOTP secret, shown once with its `otpauth://` URI; it becomes the factor when
    a code from it is confirmed."""
    secret, uri = mfa.begin_enrolment(db, service.get_user(db, user.id))
    return MfaEnrolmentOut(secret=secret, provisioning_uri=uri)


@auth_router.post("/mfa/confirm", response_model=RecoveryCodesOut, summary="Confirm enrolment")
def confirm_mfa_enrolment(
    body: MfaCodeRequest, user: CurrentUser, db: DbSession
) -> RecoveryCodesOut:
    """Turns the factor on and returns eight one-time recovery codes (shown only now). The
    other sessions are signed out; this one counts as verified."""
    codes = mfa.confirm_enrolment(
        db, mfa.lock(db, user.id), body.code, db.get(AuthSession, user.session_id)
    )
    sessions.revoke_all(db, user.id, "mfa_enrolled", user.id, keep=user.session_id)
    return RecoveryCodesOut(recovery_codes=codes)


@auth_router.post(
    "/mfa/recovery-codes", response_model=RecoveryCodesOut, summary="New recovery codes"
)
def regenerate_recovery_codes(
    body: MfaCodeRequest, user: CurrentUser, db: DbSession
) -> RecoveryCodesOut:
    codes = mfa.regenerate_recovery_codes(db, mfa.lock(db, user.id), body.code)
    return RecoveryCodesOut(recovery_codes=codes)


@auth_router.post("/mfa/remove", status_code=status.HTTP_204_NO_CONTENT, summary="Remove")
def remove_mfa(
    body: MfaCodeRequest, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> Response:
    """Remove one's own factor with a current code. Refused when the role requires one."""
    record = mfa.lock(db, user.id)
    if sessions.requires_mfa(record, settings):
        raise BusinessRuleViolation("Your role requires a second factor.")
    if mfa.verify(record, body.code) is None:
        raise BusinessRuleViolation("The code is not valid.")
    mfa.clear(db, record, user.id, reason="removed_by_user")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Simulated single sign-on --------------------------------------------------------------


@auth_router.get("/sso/providers", response_model=list[SsoProviderOut], summary="SSO providers")
def sso_providers() -> list[SsoProviderOut]:
    return [SsoProviderOut(**p) for p in sso.providers()]


@auth_router.post("/sso/{provider}/start", response_model=SsoStartOut, summary="Start SSO")
def sso_start(provider: str, request: Request, db: DbSession) -> SsoStartOut:
    """A sign-in request for the identity provider: `state` and `nonce`, valid 10 minutes."""
    ratelimit.hit(db, "sso.ip", ratelimit.client_address(request))
    request = sso.start(db, provider)
    return SsoStartOut(provider=provider, state=request.state, nonce=request.nonce,
                       expires_at=request.expires_at)  # fmt: skip


@auth_router.post("/sso/{provider}/callback", response_model=LoginResponse, summary="Finish SSO")
def sso_callback(
    provider: str, body: SsoCallback, request: Request, db: DbSession, settings: SettingsDep
) -> LoginResponse:
    """Accept the provider's ID token for a pending request and sign the user in."""
    ratelimit.hit(db, "sso.ip", ratelimit.client_address(request))
    user, sign_in = sso.callback(
        db, provider, state=body.state, id_token=body.id_token, settings=settings,
        meta=_meta(request),
    )  # fmt: skip
    return _signed_in(db, user, sign_in)


@directory_router.post(
    "/{provider}/sign-in", response_model=DirectoryResponse,
    summary="The simulated directory's sign-in",
)  # fmt: skip
def directory_sign_in(
    provider: str, body: DirectorySignIn, request: Request, db: DbSession, settings: SettingsDep
) -> DirectoryResponse:
    """Stands in for the corporate identity provider: authenticates the employee and
    returns a signed ID token for the bank's callback."""
    ratelimit.hit(db, "sso.ip", ratelimit.client_address(request))
    token = sso.directory_sign_in(
        db, provider, nonce=body.nonce, username=body.username, password=body.password,
        otp=body.otp, settings=settings,
    )  # fmt: skip
    return DirectoryResponse(id_token=token)


@roles_router.get("", response_model=list[RoleOut], summary="Roles and their permissions")
def list_roles(db: DbSession, _: CurrentUser) -> list[RoleOut]:
    return [
        RoleOut(
            id=role.id,
            code=role.code,
            name=role.name,
            description=role.description,
            permissions=sorted(p.value for p in permissions_for(role.code)),
        )
        for role in service.list_roles(db)
    ]


def _require_unscoped(actor) -> None:
    """User administration is for administrators without a scope: a scoped one could
    otherwise mint or empower an unscoped account (PR #75 review)."""
    if actor.scope.limited:
        raise BusinessRuleViolation(
            "Only an administrator without a country or department scope can manage users."
        )


@users_router.get("", response_model=Page[UserOut], summary="List users")
def list_users(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.USERS_READ),
    kind: Annotated[
        Literal["people", "service"] | None,
        Query(description="people: can sign in; service: system principals"),
    ] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[UserOut]:
    users, total = service.list_users(db, page, kind=kind, q=q)
    return Page(
        items=[service.user_out(u) for u in users],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@users_router.post(
    "", response_model=UserOut, status_code=status.HTTP_201_CREATED, summary="Create a user"
)
def create_user(
    body: UserCreate,
    request: Request,
    db: DbSession,
    actor: Authorized(Permission.USERS_MANAGE),
    idempotency_key: IdempotencyKey = None,
):
    _require_unscoped(actor)
    return run_idempotent(
        db,
        key=idempotency_key,
        actor_id=actor.id,
        method="POST",
        path=request.url.path,
        payload=body,
        status_code=status.HTTP_201_CREATED,
        operation=lambda: service.user_out(service.create_user(db, body, actor.id)),
    )


@users_router.get("/{user_id}", response_model=UserOut, summary="Get a user")
def get_user(user_id: uuid.UUID, db: DbSession, _: Authorized(Permission.USERS_READ)) -> UserOut:
    return service.user_out(service.get_user(db, user_id))


@users_router.patch("/{user_id}", response_model=UserOut, summary="Update a user")
def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    db: DbSession,
    actor: Authorized(Permission.USERS_MANAGE),
) -> UserOut:
    _require_unscoped(actor)
    user = service.update_user(db, service.get_user(db, user_id), body, actor.id)
    return service.user_out(user)


@users_router.put("/{user_id}/scopes", response_model=ScopeOut, summary="Set a user's scopes")
def set_user_scopes(
    user_id: uuid.UUID, body: ScopeUpdate, db: DbSession, actor: Authorized(Permission.USERS_MANAGE)
) -> ScopeOut:
    """Limit the user to countries and departments (empty: not limited in that dimension).
    Takes effect on the user's next request."""
    _require_unscoped(actor)
    scope = scopes.set_scopes(db, service.get_user(db, user_id), body.countries,
                              body.departments, actor.id)  # fmt: skip
    return ScopeOut(**scope.describe())


@users_router.get(
    "/{user_id}/sessions", response_model=list[SessionOut], summary="A user's sessions"
)
def user_sessions(
    user_id: uuid.UUID, db: DbSession, _: Authorized(Permission.USERS_READ)
) -> list[SessionOut]:
    return [service.session_out(s) for s in sessions.list_for(db, service.get_user(db, user_id).id)]


@users_router.post("/{user_id}/sessions/revoke", summary="Sign a user out everywhere")
def revoke_user_sessions(
    user_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.USERS_MANAGE)
) -> dict[str, int]:
    _require_unscoped(actor)
    return {"revoked": sessions.revoke_all(db, service.get_user(db, user_id).id,
                                           "revoked_by_administrator", actor.id)}  # fmt: skip


@users_router.post(
    "/{user_id}/mfa/reset", status_code=status.HTTP_204_NO_CONTENT, summary="Reset MFA"
)
def reset_user_mfa(
    user_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.USERS_MANAGE)
) -> Response:
    """Remove a user's second factor (a lost device) and sign them out everywhere; they
    enrol again at their next sign-in if their role requires it. Not one's own."""
    _require_unscoped(actor)
    user = service.get_user(db, user_id)
    if user.id == actor.id:
        raise BusinessRuleViolation("Reset your own factor from your security settings.")
    mfa.clear(db, user, actor.id, reason="reset_by_administrator")
    sessions.revoke_all(db, user.id, "mfa_reset", actor.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@users_router.post("/{user_id}/unlock", response_model=UserOut, summary="Unlock a user")
def unlock_user(
    user_id: uuid.UUID, db: DbSession, actor: Authorized(Permission.USERS_MANAGE)
) -> UserOut:
    """Lift a sign-in lockout (Phase 85) before it expires."""
    _require_unscoped(actor)
    return service.user_out(service.unlock_user(db, service.get_user(db, user_id), actor.id))
