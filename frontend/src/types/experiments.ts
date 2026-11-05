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
  // Omitted: the scenario's thresholds apply (Phase 80).
  thresholds?: SuccessThresholds;
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
  configuration: { costs: CostAssumptions; thresholds: SuccessThresholds; thresholds_source?: ThresholdsSource };
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

// --- Repeated-seed series (Phase 77) ---------------------------------------------------------

export type SeriesFinding = "improved" | "worse" | "no_significant_difference" | "too_few_seeds" | "informational";

export interface SeriesMetric {
  metric: string;
  label: string;
  unit: string;
  better: "lower" | "higher" | "none";
  n: number;
  baseline_mean: number | null;
  candidate_mean: number | null;
  mean_delta: number | null;
  ci_low: number | null;
  ci_high: number | null;
  relative_change: number | null;
  relative_ci_low: number | null;
  relative_ci_high: number | null;
  p_value: number | null;
  p_adjusted: number | null;
  significant: boolean;
  finding: SeriesFinding;
  per_seed: { seed: number; baseline: number | null; candidate: number | null; delta: number | null }[];
}

export interface SeriesStatistics {
  method: string;
  confidence: number;
  replicates: number;
  seeds: number[];
  replicate_verdicts: { successful: number; not_successful: number };
  metrics: SeriesMetric[];
  significantly_worse: string[];
  verdict: "successful" | "not_successful";
  conclusion: string;
}

