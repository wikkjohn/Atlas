import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class WorkflowSummary(BaseModel):
    workflow_id: str
    name: str
    version: int
    versions: list[int]
    description: str
    business_owner: str
    trigger_type: str
    step_count: int


class WorkflowDefinitionOut(WorkflowSummary):
    start: str
    input_schema: dict[str, Any]
    steps: list[dict[str, Any]]
    transition_rules: list[dict[str, Any]]
    approval_policies: list[dict[str, Any]]
    failure_policies: list[dict[str, Any]]
    timeout_policies: list[dict[str, Any]]


class StartExecution(BaseModel):
    input: dict[str, Any]


class TaskCompletion(BaseModel):
    decision: Literal["approve", "reject"] | None = None
    data: dict[str, Any] | None = None
    note: str | None = Field(default=None, max_length=500)


class SignalIn(BaseModel):
    signal: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


class CancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class ExecutionSummary(BaseModel):
    id: uuid.UUID
    workflow_id: str
    workflow_version: int
    status: str
    outcome: str | None
    current_steps: list[str]
    business_key: str | None
    applicant: str | None
    initiated_by: uuid.UUID
    initiated_by_username: str | None
    correlation_id: str | None
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None
    simulation_run_id: uuid.UUID | None = None  # set when driven on simulated time


class StepRunOut(BaseModel):
    id: uuid.UUID
    sequence: int
    step_id: str
    step_name: str
    step_type: str
    status: str
    branch: str | None
    attempt: int
    required_permissions: list[str]
    actor_id: uuid.UUID | None
    actor_username: str | None
    output: dict[str, Any] | None
    error: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    not_before: datetime | None
    due_at: datetime | None
    escalated_at: datetime | None


class ExecutionDetail(ExecutionSummary):
    context: dict[str, Any]
    error: dict[str, Any] | None
    steps: list[StepRunOut]


class WorkflowEventOut(BaseModel):
    id: uuid.UUID
    event_type: str
    occurred_at: datetime
    step_run_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    data: dict[str, Any]


class TaskOut(BaseModel):
    run_id: uuid.UUID
    execution_id: uuid.UUID
    workflow_id: str
    step_id: str
    step_name: str
    step_type: str
    opened_at: datetime | None
    due_at: datetime | None
    overdue: bool
    required_permissions: list[str]
    can_act: bool
    blocked_reason: str | None
    applicant: str | None
    risk_rating: str | None
    flags: list[str]
    initiated_by_username: str | None


class StepMetric(BaseModel):
    step_id: str
    step_name: str
    step_type: str
    runs: int
    completed: int
    failed: int
    open: int
    retries: int
    avg_ms: float | None
    p50_ms: float | None
    p95_ms: float | None
    max_ms: int | None


class WorkflowMetrics(BaseModel):
    workflow_id: str
    executions: dict[str, int]
    outcomes: dict[str, int]
    avg_execution_ms: float | None
    bottleneck_step: str | None
    steps: list[StepMetric]
