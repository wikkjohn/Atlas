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
