"""Workflow definitions: typed, validated, and serializable.

A definition is data: steps, transitions and policies. The engine interprets it; business
logic lives in named handlers registered separately (see `registry.py`). Conditions use a
small structured language evaluated against the execution context, never `eval`.
"""

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


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

    def targets(self) -> list[str]:
        out = [t.to for t in self.transitions] + [x for x in (self.next, self.on_failure) if x]
        out += self.branches
        if self.timeout and self.timeout.to:
            out.append(self.timeout.to)
        return out


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

    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode="after")
    def _validate_graph(self) -> "WorkflowDefinition":
        by_id = {s.id: s for s in self.steps}
        if len(by_id) != len(self.steps):
            raise ValueError("Step ids must be unique.")
        if self.start not in by_id:
            raise ValueError(f"Start step '{self.start}' does not exist.")
        for step in self.steps:
            for target in step.targets():
                if target not in by_id:
                    raise ValueError(f"Step '{step.id}' points to unknown step '{target}'.")
            if step.type in HANDLER_TYPES and not step.handler:
                raise ValueError(f"Step '{step.id}' ({step.type}) needs a handler.")
            if step.type in (StepType.APPROVAL, StepType.HUMAN_TASK) and not step.approval:
                raise ValueError(f"Step '{step.id}' needs an approval policy.")
            if step.type == StepType.APPROVAL and not step.transitions:
                raise ValueError(f"Approval '{step.id}' needs approve/reject transitions.")
            if step.type == StepType.WAIT and not (step.signal or step.timeout):
                raise ValueError(f"Wait '{step.id}' needs a signal and/or a timeout.")
            if step.type == StepType.PARALLEL:
                if len(step.branches) < 2 or not step.join:
                    raise ValueError(f"Parallel '{step.id}' needs 2+ branches and a join.")
                if by_id[step.join].type != StepType.JOIN:
                    raise ValueError(f"Parallel '{step.id}' join must be a join step.")
            if step.type == StepType.DECISION and not step.transitions:
                raise ValueError(f"Decision '{step.id}' needs transitions.")
            if step.type not in TERMINAL_TYPES | {StepType.PARALLEL, StepType.DECISION}:
                if not (step.next or step.transitions):
                    raise ValueError(f"Step '{step.id}' has no way forward.")
            if step.timeout and step.timeout.action == "transition" and not step.timeout.to:
                raise ValueError(f"Step '{step.id}' timeout transition needs 'to'.")
        if not any(s.type == StepType.COMPLETION for s in self.steps):
            raise ValueError("A workflow needs a completion step.")
        unreachable = set(by_id) - self._reachable(by_id)
        if unreachable:
            raise ValueError(f"Unreachable steps: {sorted(unreachable)}")
        return self

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
