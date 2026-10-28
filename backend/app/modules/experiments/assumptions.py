"""Cost assumptions and success thresholds: explicit, editable, stored with every
experiment. Default values are illustrative for synthetic data — not benchmarks of any
real bank — and every report says so."""

from pydantic import BaseModel, Field


class CostAssumptions(BaseModel):
    currency_label: str = Field(default="USD (illustrative)", max_length=40)
    reviewer_cost_per_minute: float = Field(default=0.85, ge=0)  # fully loaded employee cost
    ai_cost_per_invocation: float = Field(default=0.04, ge=0)  # executed calls, incl. failed
    infrastructure_cost_per_run: float = Field(default=20.0, ge=0)  # fixed per workload
    infrastructure_cost_per_case: float = Field(default=0.02, ge=0)
    exception_handling_cost: float = Field(default=12.0, ge=0)  # per workflow exception
    manual_escalation_cost: float = Field(default=6.0, ge=0)  # per compliance escalation
    # Human oversight of automation: a share of automated decisions is re-checked.
    oversight_sample_rate: float = Field(default=0.10, ge=0, le=1)
    oversight_minutes_per_sample: float = Field(default=6.0, ge=0)
    # Risk exposure of wrong decisions, reported separately from operating cost.
    false_approval_cost: float = Field(default=750.0, ge=0)
    false_rejection_cost: float = Field(default=60.0, ge=0)
    notes: str = Field(default="", max_length=2000)


class SuccessThresholds(BaseModel):
    min_improvement: float = Field(default=0.05, ge=0, le=1)  # on time, labour or cost
    max_accuracy_drop: float = Field(default=0.005, ge=0, le=1)  # vs. the baseline
    max_false_approval_rate: float = Field(default=0.05, ge=0, le=1)  # of should-reject cases
    max_false_rejection_rate: float = Field(default=0.05, ge=0, le=1)  # of should-approve cases
    max_error_rate: float = Field(default=0.05, ge=0, le=1)  # errors per case
    max_policy_violations: int = Field(default=0, ge=0)
    regression_tolerance: float = Field(default=0.01, ge=0, le=1)  # relative worsening allowed


class EvaluationConfig(BaseModel):
    costs: CostAssumptions = Field(default_factory=CostAssumptions)
    thresholds: SuccessThresholds = Field(default_factory=SuccessThresholds)
