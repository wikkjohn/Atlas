// Mirrors backend/app/simulation/schemas.py.

export type SimulationStatus = "queued" | "running" | "completed" | "failed";
export type ProfileId = "small" | "department" | "large" | "enterprise" | "custom";

export interface Scenario {
  scenario_id: string;
  version: number;
  name: string;
  description: string;
  workload: string;
  workflow_id: string;
  workflow_version: number;
  modes: ExperimentMode[];
  simulated_start: string;
  config: Record<string, unknown>;
}

export type ExperimentMode = "baseline" | "ai_assisted" | "ai_automated";

export const MODE_LABELS: Record<ExperimentMode, string> = {
  baseline: "A — Baseline",
  ai_assisted: "B — AI assisted",
  ai_automated: "C — AI automated tasks",
};

export interface Profile {
  profile_id: Exclude<ProfileId, "custom">;
  name: string;
  applications: number;
  customers: number;
  employees: number;
  status: "verified" | "target";
  runnable: boolean;
  note: string;
  /** Parallel shards the profile needs at least (one process would take hours). */
  min_shards: number;
}

export interface StartSimulation {
  scenario_id: string;
  scenario_version?: number;
  mode?: ExperimentMode;
  tool_id?: string | null;
  tool_version?: string | null;
  profile: ProfileId;
  seed: number;
  applications?: number | null;
  employees?: number | null;
  shards?: number;
}

export interface SimulationProgress {
  cases_total?: number;
  cases_started?: number;
  cases_completed?: number;
  events_processed?: number;
  events_pending?: number;
  simulated_now?: string;
  wall_seconds?: number;
  shards?: { total: number; completed: number };
}

export interface SimulationRunSummary {
  id: string;
  run_number: number;
  scenario_id: string;
  scenario_version: number;
  workflow_id: string;
  workflow_version: number;
  profile: ProfileId;
  seed: number;
  applications: number;
  employees: number;
  status: SimulationStatus;
  failure_reason: string | null;
  software_version: string;
  config_hash: string;
  result_digest: string | null;
  created_by_username: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  wall_ms: number | null;
  progress: SimulationProgress;
  percent_complete: number;
  mode: ExperimentMode;
  tool_id: string | null;
  tool_version: string | null;
  batch_id: string | null;
  /** Parallel slices of the run (1: a single process). */
  shards: number;
  history_state: HistoryState;
}

export interface ShardProgress {
  shard: number;
  status: "queued" | "running" | "completed" | "failed";
  cases_total: number;
  cases_completed: number;
  events_processed: number;
  worker: string | null;
  started_at: string | null;
  completed_at: string | null;
  wall_ms: number | null;
  error: string | null;
}

/** Where a run's workflow history is: in the database, in archive files, or removed. */
export type HistoryState = "present" | "archived" | "purged";

export interface SimulationArchive {
  id: string;
  run_id: string;
  run_number: number;
  kind: "archive" | "purge";
  location: string | null;
  rows: number;
  bytes: number;
  tables: Record<string, number>;
  created_by_username: string | null;
  created_at: string;
}

export interface PartitionUsage {
  table: string;
  realm: "live" | "simulation";
  rows_estimate: number;
  bytes: number;
}

export interface HistoryOverview {
  partitions: PartitionUsage[];
  runs_by_history_state: Record<HistoryState, number>;
  archive_directory: string;
  archive_bytes: number;
  recent_archives: SimulationArchive[];
  retention_schedule_enabled: boolean | null;
}

export interface QueuedJob {
  job_id: string;
  job_number: number;
  kind: string;
  status: string;
}

export interface StartSuite {
  scenario_id: string;
  scenario_version: number;
  profile: "small" | "custom";
  seed: number;
  applications?: number | null;
  employees?: number | null;
  modes: ExperimentMode[];
  tool_id: string;
  tool_version: string;
}

export interface AiResults {
  mode: string;
  invocations: number;
  invocation_statuses: Record<string, number>;
  failed_invocations: number;
  recommendations: Record<string, number>;
  escalations: number;
  recommendation_accuracy: number | null;
  automated_approvals: number;
}

export interface Percentiles {
  avg?: number | null;
  p50?: number | null;
  p95?: number | null;
  max?: number | null;
}

export interface SimulationResults {
  cases: number;
  completed: number;
  unfinished: number;
  outcomes: Record<string, number>;
  by_kind: Record<string, { cases: number; approved: number; rejected: number; other: number }>;
  risk_ratings: Record<string, number>;
  ground_truth: {
    correct: number;
    false_approvals: number;
    false_rejections: number;
    accuracy: number | null;
  };
  manual_reviews: number;
  straight_through_rate: number | null;
  review_labor_hours: number | null;
  overdue_tasks: number;
  cycle_time_hours: Percentiles;
  review_queue_wait_hours: Percentiles;
  staff: Record<string, number>;
  simulated_hours: number | null;
  ai?: AiResults | null;
  execution: {
    events_processed: number;
    workflow_steps_completed: number;
    wall_ms: number;
    cases_per_second: number | null;
  };
}

export interface Reproduction {
  id: string;
  run_number: number;
  result_digest: string | null;
  matches: boolean;
}

export interface SimulationRunDetail extends SimulationRunSummary {
  config: Record<string, unknown> & { scenario?: Record<string, unknown> };
  results: SimulationResults | null;
  simulated_start: string;
  simulated_end: string | null;
  staff_unit_id: string | null;
  reproductions: Reproduction[];
  archive: SimulationArchive | null;
  shard_progress: ShardProgress[];
}

export interface CaseResult {
  case_index: number;
  execution_id: string | null;
  kind: string;
  expected_outcome: string;
  status: string;
  outcome: string | null;
  matches_ground_truth: boolean;
  risk_rating: string | null;
  flags: string[];
  manual_reviews: number;
  review_minutes: number;
  queue_wait_minutes: number;
  overdue_tasks: number;
  arrived_at: string;
  completed_at: string | null;
  cycle_hours: number | null;
  path: string[];
  ai_recommendation: string | null;
  ai_status: string | null;
  automated: boolean;
}
