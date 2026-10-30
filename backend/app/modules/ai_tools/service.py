"""AI tool registry and the single invocation path every caller uses."""

import asyncio
import concurrent.futures
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit_event
from app.core.errors import BusinessRuleViolation, ConflictError, NotFoundError
from app.core.logging import correlation_id_var
from app.core.pagination import PageParams, paginate
from app.core.permissions import Permission
from app.modules.ai_tools.actions import FORBIDDEN_ACTIONS, GRANTABLE_ACTIONS
from app.modules.ai_tools.adapters import ADAPTERS, get_adapter
from app.modules.ai_tools.adapters.base import ToolContext, ToolError, ToolRequest
from app.modules.ai_tools.models import AITool, AIToolInvocation, InvocationStatus, ToolStatus
from app.modules.ai_tools.schemas import (
    ActionOut,
    AdapterOut,
    InvocationOut,
    ToolCreate,
    ToolOut,
)
from app.modules.identity.models import User
from app.modules.workflows import store

DEFAULT_TIMEOUT_SECONDS = 5.0


# --- Catalogues -------------------------------------------------------------------------------


def adapters() -> list[AdapterOut]:
    return [
        AdapterOut(
            key=a.key,
            name=a.name,
            provider=a.provider,
            description=a.description,
            supported_actions=sorted(a.supported_actions),
            input_schema=a.input_model.model_json_schema(),
            output_schema=a.output_model.model_json_schema(),
            configuration_schema=a.config_model.model_json_schema(),
        )
        for a in ADAPTERS.values()
    ]


def actions() -> list[ActionOut]:
    return [
        ActionOut(action=name, grantable=True, description=text)
        for name, text in GRANTABLE_ACTIONS.items()
    ] + [
        ActionOut(action=name, grantable=False, description=text)
        for name, text in FORBIDDEN_ACTIONS.items()
    ]


# --- Registration -----------------------------------------------------------------------------


def _check_schema(name: str, schema: dict[str, Any]) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise BusinessRuleViolation(
            f"{name} is not a valid JSON Schema: {exc.message}", {"field": name}
        ) from exc
    if schema.get("type") != "object":
        raise BusinessRuleViolation(
            f'{name} must describe a JSON object ("type": "object").', {"field": name}
        )


def register_tool(db: Session, data: ToolCreate, actor_id: uuid.UUID | None) -> AITool:
    adapter = get_adapter(data.adapter)
    if adapter is None:
        raise BusinessRuleViolation(
            f"Unknown adapter '{data.adapter}'.", {"available": sorted(ADAPTERS)}
        )
    forbidden = [a for a in data.allowed_actions if a in FORBIDDEN_ACTIONS]
    if forbidden:
        raise BusinessRuleViolation(
            "AI tools cannot be granted actions that change banking records on their own "
            "authority.",
            {"forbidden_actions": forbidden},
        )
    unknown = [a for a in data.allowed_actions if a not in GRANTABLE_ACTIONS]
    if unknown:
        raise BusinessRuleViolation("Unknown actions.", {"unknown_actions": unknown})
    unsupported = [a for a in data.allowed_actions if a not in adapter.supported_actions]
    if unsupported:
        raise BusinessRuleViolation(
            f"The {adapter.key} adapter does not implement these actions.",
            {"unsupported_actions": unsupported},
        )
    valid_permissions = {p.value for p in Permission}
    bad_permissions = [p for p in data.permissions if p not in valid_permissions]
    if bad_permissions:
        raise BusinessRuleViolation("Unknown permissions.", {"permissions": bad_permissions})
    workflows = store.workflow_ids(db)
    unknown_workflows = [w for w in data.compatible_workflows if w not in workflows]
    if unknown_workflows:
        raise BusinessRuleViolation("Unknown workflows.", {"workflows": unknown_workflows})
    input_schema = data.input_schema or adapter.input_model.model_json_schema()
    output_schema = data.output_schema or adapter.output_model.model_json_schema()
    _check_schema("input_schema", input_schema)
    _check_schema("output_schema", output_schema)
    try:
        configuration = adapter.config_model.model_validate(data.configuration).model_dump(
            mode="json"
        )
    except ValidationError as exc:
        raise BusinessRuleViolation(
            "The configuration is invalid for this adapter.",
            [{"location": list(e["loc"]), "message": e["msg"]} for e in exc.errors()],
        ) from exc

    tool = AITool(
        tool_id=data.tool_id,
        tool_name=data.tool_name.strip(),
        tool_version=data.tool_version,
        provider=data.provider.strip(),
        description=data.description.strip(),
        adapter=adapter.key,
        input_schema=input_schema,
        output_schema=output_schema,
        allowed_actions=list(dict.fromkeys(data.allowed_actions)),
        permissions=list(dict.fromkeys(data.permissions)),
        compatible_workflows=list(dict.fromkeys(data.compatible_workflows)),
        configuration=configuration,
        status=ToolStatus.ACTIVE.value,
        created_by=actor_id,
    )
    db.add(tool)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        raise ConflictError(
            f"{data.tool_id} {data.tool_version} is already registered; versions are "
            "immutable — register a new version."
        ) from exc
    db.refresh(tool)
    record_audit_event(
        db,
        actor_id=actor_id,
        action="ai_tool.registered",
        entity_type="ai_tool",
        entity_id=tool.id,
        metadata={
            "tool_id": tool.tool_id,
            "tool_version": tool.tool_version,
            "adapter": tool.adapter,
            "allowed_actions": tool.allowed_actions,
        },
    )
    return tool


