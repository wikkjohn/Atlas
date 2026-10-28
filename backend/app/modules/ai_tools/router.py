import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from app.core.dependencies import DbSession
from app.core.errors import PermissionDeniedError
from app.core.idempotency import IdempotencyKey, run_idempotent
from app.core.pagination import Page, PageParamsDep
from app.core.permissions import Permission
from app.modules.ai_tools import service
from app.modules.ai_tools.models import InvocationStatus, ToolStatus
from app.modules.ai_tools.schemas import (
    ActionOut,
    AdapterOut,
    InvocationOut,
    InvokeRequest,
    ToolCreate,
    ToolOut,
    ToolStatusUpdate,
)
from app.modules.identity.dependencies import Authorized

router = APIRouter(prefix="/ai-tools", tags=["ai-tools"])


@router.get("", response_model=Page[ToolOut], summary="Registered AI tools")
def list_tools(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.AI_TOOLS_READ),
    status: ToolStatus | None = None,
    workflow_id: Annotated[str | None, Query(max_length=20)] = None,
) -> Page[ToolOut]:
    items, total = service.list_tools(db, page, status=status, workflow_id=workflow_id)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/adapters", response_model=list[AdapterOut], summary="Available implementations")
def list_adapters(_: Authorized(Permission.AI_TOOLS_READ)) -> list[AdapterOut]:
    return service.adapters()


@router.get("/actions", response_model=list[ActionOut], summary="Grantable and forbidden actions")
def list_actions(_: Authorized(Permission.AI_TOOLS_READ)) -> list[ActionOut]:
    return service.actions()


@router.get("/invocations", response_model=Page[InvocationOut], summary="Recorded tool invocations")
def list_invocations(
    db: DbSession,
    page: PageParamsDep,
    _: Authorized(Permission.AI_TOOLS_READ),
    tool: Annotated[uuid.UUID | None, Query(description="Registered tool (record id)")] = None,
    status: InvocationStatus | None = None,
    execution_id: uuid.UUID | None = None,
    simulation_run_id: uuid.UUID | None = None,
) -> Page[InvocationOut]:
    items, total = service.list_invocations(
        db,
        page,
        tool_record_id=tool,
        status=status,
        execution_id=execution_id,
        simulation_run_id=simulation_run_id,
    )
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post(
    "", response_model=ToolOut, status_code=status.HTTP_201_CREATED, summary="Register a tool"
)
def register_tool(
    body: ToolCreate,
    request: Request,
    db: DbSession,
    actor: Authorized(Permission.AI_TOOLS_MANAGE),
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
        operation=lambda: service.tool_out(db, service.register_tool(db, body, actor.id)),
    )


@router.get("/{tool_record_id}", response_model=ToolOut, summary="A registered tool version")
def get_tool(
    tool_record_id: uuid.UUID, db: DbSession, _: Authorized(Permission.AI_TOOLS_READ)
) -> ToolOut:
    return service.tool_out(db, service.get_tool(db, tool_record_id))


@router.patch(
    "/{tool_record_id}",
    response_model=ToolOut,
    summary="Enable or disable a tool version (everything else is immutable)",
)
def update_status(
    tool_record_id: uuid.UUID,
    body: ToolStatusUpdate,
    db: DbSession,
    actor: Authorized(Permission.AI_TOOLS_MANAGE),
) -> ToolOut:
    tool = service.set_status(db, service.get_tool(db, tool_record_id), body.status, actor.id)
    return service.tool_out(db, tool)


@router.post(
    "/{tool_record_id}/invoke",
    response_model=InvocationOut,
    summary="Call a tool directly (test console); the call is recorded",
)
def invoke(
    tool_record_id: uuid.UUID,
    body: InvokeRequest,
    db: DbSession,
    actor: Authorized(Permission.AI_TOOLS_INVOKE),
) -> InvocationOut:
    tool = service.get_tool(db, tool_record_id)
    missing = [p for p in tool.permissions if not actor.can(Permission(p))]
    if missing:
        raise PermissionDeniedError(
            "Your role cannot use this tool.", {"required_permissions": missing}
        )
    record = service.invoke(db, tool, body.action, body.input, actor_id=actor.id)
    if record.status == InvocationStatus.BLOCKED:
        # Keep the record of the refused attempt, then refuse.
        db.commit()
        raise PermissionDeniedError(record.error["message"], record.error)
    return service.invocation_out(record)
