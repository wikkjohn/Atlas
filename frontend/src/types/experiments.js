// Mirrors backend/app/modules/experiments/schemas.py and assumptions.py.
export const DEFAULT_COSTS = {
    currency_label: "USD (illustrative)",
    reviewer_cost_per_minute: 0.85,
    ai_cost_per_invocation: 0.04,
    infrastructure_cost_per_run: 20,
    infrastructure_cost_per_case: 0.02,
    exception_handling_cost: 12,
    manual_escalation_cost: 6,
    oversight_sample_rate: 0.1,
    oversight_minutes_per_sample: 6,
    false_approval_cost: 750,
    false_rejection_cost: 60,
    notes: "",
};
export const DEFAULT_THRESHOLDS = {
    min_improvement: 0.05,
    max_accuracy_drop: 0.005,
    max_false_approval_rate: 0.05,
    max_false_rejection_rate: 0.05,
    max_error_rate: 0.05,
    max_policy_violations: 0,
    regression_tolerance: 0.01,
};