def set_status(db: Session, tool: AITool, status: str, actor_id: uuid.UUID) -> AITool:
    if tool.status != status:
        before = tool.status
        tool.status = status
        db.flush()
        record_audit_event(
            db,
            actor_id=actor_id,
            action="ai_tool.status_changed",
            entity_type="ai_tool",
            entity_id=tool.id,
            metadata={"from": before, "to": status},
        )
    return tool


def get_tool(db: Session, tool_record_id: uuid.UUID) -> AITool:
    tool = db.get(AITool, tool_record_id)
    if tool is None:
        raise NotFoundError("AI tool not found.")
    return tool


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def find_tool(db: Session, tool_id: str, version: str | None = None) -> AITool:
    """A tool by id; without a version, its highest active version."""
    query = select(AITool).where(AITool.tool_id == tool_id)
    if version:
        query = query.where(AITool.tool_version == version)
    else:
        query = query.where(AITool.status == ToolStatus.ACTIVE)
    candidates = list(db.execute(query).scalars())
    if not candidates:
        raise NotFoundError(
            f"AI tool {tool_id}"
            + (f" {version}" if version else "")
            + " is not registered"
            + ("" if version else " (or has no active version)")
            + "."
        )
    return max(candidates, key=lambda t: _version_key(t.tool_version))


def list_tools(
    db: Session, params: PageParams, *, status: str | None = None, workflow_id: str | None = None
) -> tuple[list[ToolOut], int]:
    query = select(AITool).order_by(AITool.tool_id, AITool.created_at.desc())
    if status:
        query = query.where(AITool.status == status)
    if workflow_id:
        query = query.where(AITool.compatible_workflows.contains([workflow_id]))
    items, total = paginate(db, query, params)
    return [tool_out(db, t) for t in items], total


def tool_out(db: Session, tool: AITool) -> ToolOut:
    counts = dict(
        db.execute(
            select(AIToolInvocation.status, func.count())
            .where(AIToolInvocation.tool_record_id == tool.id)
            .group_by(AIToolInvocation.status)
        ).all()
    )
    creator = db.get(User, tool.created_by) if tool.created_by else None
    return ToolOut(
        id=tool.id,
        tool_id=tool.tool_id,
        tool_name=tool.tool_name,
        tool_version=tool.tool_version,
        provider=tool.provider,
        description=tool.description,
        adapter=tool.adapter,
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        allowed_actions=tool.allowed_actions,
        permissions=tool.permissions,
        compatible_workflows=tool.compatible_workflows,
        configuration=tool.configuration,
        status=tool.status,
        created_by_username=creator.username if creator else None,
        created_at=tool.created_at,
        invocations=sum(counts.values()),
        failures=sum(v for k, v in counts.items() if k != InvocationStatus.SUCCEEDED),
    )


# --- Invocation -------------------------------------------------------------------------------


def _schema_errors(schema: dict[str, Any], value: Any) -> list[dict[str, Any]]:
    validator = Draft202012Validator(schema)
    return [
        {"location": list(error.absolute_path), "message": error.message}
        for error in sorted(validator.iter_errors(value), key=lambda e: list(e.absolute_path))
    ][:20]


def _run(coroutine_factory, timeout: float):
    """Run an adapter coroutine with a timeout from synchronous code."""

    async def bounded():
        return await asyncio.wait_for(coroutine_factory(), timeout)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(bounded())
    # Called from inside an event loop: run on a separate thread with its own loop.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, bounded()).result()


