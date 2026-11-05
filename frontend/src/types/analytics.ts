// Mirrors backend/app/modules/analytics/schemas.py.

export interface DashboardMetric {
  key: string;
  label: string;
  value: number | null;
  unit: "count" | "hours" | "ms" | "currency";
  detail: string;
  synthetic: boolean;
  estimate: boolean;
}

export interface AnalyticsOverview {
  generated_at: string;
  metrics: DashboardMetric[];
  workflow_outcomes: Record<string, number>;
  open_tasks: number;
  simulation_runs_by_status: Record<string, number>;
  cost_assumptions: { currency_label: string } & Record<string, unknown>;
  recent_runs: { id: string; run_number: number; mode: string; status: string; applications: number; created_at: string }[];
  recent_experiments: {
    id: string;
    experiment_number: number;
    name: string;
    status: string;
    verdict: "successful" | "not_successful" | null;
    tool_id: string | null;
    created_at: string;
  }[];
}

/** Phase 88: one place in the drill-down (enterprise → country → department → workflow). */
export type DrilldownLevel = "enterprise" | "country" | "department" | "workflow";

export interface DrilldownFigures {
  executions: number;
  completed: number;
  failed: number;
  active: number;
  failure_rate: number | null;
  avg_duration_s: number | null;
  last_started_at: string | null;
  open_tasks: number;
}

export interface DrilldownRow extends DrilldownFigures {
  key: string;
  label: string;
}

export interface DrilldownStep {
  step_id: string;
  step_type: string;
  runs: number;
  failed: number;
  waiting: number;
  avg_ms: number | null;
  p95_ms: number | null;
}

export interface Drilldown {
  level: DrilldownLevel;
  path: { level: DrilldownLevel; key: string; label: string }[];
  realm: "all" | "live" | "simulation";
  days: number | null;
  generated_at: string;
  scope: { countries: string[] | null; departments: string[] | null } | null;
  summary: DrilldownFigures;
  breakdown_by: "country" | "department" | "workflow" | null;
  breakdown: DrilldownRow[];
  truncated?: boolean;
  steps: DrilldownStep[] | null;
  outcomes: Record<string, number> | null;
  attribution: Record<string, string>;
}

export interface DrilldownQuery {
  country?: string;
  department?: string;
  workflow_id?: string;
  realm: "all" | "live" | "simulation";
  days?: number;
}
