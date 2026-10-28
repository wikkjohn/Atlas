import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.modules.experiments.assumptions import CostAssumptions, SuccessThresholds
from app.simulation.scenarios import MAX_CUSTOM_APPLICATIONS, MAX_CUSTOM_EMPLOYEES
from app.simulation.schemas import MAX_SEED


class ExperimentCreate(BaseModel):
    """Run a baseline and a candidate on the same seeded workload, then evaluate."""

    name: str = Field(min_length=3, max_length=200)
    scenario_id: str = "retail-onboarding"
    scenario_version: int | None = Field(default=None, ge=1, description="Defaults to latest")
    tool_id: str = Field(max_length=64)
    tool_version: str | None = Field(default=None, max_length=40)
    candidate_mode: Literal["ai_assisted", "ai_automated"] = "ai_assisted"
    profile: Literal["small", "department", "custom"] = "small"
    applications: int | None = Field(default=None, ge=1, le=MAX_CUSTOM_APPLICATIONS)
    employees: int | None = Field(default=None, ge=3, le=MAX_CUSTOM_EMPLOYEES)
    seed: int = Field(default=42, ge=0, le=MAX_SEED)
    costs: CostAssumptions = Field(default_factory=CostAssumptions)
    thresholds: SuccessThresholds = Field(default_factory=SuccessThresholds)


class ExperimentFromRuns(BaseModel):
    """Evaluate two completed runs (e.g. under different cost assumptions)."""

    name: str = Field(min_length=3, max_length=200)
    baseline_run_id: uuid.UUID
    candidate_run_id: uuid.UUID
    costs: CostAssumptions = Field(default_factory=CostAssumptions)
    thresholds: SuccessThresholds = Field(default_factory=SuccessThresholds)


class RunRef(BaseModel):
    id: uuid.UUID
    run_number: int
    mode: str
    status: str
    percent_complete: float
    failure_reason: str | None


class ExperimentSummary(BaseModel):
    id: uuid.UUID
    experiment_number: int
    name: str
    scenario_id: str
    scenario_version: int
    candidate_mode: str
    tool_id: str | None
    tool_version: str | None
    status: str
    failure_reason: str | None
    verdict: str | None
    created_by_username: str | None
    created_at: datetime
    completed_at: datetime | None
    baseline: RunRef
    candidate: RunRef
    headline: dict[str, float | None]  # relative changes of key metrics


class Measurement(BaseModel):
    run_id: uuid.UUID
    role: str
    metrics: dict[str, Any]
    measurement_digest: str
    captured_at: datetime


class Evaluation(BaseModel):
    evaluation_version: str
    costs: dict[str, Any]
    comparisons: list[dict[str, Any]]
    criteria: list[dict[str, Any]]
    verdict: str
    conclusion: str
    limitations: list[str]
    evaluation_digest: str
    computed_at: datetime


class ExperimentDetail(ExperimentSummary):
    configuration: dict[str, Any]
    configuration_hash: str
    measurements: list[Measurement]  # raw
    evaluation: Evaluation | None  # derived


class ReEvaluation(BaseModel):
    stored_digest: str
    recomputed_digest: str
    matches: bool


class BenchmarkRow(BaseModel):
    tool_id: str
    tool_version: str
    candidate_mode: str
    experiments: int
    successful: int
    latest_experiment_id: uuid.UUID
    latest_verdict: str | None
    median_relative_change: dict[str, float | None]
