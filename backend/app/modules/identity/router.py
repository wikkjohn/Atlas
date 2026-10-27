import uuid

from fastapi import APIRouter, Request, status

from app.core.dependencies import DbSession, SettingsDep
from app.core.idempotency import IdempotencyKey, run_idempotent
from app.core.pagination import Page, PageParamsDep
from app.core.permissions import Permission, permissions_for
from app.modules.identity import service
from app.modules.identity.dependencies import Authorized, CurrentUser
from app.modules.identity.schemas import (
    CurrentUserOut,
    LoginRequest,
    LoginResponse,
    RoleOut,
    UserCreate,
    UserOut,
    UserUpdate,
)

auth_router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])
roles_router = APIRouter(prefix="/roles", tags=["users"])


@auth_router.post("/login", response_model=LoginResponse, summary="Sign in")
def login(body: LoginRequest, db: DbSession, settings: SettingsDep) -> LoginResponse:
    user, token = service.authenticate(db, body.username, body.password, settings)
    return LoginResponse(
        access_token=token.token,
        expires_at=token.expires_at,
        user=service.current_user_out(user),
    )


@auth_router.get("/me", response_model=CurrentUserOut, summary="The signed-in user")
def me(user: CurrentUser, db: DbSession) -> CurrentUserOut:
    return service.current_user_out(service.get_user(db, user.id))


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


@users_router.get("", response_model=Page[UserOut], summary="List users")
def list_users(
    db: DbSession, page: PageParamsDep, _: Authorized(Permission.USERS_READ)
) -> Page[UserOut]:
    users, total = service.list_users(db, page)
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
    user = service.update_user(db, service.get_user(db, user_id), body, actor.id)
    return service.user_out(user)
