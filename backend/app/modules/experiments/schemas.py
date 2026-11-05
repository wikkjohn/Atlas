import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

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
    country: str | None = Field(
        default=None, pattern=r"^[A-Z]{2}$", description="One active country (Phase 78)"
    )
    costs: CostAssumptions = Field(default_factory=CostAssumptions)
    # None: the scenario's thresholds (Phase 80); given: these, recorded as the request's.
    thresholds: SuccessThresholds | None = None


class ExperimentFromRuns(BaseModel):
    """Evaluate two completed runs (e.g. under different cost assumptions)."""

    name: str = Field(min_length=3, max_length=200)
    baseline_run_id: uuid.UUID
    candidate_run_id: uuid.UUID
    costs: CostAssumptions = Field(default_factory=CostAssumptions)
    # None: the scenario's thresholds (Phase 80); given: these, recorded as the request's.
    thresholds: SuccessThresholds | None = None


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


# --- Repeated-seed series (Phase 77) ----------------------------------------------------------

MAX_REPLICATES = 30


class SeriesCreate(BaseModel):
    """Repeat an experiment over several seeds and test its effect across them."""

    name: str = Field(min_length=3, max_length=200)
    scenario_id: str = "retail-onboarding"
    scenario_version: int | None = Field(default=None, ge=1, description="Defaults to latest")
    tool_id: str = Field(max_length=64)
    tool_version: str | None = Field(default=None, max_length=40)
    candidate_mode: Literal["ai_assisted", "ai_automated"] = "ai_assisted"
    profile: Literal["small", "custom"] = "small"
    applications: int | None = Field(default=None, ge=1, le=MAX_CUSTOM_APPLICATIONS)
    employees: int | None = Field(default=None, ge=3, le=MAX_CUSTOM_EMPLOYEES)
    seed: int = Field(default=42, ge=0, le=MAX_SEED, description="The first seed")
    replicates: int = Field(default=5, ge=2, le=MAX_REPLICATES)
    seeds: list[int] | None = Field(
        default=None,
        min_length=2,
        max_length=MAX_REPLICATES,
        description="Explicit seeds instead of `seed`, `seed + 1`, ... (`replicates` ignored)",
    )
    confidence: float = Field(default=0.95, ge=0.8, le=0.99)
    country: str | None = Field(
        default=None, pattern=r"^[A-Z]{2}$", description="One active country (Phase 78)"
    )
    costs: CostAssumptions = Field(default_factory=CostAssumptions)
    # None: the scenario's thresholds (Phase 80); given: these, recorded as the request's.
    thresholds: SuccessThresholds | None = None

    @field_validator("seeds")
    @classmethod
    def _distinct(cls, seeds: list[int] | None) -> list[int] | None:
        if seeds is not None:
            if len(set(seeds)) != len(seeds):
                raise ValueError("Seeds must be different.")
            if any(not 0 <= s <= MAX_SEED for s in seeds):
                raise ValueError(f"Seeds must be between 0 and {MAX_SEED}.")
        return seeds

    def seed_list(self) -> list[int]:
        return self.seeds if self.seeds is not None else [
            self.seed + i for i in range(self.replicates)
        ]  # fmt: skip


class SeriesSummary(BaseModel):
    id: uuid.UUID
    series_number: int
    name: str
    scenario_id: str
    scenario_version: int
    candidate_mode: str
    tool_id: str | None
    tool_version: str | None
    seeds: list[int]
    confidence: float
    country: str | None
    status: str
    failure_reason: str | None
    verdict: str | None
    replicates_completed: int
    created_by_username: str | None
    created_at: datetime
    completed_at: datetime | None


class SeriesDetail(SeriesSummary):
    configuration: dict[str, Any]
    statistics: dict[str, Any] | None
    experiments: list[ExperimentSummary]


# --- Portfolios (Phase 78) ---------------------------------------------------------------------

MAX_PORTFOLIO_EXPERIMENTS = 600  # cells × seeds


class PortfolioCreate(BaseModel):
    """Evaluate a tool family on every scenario it serves, in each of the countries."""

    name: str = Field(min_length=3, max_length=200)
    family: str = Field(min_length=3, max_length=64)
    candidate_mode: Literal["ai_assisted", "ai_automated"] = "ai_assisted"
    countries: list[str] = Field(min_length=1, max_length=10)
    applications: int = Field(default=60, ge=5, le=MAX_CUSTOM_APPLICATIONS)
    employees: int = Field(default=12, ge=3, le=MAX_CUSTOM_EMPLOYEES)
    seed: int = Field(default=42, ge=0, le=MAX_SEED, description="The first seed of each cell")
    replicates: int = Field(default=3, ge=2, le=MAX_REPLICATES)
    confidence: float = Field(default=0.95, ge=0.8, le=0.99)
    costs: CostAssumptions = Field(default_factory=CostAssumptions)
    # None: the scenario's thresholds (Phase 80); given: these, recorded as the request's.
    thresholds: SuccessThresholds | None = None

    @field_validator("countries")
    @classmethod
    def _countries(cls, countries: list[str]) -> list[str]:
        import re

        if len(set(countries)) != len(countries):
            raise ValueError("Countries must be different.")
        if any(not re.fullmatch(r"[A-Z]{2}", c) for c in countries):
            raise ValueError("Countries are ISO 3166 alpha-2 codes, e.g. GB.")
        return countries


class PortfolioSummary(BaseModel):
    id: uuid.UUID
    portfolio_number: int
    name: str
    family: str
    candidate_mode: str
    countries: list[str]
    seeds: list[int]
    applications: int
    employees: int
    confidence: float
    status: str
    failure_reason: str | None
    verdict: str | None
    cells: int
    cells_completed: int
    created_by_username: str | None
    created_at: datetime
    completed_at: datetime | None


class PortfolioDetail(PortfolioSummary):
    configuration: dict[str, Any]
    statistics: dict[str, Any] | None
    series: list[SeriesSummary]


# --- Scenario thresholds (Phase 80) ------------------------------------------------------------


class ThresholdProposal(BaseModel):
    """Propose a scenario's success thresholds; a risk approver (someone else) decides."""

    scenario_id: str = Field(min_length=3, max_length=64)
    risk_tier: Literal["critical", "high", "medium", "low"]
    thresholds: SuccessThresholds | None = Field(
        default=None, description="Defaults to the risk tier's built-in thresholds"
    )
    rationale: str = Field(min_length=20, max_length=4000)


class ThresholdDecision(BaseModel):
    note: str = Field(default="", max_length=2000)
