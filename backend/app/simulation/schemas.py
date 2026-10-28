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
    workflow_id: str
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


class SimulationRunDetail(SimulationRunSummary):
    config: dict[str, Any]
    results: dict[str, Any] | None
    simulated_start: datetime
    simulated_end: datetime | None
    staff_unit_id: uuid.UUID | None
    reproductions: list[Reproduction]


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
