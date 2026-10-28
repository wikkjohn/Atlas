import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class Metric(BaseModel):
    """One dashboard figure, with where it comes from and what it includes."""

    key: str
    label: str
    value: float | int | None
    unit: str  # count | hours | ms | currency
    detail: str
    synthetic: bool = True
    estimate: bool = False  # derived from assumptions rather than counted


class RecentRun(BaseModel):
    id: uuid.UUID
    run_number: int
    mode: str
    status: str
    applications: int
    created_at: datetime


class RecentExperiment(BaseModel):
    id: uuid.UUID
    experiment_number: int
    name: str
    status: str
    verdict: str | None
    tool_id: str | None
    created_at: datetime


class Overview(BaseModel):
    generated_at: datetime
    metrics: list[Metric]
    workflow_outcomes: dict[str, int]  # live executions
    open_tasks: int
    simulation_runs_by_status: dict[str, int]
    cost_assumptions: dict[str, Any]
    recent_runs: list[RecentRun]
    recent_experiments: list[RecentExperiment]
