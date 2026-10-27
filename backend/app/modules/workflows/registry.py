"""Registries of workflow definitions and the handlers their steps name."""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.modules.workflows.definition import HANDLER_TYPES, StepType, WorkflowDefinition

Handler = Callable[[Any], dict[str, Any] | None]

_DEFINITIONS: dict[tuple[str, int], WorkflowDefinition] = {}
_INPUT_MODELS: dict[tuple[str, int], type[BaseModel]] = {}
_SERVICE_HANDLERS: dict[str, Handler] = {}
_AI_HANDLERS: dict[str, Handler] = {}


def service_task(name: str) -> Callable[[Handler], Handler]:
    def register(func: Handler) -> Handler:
        _SERVICE_HANDLERS[name] = func
        return func

    return register


def ai_task(name: str) -> Callable[[Handler], Handler]:
    """Register an AI adapter for `ai_task` steps. The AI Innovation Lab (Phase 6) plugs its
    provider-independent tool adapters in here; the engine only sees this interface."""

    def register(func: Handler) -> Handler:
        _AI_HANDLERS[name] = func
        return func

    return register


def handler_for(step_type: StepType, name: str) -> Handler | None:
    table = _AI_HANDLERS if step_type == StepType.AI_TASK else _SERVICE_HANDLERS
    return table.get(name)


def register_definition(definition: WorkflowDefinition, input_model: type[BaseModel]) -> None:
    """Add a definition. Versions are immutable: re-registering must be identical."""
    key = (definition.workflow_id, definition.version)
    definition.input_schema = input_model.model_json_schema()
    existing = _DEFINITIONS.get(key)
    if existing is not None and existing.content_hash() != definition.content_hash():
        raise ValueError(f"{key} is already registered with different content; bump the version.")
    missing = [
        s.handler
        for s in definition.steps
        if s.type in HANDLER_TYPES and handler_for(s.type, s.handler or "") is None
    ]
    if missing:
        raise ValueError(f"Unregistered handlers: {missing}")
    _DEFINITIONS[key] = definition
    _INPUT_MODELS[key] = input_model


def unregister_definition(workflow_id: str, version: int) -> None:
    _DEFINITIONS.pop((workflow_id, version), None)
    _INPUT_MODELS.pop((workflow_id, version), None)


def get_definition(workflow_id: str, version: int | None = None) -> WorkflowDefinition | None:
    if version is not None:
        return _DEFINITIONS.get((workflow_id, version))
    versions = [v for (wid, v) in _DEFINITIONS if wid == workflow_id]
    return _DEFINITIONS[(workflow_id, max(versions))] if versions else None


def input_model(workflow_id: str, version: int) -> type[BaseModel]:
    return _INPUT_MODELS[(workflow_id, version)]


def all_definitions() -> list[WorkflowDefinition]:
    return sorted(_DEFINITIONS.values(), key=lambda d: (d.workflow_id, d.version))