export interface SeriesSummary {
  id: string;
  series_number: number;
  name: string;
  scenario_id: string;
  scenario_version: number;
  candidate_mode: "ai_assisted" | "ai_automated";
  tool_id: string | null;
  tool_version: string | null;
  seeds: number[];
  confidence: number;
  status: ExperimentStatus;
  failure_reason: string | null;
  verdict: "successful" | "not_successful" | null;
  replicates_completed: number;
  created_by_username: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface SeriesDetail extends SeriesSummary {
  configuration: Record<string, unknown>;
  statistics: SeriesStatistics | null;
  experiments: ExperimentSummary[];
}

export interface SeriesCreate {
  name: string;
  scenario_id: string;
  tool_id: string;
  tool_version: string | null;
  candidate_mode: "ai_assisted" | "ai_automated";
  profile: "custom";
  applications: number;
  employees: number;
  seed: number;
  replicates: number;
  confidence: number;
  // Phase 82: calibrated reviewers (default) and per-seed draws of their parameters.
  calibrated?: boolean;
  calibration_draws?: boolean;
}

// --- Portfolios (Phase 78) -------------------------------------------------------------------

export interface PortfolioMetric {
  metric: string;
  label: string;
  better: "lower" | "higher";
  workflows: number;
  cells: number;
  country_dependent_workflows: number;
  mean_relative_change: number | null;
  ci_low: number | null;
  ci_high: number | null;
  median_relative_change: number | null;
  p_value: number | null;
  p_adjusted: number | null;
  significant: boolean;
  finding: "improved" | "worse" | "no_significant_difference" | "too_few_cells";
  cell_findings: { improved: number; worse: number; no_significant_difference: number };
  by_department: { department: string; cells: number; mean_relative_change: number | null }[];
  by_country: { country: string; cells: number; mean_relative_change: number | null }[];
}

export interface PortfolioCell {
  scenario_id: string;
  workflow_id: string;
  department: string | null;
  country: string | null;
  tool_id: string;
  series_number: number;
  verdict: "successful" | "not_successful" | null;
  headline: Record<string, number | null>;
}

export interface PortfolioStatistics {
  method: string;
  confidence: number;
  cells: number;
  workflows: number;
  departments: string[];
  countries: string[];
  tools: string[];
  cell_verdicts: { successful: number; not_successful: number };
  cells_with_a_worse_metric: string[];
  metrics: PortfolioMetric[];
  cell_summaries: PortfolioCell[];
  verdict: "successful" | "not_successful";
  conclusion: string;
}

export interface PortfolioSummary {
  id: string;
  portfolio_number: number;
  name: string;
  family: string;
  candidate_mode: "ai_assisted" | "ai_automated";
  countries: string[];
  seeds: number[];
  applications: number;
  employees: number;
  confidence: number;
  status: ExperimentStatus;
  failure_reason: string | null;
  verdict: "successful" | "not_successful" | null;
  cells: number;
  cells_completed: number;
  created_by_username: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface PortfolioDetail extends PortfolioSummary {
  configuration: { plan?: { cells: unknown[]; skipped: { scenario_id: string; reason: string }[] } } & Record<string, unknown>;
  statistics: PortfolioStatistics | null;
  series: SeriesSummary[];
}

export interface PortfolioCreate {
  name: string;
  family: string;
  candidate_mode: "ai_assisted" | "ai_automated";
  countries: string[];
  applications: number;
  employees: number;
  seed: number;
  replicates: number;
  scenario_ids?: string[];
}

// --- Scenario thresholds (Phase 80) -----------------------------------------------------------

export type RiskTier = "critical" | "high" | "medium" | "low";
export const RISK_TIERS: RiskTier[] = ["critical", "high", "medium", "low"];

export interface ThresholdsSource {
  source: "scenario" | "tier_default" | "request" | "scenario_per_cell";
  scenario_id?: string;
  risk_tier?: RiskTier;
  version?: number;
  record_id?: string | null;
}

export interface ThresholdVersion {
  id: string;
  scenario_id: string;
  version: number;
  risk_tier: RiskTier;
  thresholds: SuccessThresholds;
  rationale: string;
  status: "proposed" | "active" | "superseded" | "rejected";
  proposed_by_username: string | null;
  proposed_at: string;
  decided_by_username: string | null;
  decided_at: string | null;
  decision_note: string | null;
}

export interface ScenarioThresholdRow {
  scenario_id: string;
  name: string;
  workflow_id: string;
  risk_tier: RiskTier;
  default_tier: RiskTier;
  default_rationale: string;
  source: "scenario" | "tier_default";
  version: number;
  thresholds: SuccessThresholds;
  rationale: string;
  pending: ThresholdVersion | null;
}

export interface ThresholdOverview {
  tiers: Record<RiskTier, SuccessThresholds & { description: string }>;
  scenarios: ScenarioThresholdRow[];
}

export interface ThresholdProposal {
  scenario_id: string;
  risk_tier: RiskTier;
  thresholds?: SuccessThresholds;
  rationale: string;
}

export interface ExperimentReassessment {
  experiment_id: string;
  scenario_id: string;
  thresholds_source: ThresholdsSource;
  thresholds: SuccessThresholds;
  stored_thresholds: SuccessThresholds;
  stored_verdict: Verdict;
  verdict: Verdict;
  changed: boolean;
  failed_criteria: string[];
}

export interface PortfolioReassessment {
  portfolio_id: string;
  stored_cell_verdicts: { successful: number; not_successful: number } | null;
  stored_verdict: Verdict | null;
  cell_verdicts: { successful: number; not_successful: number };
  verdict: Verdict;
  by_tier: Partial<Record<RiskTier, { cells: number; successful: number; before: number }>>;
  cells: {
    scenario_id: string;
    country: string | null;
    risk_tier: RiskTier;
    stored_verdict: Verdict | null;
    verdict: Verdict;
    replicates_successful: number;
    replicates: number;
    failed_criteria: string[];
  }[];
  method: string;
}

// --- Tool comparison (Phase 81) ---------------------------------------------------------------

export type PairOutcome = "a_preferred" | "b_preferred" | "trade_off" | "no_difference" | "identical" | "too_few_matched";

export interface PairMetric {
  metric: string;
  label: string;
  unit: string;
  better: "lower" | "higher";
  n: number;
  a_mean: number | null;
  b_mean: number | null;
  mean_difference: number | null;
  relative_difference: number | null;
  ci_low: number | null;
  ci_high: number | null;
  p_value: number | null;
  p_adjusted: number | null;
  identical: boolean;
  finding: "a_better" | "b_better" | "no_significant_difference" | "too_few_matched";
}

export interface ToolPair {
  a: string;
  b: string;
  matched_workloads: number;
  seeds: number[];
  outcome: PairOutcome;
  a_better_on: string[];
  b_better_on: string[];
  metrics: PairMetric[];
}

export interface RankedTool {
  tool: string;
  tool_id: string;
  tool_version: string;
  rank: number;
  experiments: number;
  successful: number;
  successful_stored: number;
  preferred_in: number;
  not_preferred_in: number;
  mean_relative_change: Record<string, number | null>;
}

export interface Benchmark {
  scenario_id: string;
  scenario_version: number;
  candidate_mode: "ai_assisted" | "ai_automated";
  cost_assumptions: string;
  risk_tier: RiskTier;
  tools: RankedTool[];
  pairs: ToolPair[];
}

export interface ScoreboardRow {
  tool: string;
  tool_id: string;
  tool_version: string;
  benchmarks: number;
  ranked_first: number;
  experiments: number;
  successful: number;
  preferred: number;
  not_preferred: number;
  trade_off: number;
  no_difference: number;
  identical: number;
  too_few_matched: number;
}

export interface ToolComparison {
  benchmarks: Benchmark[];
  scoreboard: ScoreboardRow[];
  confidence: number;
  method: string;
}

export interface ToolComparisonStart {
  name: string;
  scenario_id: string;
  tools: { tool_id: string; tool_version: string | null }[];
  candidate_mode: "ai_assisted" | "ai_automated";
  applications: number;
  employees: number;
  seed: number;
  replicates: number;
}

// --- Reviewer calibration (Phase 82) -----------------------------------------------------------

export interface Estimate {
  estimate: number | null;
  low: number | null;
  high: number | null;
  n?: number;
  successes?: number;
}

export interface CalibrationFit {
  confidence: number;
  observations: number;
  unassisted: number;
  assisted: number;
  reviewer: { mean_minutes: Estimate; sigma: Estimate; accuracy: Estimate; accuracy_should_reject: Estimate | null };
  ai_assistance: { review_time_factor: Estimate; accuracy_when_ai_correct: Estimate; accuracy_when_ai_wrong: Estimate | null } | null;
  notes: string[];
}

export interface ReviewerCalibration {
  id: string;
  calibration_number: number;
  scenario_id: string;
  step_id: string;
  source: string;
  observation_count: number;
  data_digest: string;
  status: "active" | "superseded";
  fitted: CalibrationFit;
  assumption: {
    reviewer?: { mean_minutes: number; sigma: number; accuracy: number; accuracy_should_reject: number | null };
    ai_assistance?: { review_time_factor: number; accuracy_when_ai_correct: number; accuracy_when_ai_wrong: number } | null;
  };
  created_by_username: string | null;
  created_at: string;
}

export interface ReviewObservation {
  minutes: number;
  truth: "approve" | "reject";
  decision: "approve" | "reject";
  ai_recommendation: "approve" | "reject" | null;
}
