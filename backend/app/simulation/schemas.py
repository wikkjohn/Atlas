import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.simulation.scenarios import MAX_CUSTOM_APPLICATIONS, MAX_CUSTOM_EMPLOYEES

MAX_SEED = 2**53 - 1  # exact in JavaScript too


class ScenarioOut(BaseModel):
    scenario_id: str
    version: int
    name: str
    description: str
    workload: str
    workflow_id: str
    workflow_version: int
    modes: list[str]
    simulated_start: datetime
    config: dict[str, Any]


class ProfileOut(BaseModel):
    profile_id: str
    name: str
    applications: int
    customers: int
    employees: int
    status: Literal["verified", "target"]
    runnable: bool
    note: str


class StartSimulation(BaseModel):
    scenario_id: str = "retail-onboarding"
    scenario_version: int | None = Field(default=None, ge=1, description="Defaults to latest")
    profile: Literal["small", "department", "enterprise", "custom"] = "small"
    seed: int = Field(default=42, ge=0, le=MAX_SEED)
    applications: int | None = Field(
        default=None, ge=1, le=MAX_CUSTOM_APPLICATIONS, description="Custom profile only"
    )
    employees: int | None = Field(
        default=None, ge=3, le=MAX_CUSTOM_EMPLOYEES, description="Custom profile only"
    )
    mode: Literal["baseline", "ai_assisted", "ai_automated"] = "baseline"
    tool_id: str | None = Field(default=None, max_length=64, description="AI modes only")
    tool_version: str | None = Field(
        default=None, max_length=40, description="Defaults to the highest active version"
    )


class StartSuite(BaseModel):
    """Several modes on the same scenario, seed and workload, executed one after another."""

    scenario_id: str = "retail-onboarding"
    scenario_version: int | None = Field(default=None, ge=1)
    profile: Literal["small", "department", "custom"] = "small"
    seed: int = Field(default=42, ge=0, le=MAX_SEED)
    applications: int | None = Field(default=None, ge=1, le=MAX_CUSTOM_APPLICATIONS)
    employees: int | None = Field(default=None, ge=3, le=MAX_CUSTOM_EMPLOYEES)
    modes: list[Literal["baseline", "ai_assisted", "ai_automated"]] = Field(
        default_factory=lambda: ["baseline", "ai_assisted", "ai_automated"],
        min_length=1,
        max_length=3,
    )
    tool_id: str | None = Field(default=None, max_length=64)
    tool_version: str | None = Field(default=None, max_length=40)


class Reproduction(BaseModel):
    id: uuid.UUID
    run_number: int
    result_digest: str | None
    matches: bool


class SimulationRunSummary(BaseModel):
    id: uuid.UUID
    run_number: int
    scenario_id: str
    scenario_version: int
    workflow_id: str
    workflow_version: int
    profile: str
    seed: int
    applications: int
    employees: int
    status: str
    failure_reason: str | None
    software_version: str
    config_hash: str
    result_digest: str | None
    created_by_username: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    wall_ms: int | None
    progress: dict[str, Any]
    percent_complete: float
    mode: str
    tool_id: str | None
    tool_version: str | None
    batch_id: uuid.UUID | None
    # Where the run's workflow history is: present, archived or purged (Phase 15).
    history_state: str


class ArchiveOut(BaseModel):
    """An archive (or purge) of a run's workflow history."""

    id: uuid.UUID
    run_id: uuid.UUID
    run_number: int
    kind: str
    location: str | None
    rows: int
    bytes: int
    tables: dict[str, int]  # rows per table
    created_by_username: str | None
    created_at: datetime


class PartitionUsage(BaseModel):
    table: str
    realm: str
    rows_estimate: int
    bytes: int


class HistoryOverview(BaseModel):
    """How much room workflow history takes, live and simulated, and what is archived."""

    partitions: list[PartitionUsage]
    runs_by_history_state: dict[str, int]
    archive_directory: str
    archive_bytes: int
    recent_archives: list[ArchiveOut]
    retention_schedule_enabled: bool | None


class SimulationRunDetail(SimulationRunSummary):
    config: dict[str, Any]
    results: dict[str, Any] | None
    simulated_start: datetime
    simulated_end: datetime | None
    staff_unit_id: uuid.UUID | None
    reproductions: list[Reproduction]
    archive: ArchiveOut | None


class CaseResultOut(BaseModel):
    case_index: int
    execution_id: uuid.UUID | None
    kind: str
    expected_outcome: str
    status: str
    outcome: str | None
    matches_ground_truth: bool
    risk_rating: str | None
    flags: list[str]
    manual_reviews: int
    review_minutes: float
    queue_wait_minutes: float
    overdue_tasks: int
    arrived_at: datetime
    completed_at: datetime | None
    cycle_hours: float | None
    path: list[str]
    ai_recommendation: str | None
    ai_status: str | None
    automated: bool