def invoke(
    db: Session,
    tool: AITool,
    action: str,
    payload: dict[str, Any],
    *,
    actor_id: uuid.UUID | None,
    execution_id: uuid.UUID | None = None,
    simulation_run_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> AIToolInvocation:
    """Call a tool and record the call. Never raises for tool problems: the returned
    invocation's status says what happened, so callers can escalate safely."""
    now = now or datetime.now(UTC)
    record = AIToolInvocation(
        tool_record_id=tool.id,
        tool_id=tool.tool_id,
        tool_version=tool.tool_version,
        action=action,
        input=payload,
        invoked_by=actor_id,
        execution_id=execution_id,
        simulation_run_id=simulation_run_id,
        occurred_at=now,
        usage={},
        duration_ms=0,
    )

    def finish(status: InvocationStatus, *, output=None, error=None) -> AIToolInvocation:
        record.status = status.value
        record.output = output
        record.error = error
        db.add(record)
        db.flush()
        if status == InvocationStatus.BLOCKED:
            record_audit_event(
                db,
                actor_id=actor_id,
                action="ai_tool.invocation_blocked",
                entity_type="ai_tool",
                entity_id=tool.id,
                metadata={"action": action, "reason": error},
            )
        return record

    adapter = get_adapter(tool.adapter)
    if tool.status != ToolStatus.ACTIVE:
        return finish(
            InvocationStatus.BLOCKED,
            error={"code": "tool_disabled", "message": "The tool is disabled."},
        )
    if action not in tool.allowed_actions:
        return finish(
            InvocationStatus.BLOCKED,
            error={
                "code": "action_not_allowed",
                "message": f"The tool is not permitted to perform '{action}'.",
                "allowed_actions": tool.allowed_actions,
            },
        )
    if adapter is None:
        return finish(
            InvocationStatus.FAILED,
            error={"code": "adapter_missing", "message": f"No adapter '{tool.adapter}'."},
        )
    input_errors = _schema_errors(tool.input_schema, payload)
    if input_errors:
        return finish(
            InvocationStatus.INVALID_INPUT,
            error={
                "code": "invalid_input",
                "message": "The request does not match the tool's input schema.",
                "errors": input_errors,
            },
        )

    context = ToolContext(
        tool_id=tool.tool_id,
        tool_version=tool.tool_version,
        configuration=tool.configuration,
        now=now,
        actor_id=str(actor_id) if actor_id else None,
        execution_id=str(execution_id) if execution_id else None,
        correlation_id=correlation_id_var.get(),
    )
    request = ToolRequest(action=action, input=payload)
    timeout = float(tool.configuration.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
    started = time.perf_counter()
    try:
        result = _run(lambda: adapter.execute(request, context), timeout)
    except TimeoutError:
        record.duration_ms = round((time.perf_counter() - started) * 1000)
        return finish(
            InvocationStatus.TIMEOUT,
            error={"code": "timeout", "message": f"No result within {timeout:g} s."},
        )
    except ToolError as exc:
        record.duration_ms = round((time.perf_counter() - started) * 1000)
        return finish(
            InvocationStatus.FAILED,
            error={"code": exc.code, "message": exc.message, "retryable": exc.retryable},
        )
    except Exception as exc:  # noqa: BLE001 - any adapter fault is recorded, never propagated
        record.duration_ms = round((time.perf_counter() - started) * 1000)
        return finish(
            InvocationStatus.FAILED,
            error={"code": "adapter_error", "message": f"{type(exc).__name__}: {exc}"},
        )
    record.duration_ms = round((time.perf_counter() - started) * 1000)
    record.usage = result.usage
    output_errors = _schema_errors(tool.output_schema, result.output)
    if output_errors:
        return finish(
            InvocationStatus.INVALID_OUTPUT,
            output=result.output,
            error={
                "code": "invalid_output",
                "message": "The result does not match the tool's output schema.",
                "errors": output_errors,
            },
        )
    return finish(InvocationStatus.SUCCEEDED, output=result.output)


def invocation_out(i: AIToolInvocation) -> InvocationOut:
    return InvocationOut.model_validate(i, from_attributes=True)


def list_invocations(
    db: Session,
    params: PageParams,
    *,
    tool_record_id: uuid.UUID | None = None,
    status: str | None = None,
    execution_id: uuid.UUID | None = None,
    simulation_run_id: uuid.UUID | None = None,
) -> tuple[list[InvocationOut], int]:
    query = select(AIToolInvocation).order_by(
        AIToolInvocation.created_at.desc(), AIToolInvocation.id
    )
    if tool_record_id:
        query = query.where(AIToolInvocation.tool_record_id == tool_record_id)
    if status:
        query = query.where(AIToolInvocation.status == status)
    if execution_id:
        query = query.where(AIToolInvocation.execution_id == execution_id)
    if simulation_run_id:
        query = query.where(AIToolInvocation.simulation_run_id == simulation_run_id)
    items, total = paginate(db, query, params)
    return [invocation_out(i) for i in items], total
