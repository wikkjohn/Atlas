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
    source: Literal["code", "stored"] = "code"
    status: Literal["active", "retired"] = "active"  # of the version shown
    template_id: str | None = None  # generated from this template (Phase 19)


class WorkflowDefinitionOut(WorkflowSummary):
    start: str
    input_schema: dict[str, Any]
    presentation: dict[str, Any] | None = None
    origin: dict[str, Any] | None = None  # template, template version and variant key
    last_test: "TestSummary | None" = None  # stored definitions: the latest generated tests
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
    subject: str | None  # what the case is about, e.g. the applicant or the payment
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
    subject: str | None  # what the case is about, e.g. the applicant or the payment
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


# --- Stored definitions (Phase 17) ---------------------------------------------------------


class DefinitionDocument(BaseModel):
    """A workflow definition as JSON (the shape `GET /workflows/{id}/export` returns). It is
    taken as raw data so that validation can report every problem, not the first."""

    definition: dict[str, Any]


class DefinitionProblem(BaseModel):
    location: str
    code: str
    message: str


class ValidationReportOut(BaseModel):
    valid: bool
    workflow_id: str | None
    version: int | None
    content_hash: str | None
    # "new": importable; "identical": already stored unchanged (importing is a no-op).
    existing: Literal["new", "identical"] | None
    errors: list[DefinitionProblem]
    warnings: list[DefinitionProblem]
    # Step id -> what its handler does: reads, writes, moves_money, advisory or none.
    effects: dict[str, str] = Field(default_factory=dict)


class StoredDefinitionOut(BaseModel):
    id: uuid.UUID
    workflow_id: str
    version: int
    name: str
    status: Literal["active", "retired"]
    content_hash: str
    step_count: int
    imported_by: uuid.UUID | None
    imported_by_username: str | None
    imported_at: datetime
    status_changed_at: datetime | None
    executions: int


class ImportResult(BaseModel):
    created: bool  # false: this exact version was already stored
    definition: StoredDefinitionOut
    warnings: list[DefinitionProblem]


class LibraryHandlerOut(BaseModel):
    name: str
    step_type: str
    summary: str
    output: str
    effect: Literal["none", "reads", "writes", "moves_money", "advisory"]
    requires_approval: bool
    params_schema: dict[str, Any]


# --- Templates and variants (Phase 19) --------------------------------------------------------


class TemplateDocumentIn(BaseModel):
    """A template as JSON (taken raw so that validation can report every problem)."""

    template: dict[str, Any]


class TemplateReportOut(BaseModel):
    valid: bool
    template_id: str | None
    version: int | None
    existing: Literal["new", "identical"] | None
    errors: list[DefinitionProblem]
    warnings: list[DefinitionProblem]
    preview: dict[str, Any] | None  # the example parameters rendered


class TemplateOut(BaseModel):
    id: uuid.UUID
    template_id: str
    version: int
    name: str
    description: str
    status: Literal["active", "retired"]
    content_hash: str
    id_range: tuple[int, int]
    parameters: dict[str, Any]
    example: dict[str, Any]
    imported_by_username: str | None
    imported_at: datetime
    variants: int  # generated from any version of this template


class TemplateDetail(TemplateOut):
    body: dict[str, Any]


class TemplateImportResult(BaseModel):
    created: bool
    template: TemplateOut
    warnings: list[DefinitionProblem]


class RenderIn(BaseModel):
    params: dict[str, Any]
    version: int | None = Field(default=None, ge=1)


class RenderOut(BaseModel):
    definition: dict[str, Any] | None
    report: ValidationReportOut


class GenerateIn(BaseModel):
    """Parameter sets: the cartesian product of `grid` plus `variants`, each over `fixed`."""

    grid: dict[str, list[Any]] | None = None
    variants: list[dict[str, Any]] | None = None
    fixed: dict[str, Any] | None = None
    version: int | None = Field(default=None, ge=1)
    dry_run: bool = False


class VariantResultOut(BaseModel):
    variant_key: str
    params: dict[str, Any]
    workflow_id: str | None
    version: int | None
    status: Literal["created", "updated", "unchanged", "invalid"]
    errors: list[DefinitionProblem]


class GenerationOut(BaseModel):
    template_id: str
    template_version: int
    dry_run: bool
    stored: bool  # false for a dry run, or when any variant was invalid (nothing stored)
    created: int
    updated: int
    unchanged: int
    invalid: int
    results: list[VariantResultOut]


class VariantOut(BaseModel):
    workflow_id: str
    variant_key: str
    params: dict[str, Any]
    template_version: int
    definition_version: int
    generated_at: datetime


# --- Generated tests (Phase 20) --------------------------------------------------------------


class TestCaseOut(BaseModel):
    name: str
    kind: str
    route: str | None
    status: Literal["passed", "failed", "skipped"]
    detail: str
    outcome: str | None
    visited: list[str]
    mocked: list[str]
    ms: int


class TestRunOut(BaseModel):
    id: uuid.UUID
    workflow_id: str
    version: int
    passed: int
    failed: int
    skipped: int
    step_coverage: float
    route_coverage: float
    cases: list[TestCaseOut]
    uncovered: list[dict[str, str]]
    duration_ms: int
    ran_at: datetime
    ran_by_username: str | None


class TestSummary(BaseModel):
    passed: int
    failed: int
    step_coverage: float
    route_coverage: float
    ran_at: datetime


# --- Graph and editor preview (Phase 21) -----------------------------------------------------


class DraftPreview(BaseModel):
    """A draft definition's validation report and, when it parses, its graph."""

    report: ValidationReportOut
    graph: dict[str, Any] | None
