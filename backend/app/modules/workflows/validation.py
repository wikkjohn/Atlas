"""Full validation of a workflow definition document before it is imported.

The definition model already checks the graph's shape (every target exists, every step is
reachable, approvals have policies, …). Importing data rather than code needs more, so
this module also checks, collecting every problem rather than stopping at the first:

- ownership: the workflow id is not one registered in code;
- versions: a new version is higher than every stored one, and an existing version is
  either re-imported unchanged or refused (versions are immutable);
- termination: every step can still reach a completion or failure step;
- handlers: service tasks name a library handler and their params match its model;
- context paths: conditions, handler params and presentation read the input's fields,
  earlier steps' outputs or known keys — a typo is caught here, not in production;
- permissions: approval policies name real permissions that some person's role holds,
  and four-eyes references point at task or approval steps;
- input: the input schema is a valid JSON Schema (draft 2020-12) for an object.

Errors block the import; warnings are worth reading but do not.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import ROLE_PERMISSIONS, SERVICE_ROLES, Permission
from app.modules.workflows import library, registry
from app.modules.workflows.definition import (
    HANDLER_TYPES,
    TERMINAL_TYPES,
    WAITING_TYPES,
    Condition,
    StepType,
    WorkflowDefinition,
    problem,
)
from app.modules.workflows.models import WorkflowDefinitionRecord

MAX_DOCUMENT_BYTES = 256 * 1024
MAX_STEPS = 200
# Context keys every execution may have besides the input and the step outputs.
KNOWN_KEYS = frozenset({"input", "outcome", "_settings", "_failure"})
STORED_TRIGGERS = frozenset({"api", "event"})
NAME = r"^[a-z][a-z0-9_]{0,63}$"


@dataclass
class Report:
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    definition: WorkflowDefinition | None = None
    # "new" (importable), "identical" (already stored, unchanged) or None (invalid).
    existing: str | None = None

    @property
    def valid(self) -> bool:
        return not self.errors

    def error(self, location: str, code: str, message: str) -> None:
        self.errors.append(problem(location, code, message))

    def warn(self, location: str, code: str, message: str) -> None:
        self.warnings.append(problem(location, code, message))


def _location(loc: tuple[Any, ...]) -> str:
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out or "document"


def validate(db: Session | None, document: dict[str, Any]) -> Report:
    report = Report()
    size = len(json.dumps(document, separators=(",", ":")).encode())
    if size > MAX_DOCUMENT_BYTES:
        report.error(
            "document",
            "too_large",
            f"The document is {size} bytes; the limit is {MAX_DOCUMENT_BYTES}.",
        )
        return report
    if len(document.get("steps") or []) > MAX_STEPS:
        report.error("steps", "too_many_steps", f"At most {MAX_STEPS} steps per definition.")
        return report
    try:
        definition = WorkflowDefinition.model_validate(document, context={"defer_graph": True})
    except ValidationError as exc:
        for e in exc.errors():
            report.error(_location(e["loc"]), e["type"], e["msg"])
        return report
    report.definition = definition
    report.errors.extend(definition.graph_problems())

    _check_ownership(report, definition)
    _check_input_schema(report, definition)
    _check_steps(report, definition)
    if not any(e["code"] == "unknown_step" for e in report.errors):
        _check_termination(report, definition)
    if db is not None and report.valid:
        _check_versions(db, report, definition)
    return report


def _check_ownership(report: Report, d: WorkflowDefinition) -> None:
    if registry.get_definition(d.workflow_id) is not None:
        report.error(
            "workflow_id",
            "owned_by_code",
            f"{d.workflow_id} is registered in code; "
            "stored definitions need a workflow id of their own.",
        )
    if d.trigger_type not in STORED_TRIGGERS:
        report.error(
            "trigger_type",
            "trigger_unsupported",
            "Stored definitions are started "
            "through the API or by events; schedules and simulation workloads are "
            "registered in code.",
        )


def _input_fields(d: WorkflowDefinition) -> set[str]:
    return set((d.input_schema.get("properties") or {}).keys())


def _check_input_schema(report: Report, d: WorkflowDefinition) -> None:
    schema = d.input_schema
    if not schema:
        report.error("input_schema", "schema_required", "An input schema is required.")
        return
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        report.error("input_schema", "schema_invalid", exc.message)
        return
    if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
        report.error(
            "input_schema",
            "schema_not_object",
            "The input schema must describe an object with properties.",
        )
        return
    unknown = sorted(set(schema.get("required") or []) - _input_fields(d))
    if unknown:
        report.error(
            "input_schema.required",
            "unknown_field",
            f"Required fields that are not properties: {unknown}",
        )
    if schema.get("additionalProperties") is not False:
        report.warn(
            "input_schema",
            "open_input",
            "additionalProperties is not false: unknown input fields are accepted and stored.",
        )


def _check_path(report: Report, d: WorkflowDefinition, location: str, path: str) -> None:
    root, _, rest = path.partition(".")
    step_ids = {s.id for s in d.steps}
    if root not in step_ids and root not in KNOWN_KEYS:
        report.error(
            location,
            "unknown_path",
            f"'{path}' reads '{root}', which is neither a step, the input nor a known context key.",
        )
    elif root == "input":
        field_name = rest.partition(".")[0]
        if not field_name or field_name not in _input_fields(d):
            report.error(
                location,
                "unknown_input_field",
                f"'{path}' reads an input field the input schema does not define.",
            )


def _condition_paths(condition: Condition) -> list[str]:
    if condition.path is not None:
        return [condition.path]
    return [p for c in (condition.all or condition.any or []) for p in _condition_paths(c)]


def _human_roles_with(permissions: set[str]) -> list[str]:
    return [
        role.value
        for role, granted in ROLE_PERMISSIONS.items()
        if role not in SERVICE_ROLES and permissions <= {p.value for p in granted}
    ]


def _check_steps(report: Report, d: WorkflowDefinition) -> None:
    by_id = {s.id: s for s in d.steps}
    valid_permissions = {p.value for p in Permission}
    sets_outcome = any(s.handler == "core.set_outcome" for s in d.steps)
    for step in d.steps:
        at = f"steps.{step.id}"
        # Handlers and their params
        if step.type == StepType.AI_TASK:
            report.error(
                at,
                "handler_unavailable",
                "AI steps need an AI handler from the "
                "library; none is available to stored definitions yet.",
            )
        elif step.type in HANDLER_TYPES:
            found = library.get(step.handler or "")
            if found is None:
                report.error(
                    f"{at}.handler",
                    "unknown_handler",
                    f"'{step.handler}' is not in "
                    f"the handler library ({', '.join(sorted(library.LIBRARY))}).",
                )
            else:
                try:
                    params = found.params_model.model_validate(step.params or {})
                except ValidationError as exc:
                    for e in exc.errors():
                        report.error(
                            f"{at}.params{'.' if e['loc'] else ''}"
                            f"{_location(e['loc']) if e['loc'] else ''}",
                            e["type"],
                            e["msg"],
                        )
                else:
                    for path in found.reads(params):
                        _check_path(report, d, f"{at}.params", path)
        elif step.params is not None:
            report.error(f"{at}.params", "params_unused", "Only service tasks take params.")
        # Conditions
        for i, transition in enumerate(step.transitions):
            if transition.when is not None:
                for path in _condition_paths(transition.when):
                    _check_path(report, d, f"{at}.transitions[{i}].when", path)
        if (
            step.type == StepType.DECISION
            and step.transitions[-1:]
            and (step.transitions[-1].when is not None and not step.next)
        ):
            report.warn(
                at,
                "no_fallback",
                "No unconditional route: when no condition "
                "matches, the execution fails with no_route.",
            )
        # People
        if step.approval is not None:
            unknown = [p for p in step.approval.permissions if p not in valid_permissions]
            if unknown:
                report.error(
                    f"{at}.approval.permissions",
                    "unknown_permission",
                    f"Unknown permissions: {unknown}",
                )
            else:
                roles = _human_roles_with(set(step.approval.permissions))
                if not roles:
                    report.error(
                        f"{at}.approval.permissions",
                        "nobody_can_act",
                        "No person's role holds all of these permissions.",
                    )
                elif roles == ["platform_administrator"]:
                    report.warn(
                        f"{at}.approval.permissions",
                        "administrators_only",
                        "Only platform administrators can act on this step.",
                    )
            for ref in step.approval.distinct_from:
                if ref != "initiator" and (
                    ref not in by_id
                    or by_id[ref].type not in (StepType.APPROVAL, StepType.HUMAN_TASK)
                ):
                    report.error(
                        f"{at}.approval.distinct_from",
                        "unknown_task",
                        f"'{ref}' is not 'initiator' or a task or approval step.",
                    )
        names = [f.name for f in step.form]
        if len(names) != len(set(names)):
            report.error(f"{at}.form", "duplicate_field", "Form field names must be unique.")
        # Waiting
        if step.timeout is not None and step.type not in WAITING_TYPES:
            report.error(
                f"{at}.timeout",
                "timeout_unsupported",
                "Timeouts apply to human tasks, approvals and waits only.",
            )
        if step.signal is not None and not re.fullmatch(NAME, step.signal):
            report.error(f"{at}.signal", "invalid_name", "Signal names are lower_snake_case.")
        if step.type == StepType.COMPLETION and step.outcome is None and not sets_outcome:
            report.warn(
                at,
                "no_outcome",
                "This completion has no outcome and no step sets "
                "one; executions finish without an outcome.",
            )
    if d.presentation is not None:
        for name in ("subject_path", "risk_path", "flags_path"):
            path = getattr(d.presentation, name)
            if path:
                _check_path(report, d, f"presentation.{name}", path)
    else:
        report.warn(
            "presentation",
            "no_presentation",
            "Without a presentation, task inboxes and lists show no subject for these cases.",
        )


def _check_termination(report: Report, d: WorkflowDefinition) -> None:
    """Every step must still be able to reach an end (no trap loops)."""
    predecessors: dict[str, set[str]] = {s.id: set() for s in d.steps}
    for step in d.steps:
        for target in step.targets() + ([step.join] if step.join else []):
            predecessors.setdefault(target, set()).add(step.id)
    finishing = {s.id for s in d.steps if s.type in TERMINAL_TYPES}
    stack = list(finishing)
    while stack:
        for before in predecessors.get(stack.pop(), ()):
            if before not in finishing:
                finishing.add(before)
                stack.append(before)
    trapped = sorted({s.id for s in d.steps} - finishing)
    if trapped:
        report.error(
            "steps",
            "cannot_finish",
            f"These steps can never reach a completion or failure step: {trapped}",
        )


def _check_versions(db: Session, report: Report, d: WorkflowDefinition) -> None:
    rows = db.execute(
        select(WorkflowDefinitionRecord.version, WorkflowDefinitionRecord.content_hash).where(
            WorkflowDefinitionRecord.workflow_id == d.workflow_id
        )
    ).all()
    versions = dict(rows)
    if d.version in versions:
        if versions[d.version] == d.content_hash():
            report.existing = "identical"
        else:
            report.error(
                "version",
                "version_exists",
                f"{d.workflow_id} v{d.version} is "
                "already stored with different content; versions are immutable — "
                "import it as a new version.",
            )
        return
    latest = max(versions, default=0)
    if d.version <= latest:
        report.error(
            "version",
            "version_not_increasing",
            f"The latest stored version of "
            f"{d.workflow_id} is {latest}; a new version must be higher.",
        )
        return
    report.existing = "new"
