"""Workflow definitions: typed, validated, and serializable.

A definition is data: steps, transitions and policies. The engine interprets it; business
logic lives in named handlers registered separately (see `registry.py`). Conditions use a
small structured language evaluated against the execution context, never `eval`.
"""

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, ValidationInfo, model_validator
from pydantic_core import PydanticCustomError


class StepType(StrEnum):
    SERVICE_TASK = "service_task"  # automated, runs a registered handler
    HUMAN_TASK = "human_task"  # waits for a person to submit a form
    APPROVAL = "approval"  # waits for an authorized person to approve or reject
    DECISION = "decision"  # routes on conditions over the context
    PARALLEL = "parallel"  # starts several branches
    JOIN = "join"  # waits for every branch of its parallel step
    WAIT = "wait"  # waits for a signal and/or a timer
    AI_TASK = "ai_task"  # calls a registered AI adapter (Phase 6 supplies real tools)
    COMPLETION = "completion"  # ends the execution successfully
    FAILURE = "failure"  # ends the execution as failed


WAITING_TYPES = frozenset({StepType.HUMAN_TASK, StepType.APPROVAL, StepType.WAIT})
TERMINAL_TYPES = frozenset({StepType.COMPLETION, StepType.FAILURE})
HANDLER_TYPES = frozenset({StepType.SERVICE_TASK, StepType.AI_TASK})

Operator = Literal["eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "exists", "truthy"]


class Condition(BaseModel):
    """`path` is a dotted path into the context, e.g. "evaluate_compliance.requires_review"."""

    path: str | None = None
    op: Operator | None = None
    value: Any = None
    all: list["Condition"] | None = None
    any: list["Condition"] | None = None
    negate: bool = False

    @model_validator(mode="after")
    def _shape(self) -> "Condition":
        leaf = self.path is not None and self.op is not None
        combos = sum(x is not None for x in (self.all, self.any))
        if leaf == bool(combos) or combos > 1:
            raise ValueError("A condition is either {path, op, value} or exactly one of all/any.")
        return self

    def evaluate(self, context: dict[str, Any]) -> bool:
        if self.all is not None:
            result = all(c.evaluate(context) for c in self.all)
        elif self.any is not None:
            result = any(c.evaluate(context) for c in self.any)
        else:
            found, actual = resolve(context, self.path or "")
            result = _compare(self.op, found, actual, self.value)
        return not result if self.negate else result


def resolve(context: dict[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = context
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, None
    return True, current


def _compare(op: str | None, found: bool, actual: Any, expected: Any) -> bool:
    if op == "exists":
        return found
    if op == "truthy":
        return found and bool(actual)
    if not found:
        return False
    try:
        match op:
            case "eq":
                return actual == expected
            case "ne":
                return actual != expected
            case "in":
                return actual in expected
            case "not_in":
                return actual not in expected
            case "gt":
                return actual > expected
            case "gte":
                return actual >= expected
            case "lt":
                return actual < expected
            case "lte":
                return actual <= expected
    except TypeError:
        return False
    return False


class Transition(BaseModel):
    to: str
    when: Condition | None = None  # None = unconditional (use last)


class RetryPolicy(BaseModel):
    max_attempts: int = Field(default=3, ge=1, le=20)
    backoff_seconds: int = Field(default=30, ge=0, le=86_400)  # doubled on each retry


class TimeoutPolicy(BaseModel):
    after_seconds: int = Field(gt=0)
    # "flag": record the task as overdue/escalated; "transition": abandon it and go to `to`.
    action: Literal["flag", "transition"] = "flag"
    to: str | None = None


class ApprovalPolicy(BaseModel):
    # The actor must hold every permission listed.
    permissions: list[str] = Field(min_length=1)
    # "initiator" and/or step ids whose actor must be someone else (four-eyes).
    distinct_from: list[str] = Field(default_factory=lambda: ["initiator"])


class FormField(BaseModel):
    name: str
    type: Literal["string", "integer", "boolean"] = "string"
    required: bool = True


class StepDefinition(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    type: StepType
    name: str
    description: str = ""
    handler: str | None = None  # service_task / ai_task
    next: str | None = None
    transitions: list[Transition] = Field(default_factory=list)
    branches: list[str] = Field(default_factory=list)  # parallel: first step of each branch
    join: str | None = None  # parallel: the join step that closes it
    approval: ApprovalPolicy | None = None  # approval and human_task
    form: list[FormField] = Field(default_factory=list)  # human_task
    signal: str | None = None  # wait
    retry: RetryPolicy | None = None  # service_task / ai_task
    on_failure: str | None = None  # where to go when retries are exhausted
    timeout: TimeoutPolicy | None = None
    outcome: str | None = None  # completion: fixed outcome (else context["outcome"])
    # Settings for a library handler (see library.py); checked against its params model.
    params: dict[str, Any] | None = None

    def targets(self) -> list[str]:
        out = [t.to for t in self.transitions] + [x for x in (self.next, self.on_failure) if x]
        out += self.branches
        if self.timeout and self.timeout.to:
            out.append(self.timeout.to)
        return out


class Presentation(BaseModel):
    """How a workflow's cases are named in lists and inboxes: what the case is about
    (`subject_path`) and its risk (`risk_path`), both dotted paths into the context."""

    subject_path: str
    risk_path: str | None = None
    flags_path: str | None = None

    def present(self, context: dict[str, Any]) -> dict[str, Any]:
        def value(path: str | None) -> Any:
            return resolve(context, path)[1] if path else None

        return {
            "subject": value(self.subject_path),
            "risk_rating": value(self.risk_path),
            "flags": value(self.flags_path) or [],
        }


class Catalogue(BaseModel):
    """How a workflow is classified in the catalogue (Phase 22). Optional in a definition:
    when present it sets the workflow's classification as the version is imported."""

    department: str | None = Field(default=None, max_length=100)
    countries: list[Annotated[str, Field(pattern=r"^[A-Z]{2}$")]] = Field(
        default_factory=list, max_length=200
    )  # ISO 3166 alpha-2
    products: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,49}$")]] = Field(
        default_factory=list, max_length=20
    )
    tags: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,49}$")]] = Field(
        default_factory=list, max_length=20
    )

    model_config = {"extra": "forbid"}


