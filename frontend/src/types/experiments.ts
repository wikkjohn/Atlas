// Mirrors backend/app/modules/experiments/schemas.py and assumptions.py.

export interface CostAssumptions {
  currency_label: string;
  reviewer_cost_per_minute: number;
  ai_cost_per_invocation: number;
  infrastructure_cost_per_run: number;
  infrastructure_cost_per_case: number;
  exception_handling_cost: number;
  manual_escalation_cost: number;
  oversight_sample_rate: number;
  oversight_minutes_per_sample: number;
  false_approval_cost: number;
  false_rejection_cost: number;
  notes: string;
}

export interface SuccessThresholds {
  min_improvement: number;
  max_accuracy_drop: number;
  max_false_approval_rate: number;
  max_false_rejection_rate: number;
  max_error_rate: number;
  max_policy_violations: number;
  regression_tolerance: number;
}

export interface ExperimentCreate {
  name: string;
  scenario_id: string;
  tool_id: string;
  tool_version: string | null;
  candidate_mode: "ai_assisted" | "ai_automated";
  profile: "custom";
  applications: number;
  employees: number;
  seed: number;
  costs: CostAssumptions;
  thresholds: SuccessThresholds;
}

export interface RunRef {
  id: string;
  run_number: number;
  mode: string;
  status: "queued" | "running" | "completed" | "failed";
  percent_complete: number;
  failure_reason: string | null;
}

export type ExperimentStatus = "running" | "completed" | "failed";
export type Verdict = "successful" | "not_successful";

export interface ExperimentSummary {
  id: string;
  experiment_number: number;
  name: string;
  scenario_id: string;
  scenario_version: number;
  candidate_mode: "ai_assisted" | "ai_automated";
  tool_id: string | null;
  tool_version: string | null;
  status: ExperimentStatus;
  failure_reason: string | null;
  verdict: Verdict | null;
  created_by_username: string | null;
  created_at: string;
  completed_at: string | null;
  baseline: RunRef;
  candidate: RunRef;
  headline: Record<string, number | null>;
}

export interface Comparison {
  metric: string;
  label: string;
  unit: "hours" | "count" | "currency" | "ratio";
  better: "lower" | "higher" | "none";
  baseline: number | null;
  candidate: number | null;
  delta: number | null;
  relative_change: number | null;
  improved: boolean;
  regression: boolean;
}

export interface Criterion {
  criterion: string;
  label: string;
  passed: boolean;
  detail: string;
}

export interface SideCosts {
  inputs: Record<string, number>;
  lines: Record<string, number>;
  operating_total: number;
  cost_per_completed_case: number | null;
  risk_exposure: Record<string, number>;
  risk_exposure_total: number;
}

export interface Evaluation {
  evaluation_version: string;
  costs: { baseline: SideCosts; candidate: SideCosts };
  comparisons: Comparison[];
  criteria: Criterion[];
  verdict: Verdict;
  conclusion: string;
  limitations: string[];
  evaluation_digest: string;
  computed_at: string;
}

export interface RawMetrics {
  cases: number;
  completed: number;
  manual_reviews: number;
  automated_approvals: number;
  escalations: number;
  exceptions: number;
  false_approvals: number;
  false_rejections: number;
  decisions_checked: number;
  policy_violations: number;
  result_digest: string | null;
  cycle_seconds: { avg: number | null; p50: number | null; p95: number | null };
  ai: { invocations: number; blocked: number; errors: number; by_status: Record<string, number> };
  workload: { seed: number; applications: number; employees: number; software_version: string };
  [key: string]: unknown;
}

export interface Measurement {
  run_id: string;
  role: "baseline" | "candidate";
  metrics: RawMetrics;
  measurement_digest: string;
  captured_at: string;
}

export interface ExperimentDetail extends ExperimentSummary {
  configuration: { costs: CostAssumptions; thresholds: SuccessThresholds };
  configuration_hash: string;
  measurements: Measurement[];
  evaluation: Evaluation | null;
}

export interface ReEvaluation {
  stored_digest: string;
  recomputed_digest: string;
  matches: boolean;
}

export interface BenchmarkRow {
  tool_id: string;
  tool_version: string;
  candidate_mode: "ai_assisted" | "ai_automated";
  experiments: number;
  successful: number;
  latest_experiment_id: string;
  latest_verdict: Verdict | null;
  median_relative_change: Record<string, number | null>;
}

export const DEFAULT_COSTS: CostAssumptions = {
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

export const DEFAULT_THRESHOLDS: SuccessThresholds = {
  min_improvement: 0.05,
  max_accuracy_drop: 0.005,
  max_false_approval_rate: 0.05,
  max_false_rejection_rate: 0.05,
  max_error_rate: 0.05,
  max_policy_violations: 0,
  regression_tolerance: 0.01,
};
