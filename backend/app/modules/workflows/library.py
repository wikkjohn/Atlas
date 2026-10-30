"""The step-handler library: generic handlers that stored definitions may use.

A stored definition (imported as data, see store.py) cannot ship code, so its service
tasks name handlers from this library and configure them with `params`. Each handler
declares a params model, checked when the definition is imported, and the context paths
it reads, checked against what the workflow can know at that point.

This is the first, small set (Milestone B step 1). Step 3 of the roadmap extends it with
screening, posting, AI calls and application calls.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.modules.workflows import registry
from app.modules.workflows.definition import Condition, StepType
from app.modules.workflows.engine import StepContext, StepError


@dataclass(frozen=True)
class LibraryHandler:
    name: str
    step_type: StepType
    summary: str
    params_model: type[BaseModel]
    output: str
    # The context paths a step with these params reads (checked on import).
    reads: Callable[[Any], list[str]]

    def params_schema(self) -> dict[str, Any]:
        return self.params_model.model_json_schema()


LIBRARY: dict[str, LibraryHandler] = {}


def _library_handler(
    name: str,
    summary: str,
    params_model: type[BaseModel],
    output: str,
    reads: Callable[[Any], list[str]] = lambda params: [],
) -> Callable[[Callable[[StepContext, Any], dict[str, Any]]], None]:
    def register(func: Callable[[StepContext, Any], dict[str, Any]]) -> None:
        def run(ctx: StepContext) -> dict[str, Any]:
            return func(ctx, params_model.model_validate(ctx.step.params or {}))

        registry.service_task(name)(run)
        LIBRARY[name] = LibraryHandler(
            name, StepType.SERVICE_TASK, summary, params_model, output, reads
        )

    return register


def get(name: str) -> LibraryHandler | None:
    return LIBRARY.get(name)


Code = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


class SetValues(_Strict):
    values: dict[str, Any] = Field(min_length=1, max_length=50)


@_library_handler(
    "core.set_values",
    "Record fixed values (product codes, limits, flags) in the context.",
    SetValues,
    "The values, under the step's id.",
)
def _set_values(ctx: StepContext, params: SetValues) -> dict[str, Any]:
    return dict(params.values)


class CopyValues(_Strict):
    # Output name -> dotted context path, e.g. {"country": "input.country"}.
    fields: dict[str, str] = Field(min_length=1, max_length=50)
    required: bool = True


@_library_handler(
    "core.copy_values",
    "Copy values from the input or earlier steps under new names.",
    CopyValues,
    "One key per field; a missing path fails the step when `required`.",
    reads=lambda params: list(params.fields.values()),
)
def _copy_values(ctx: StepContext, params: CopyValues) -> dict[str, Any]:
    output, missing = {}, []
    for name, path in params.fields.items():
        sentinel = object()
        value = ctx.get(path, sentinel)
        if value is sentinel:
            missing.append(path)
        else:
            output[name] = value
    if missing and params.required:
        raise StepError("missing_value", "Required values are missing.", {"paths": missing})
    return output


class Check(_Strict):
    condition: Condition
    code: str = Code
    message: str = Field(min_length=1, max_length=300)


def _condition_paths(condition: Condition) -> list[str]:
    if condition.path is not None:
        return [condition.path]
    return [p for c in (condition.all or condition.any or []) for p in _condition_paths(c)]


@_library_handler(
    "core.check",
    "Fail the step with a business error unless a condition holds (route with on_failure).",
    Check,
    "{passed: true}; otherwise the step fails with `code` and `message` (not retried).",
    reads=lambda params: _condition_paths(params.condition),
)
def _check(ctx: StepContext, params: Check) -> dict[str, Any]:
    if not params.condition.evaluate(ctx.context):
        raise StepError(params.code, params.message)
    return {"passed": True}


class BusinessKey(_Strict):
    path: str = Field(min_length=1, max_length=200)
    prefix: str = Field(default="", max_length=40)


@_library_handler(
    "core.business_key",
    "Set the case's business key (what lists and searches show) from a context value.",
    BusinessKey,
    "{business_key}",
    reads=lambda params: [params.path],
)
def _business_key(ctx: StepContext, params: BusinessKey) -> dict[str, Any]:
    sentinel = object()
    value = ctx.get(params.path, sentinel)
    if value is sentinel or value is None:
        raise StepError("missing_value", f"No value at '{params.path}' for the business key.")
    key = f"{params.prefix}{value}"[:100]
    ctx.set_business_key(key)
    return {"business_key": key}


class Notify(_Strict):
    channel: Literal["email", "sms", "letter", "in_app"]
    template: str = Code
    recipient_path: str | None = Field(default=None, max_length=200)


@_library_handler(
    "core.notify",
    "Record a synthetic customer notification (nothing leaves the platform).",
    Notify,
    "{channel, template, recipient, sent_at}",
    reads=lambda params: [params.recipient_path] if params.recipient_path else [],
)
def _notify(ctx: StepContext, params: Notify) -> dict[str, Any]:
    recipient = ctx.get(params.recipient_path) if params.recipient_path else None
    return {
        "channel": params.channel,
        "template": params.template,
        "recipient": recipient,
        "sent_at": ctx.now.isoformat(),
    }


class SetOutcome(_Strict):
    outcome: str = Code


@_library_handler(
    "core.set_outcome",
    "Set the outcome the execution will complete with.",
    SetOutcome,
    "{outcome}",
)
def _set_outcome(ctx: StepContext, params: SetOutcome) -> dict[str, Any]:
    ctx.set_outcome(params.outcome)
    return {"outcome": params.outcome}
