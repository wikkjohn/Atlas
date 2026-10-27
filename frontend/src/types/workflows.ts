// Mirrors backend/app/modules/workflows/schemas.py.

export interface WorkflowSummary {
  workflow_id: string;
  name: string;
  version: number;
  versions: number[];
  description: string;
  business_owner: string;
  trigger_type: string;
  step_count: number;
}

export interface StepDefinition {
  id: string;
  type: string;
  name: string;
  handler?: string;
  next?: string;
  transitions?: { to: string; when?: Record<string, unknown> }[];
  branches?: string[];
  join?: string;
  approval?: { permissions: string[]; distinct_from: string[] };
  signal?: string;
  timeout?: { after_seconds: number; action: string; to?: string };
  retry?: { max_attempts: number; backoff_seconds: number };
  on_failure?: string;
}

export interface WorkflowDefinition extends WorkflowSummary {
  start: string;
  input_schema: Record<string, unknown>;
  steps: StepDefinition[];
  transition_rules: Record<string, unknown>[];
  approval_policies: Record<string, unknown>[];
  failure_policies: Record<string, unknown>[];
  timeout_policies: Record<string, unknown>[];
}

export type ExecutionStatus = "running" | "waiting" | "completed" | "failed" | "cancelled";

export interface ExecutionSummary {
  id: string;
  workflow_id: string;
  workflow_version: number;
  status: ExecutionStatus;
  outcome: string | null;
  current_steps: string[];
  business_key: string | null;
  applicant: string | null;
  initiated_by: string;
  initiated_by_username: string | null;
  correlation_id: string | null;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
}

export interface StepRun {
  id: string;
  sequence: number;
  step_id: string;
  step_name: string;
  step_type: string;
  status: "pending" | "waiting" | "completed" | "failed" | "cancelled";
  branch: string | null;
  attempt: number;
  required_permissions: string[];
  actor_id: string | null;
  actor_username: string | null;
  output: Record<string, unknown> | null;
  error: { code?: string; message?: string; details?: unknown } | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  not_before: string | null;
  due_at: string | null;
  escalated_at: string | null;
}

export interface ExecutionDetail extends ExecutionSummary {
  context: Record<string, unknown>;
  error: Record<string, unknown> | null;
  steps: StepRun[];
}

export interface WorkflowEvent {
  id: string;
  event_type: string;
  occurred_at: string;
  step_run_id: string | null;
  actor_id: string | null;
  data: Record<string, unknown>;
}

export interface WorkflowTask {
  run_id: string;
  execution_id: string;
  workflow_id: string;
  step_id: string;
  step_name: string;
  step_type: string;
  opened_at: string | null;
  due_at: string | null;
  overdue: boolean;
  required_permissions: string[];
  can_act: boolean;
  blocked_reason: string | null;
  applicant: string | null;
  risk_rating: string | null;
  flags: string[];
  initiated_by_username: string | null;
}

export interface StepMetric {
  step_id: string;
  step_name: string;
  step_type: string;
  runs: number;
  completed: number;
  failed: number;
  open: number;
  retries: number;
  avg_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  max_ms: number | null;
}

export interface WorkflowMetrics {
  workflow_id: string;
  executions: Record<string, number>;
  outcomes: Record<string, number>;
  avg_execution_ms: number | null;
  bottleneck_step: string | null;
  steps: StepMetric[];
}