class Origin(BaseModel):
    """The template and parameters a generated variant was rendered from."""

    template_id: str
    template_version: int
    variant_key: str


def problem(location: str, code: str, message: str) -> dict[str, str]:
    return {"location": location, "code": code, "message": message}


class WorkflowDefinition(BaseModel):
    workflow_id: str = Field(pattern=r"^WF-\d{4}$")
    name: str
    version: int = Field(ge=1)
    description: str
    business_owner: str
    trigger_type: Literal["api", "event", "schedule", "simulation"] = "api"
    input_schema: dict[str, Any] = Field(default_factory=dict)
    start: str
    steps: list[StepDefinition]
    # Stored definitions carry their presentation; code registers a Presenter instead.
    presentation: Presentation | None = None
    # Set on variants generated from a template (Phase 19): where this definition came from.
    origin: "Origin | None" = None
    # Optional classification (Phase 22); applied to the workflow's catalogue entry.
    catalogue: Catalogue | None = None

    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode="after")
    def _validate_graph(self, info: ValidationInfo) -> "WorkflowDefinition":
        if info.context and info.context.get("defer_graph"):
            return self  # the caller reports graph_problems() with its other checks
        problems = self.graph_problems()
        if problems:
            raise PydanticCustomError(
                "workflow_graph",
                "{summary}",
                {"summary": "; ".join(p["message"] for p in problems), "problems": problems},
            )
        return self

    def graph_problems(self) -> list[dict[str, str]]:
        """Every structural problem of the step graph (not only the first)."""
        problems: list[dict[str, str]] = []
        by_id: dict[str, StepDefinition] = {}
        for step in self.steps:
            if step.id in by_id:
                problems.append(
                    problem(f"steps.{step.id}", "duplicate_step", "Step ids must be unique.")
                )
            by_id[step.id] = step
        if self.start not in by_id:
            problems.append(
                problem("start", "unknown_step", f"Start step '{self.start}' does not exist.")
            )
        for step in self.steps:
            at = f"steps.{step.id}"

            def add(code: str, message: str, at: str = at) -> None:
                problems.append(problem(at, code, message))

            for target in step.targets():
                if target not in by_id:
                    add("unknown_step", f"Step '{step.id}' points to unknown step '{target}'.")
            if step.type in HANDLER_TYPES and not step.handler:
                add("handler_required", f"Step '{step.id}' ({step.type}) needs a handler.")
            if step.type in (StepType.APPROVAL, StepType.HUMAN_TASK) and not step.approval:
                add("approval_required", f"Step '{step.id}' needs an approval policy.")
            if step.type == StepType.APPROVAL and not step.transitions:
                add(
                    "transitions_required",
                    f"Approval '{step.id}' needs approve/reject transitions.",
                )
            if step.type == StepType.WAIT and not (step.signal or step.timeout):
                add("wait_trigger_required", f"Wait '{step.id}' needs a signal and/or a timeout.")
            if step.type == StepType.PARALLEL:
                if len(step.branches) < 2 or not step.join:
                    add("parallel_shape", f"Parallel '{step.id}' needs 2+ branches and a join.")
                elif step.join in by_id and by_id[step.join].type != StepType.JOIN:
                    add("parallel_shape", f"Parallel '{step.id}' join must be a join step.")
                elif step.join not in by_id:
                    add("unknown_step", f"Parallel '{step.id}' joins unknown step '{step.join}'.")
            if step.type == StepType.DECISION and not step.transitions:
                add("transitions_required", f"Decision '{step.id}' needs transitions.")
            if step.type not in TERMINAL_TYPES | {StepType.PARALLEL, StepType.DECISION}:
                if not (step.next or step.transitions):
                    add("no_way_forward", f"Step '{step.id}' has no way forward.")
            if step.timeout and step.timeout.action == "transition" and not step.timeout.to:
                add("timeout_target", f"Step '{step.id}' timeout transition needs 'to'.")
        if not any(s.type == StepType.COMPLETION for s in self.steps):
            problems.append(
                problem("steps", "completion_required", "A workflow needs a completion step.")
            )
        if self.start in by_id and not any(p["code"] == "unknown_step" for p in problems):
            unreachable = set(by_id) - self._reachable(by_id)
            if unreachable:
                problems.append(
                    problem("steps", "unreachable", f"Unreachable steps: {sorted(unreachable)}")
                )
        return problems

    def _reachable(self, by_id: dict[str, StepDefinition]) -> set[str]:
        seen, stack = set(), [self.start]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            step = by_id[current]
            stack.extend(step.targets())
            if step.join:
                stack.append(step.join)
        return seen

    def step(self, step_id: str) -> StepDefinition:
        for step in self.steps:
            if step.id == step_id:
                return step
        raise KeyError(step_id)

    def parallel_for_join(self, join_id: str) -> StepDefinition:
        return next(s for s in self.steps if s.type == StepType.PARALLEL and s.join == join_id)

    def canonical_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    def content_hash(self) -> str:
        payload = json.dumps(self.canonical_json(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    # Views of the definition required by the platform's workflow contract.
    def transition_rules(self) -> list[dict[str, Any]]:
        rules = []
        for s in self.steps:
            for t in s.transitions:
                rules.append(
                    {
                        "from": s.id,
                        "to": t.to,
                        "when": t.when.model_dump(exclude_none=True) if t.when else None,
                    }
                )
            if s.next:
                rules.append({"from": s.id, "to": s.next, "when": None})
            for b in s.branches:
                rules.append({"from": s.id, "to": b, "when": None, "parallel": True})
        return rules

    def approval_policies(self) -> list[dict[str, Any]]:
        return [
            {"step": s.id, **s.approval.model_dump()} for s in self.steps if s.approval is not None
        ]

    def failure_policies(self) -> list[dict[str, Any]]:
        return [
            {
                "step": s.id,
                "retry": (s.retry or RetryPolicy()).model_dump(),
                "on_failure": s.on_failure,
            }
            for s in self.steps
            if s.type in HANDLER_TYPES
        ]

    def timeout_policies(self) -> list[dict[str, Any]]:
        return [{"step": s.id, **s.timeout.model_dump()} for s in self.steps if s.timeout]
