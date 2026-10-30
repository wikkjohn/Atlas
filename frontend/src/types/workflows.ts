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
  source: "code" | "stored";
  status: "active" | "retired";
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
  params?: Record<string, unknown>;
}

export interface WorkflowDefinition extends WorkflowSummary {
  start: string;
  input_schema: JsonSchema;
  presentation?: { subject_path: string; risk_path?: string; flags_path?: string } | null;
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
  subject: string | null;
  initiated_by: string;
  initiated_by_username: string | null;
  correlation_id: string | null;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  simulation_run_id?: string | null;
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
  subject: string | null;
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

// --- Stored definitions (Phase 17) ----------------------------------------------------------

/** The subset of JSON Schema the generic start form understands. */
export interface JsonSchemaProperty {
  type?: "string" | "integer" | "number" | "boolean";
  enum?: (string | number)[];
  description?: string;
  pattern?: string;
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  format?: string;
}

export interface JsonSchema {
  type?: string;
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
  [key: string]: unknown;
}

export interface DefinitionProblem {
  location: string;
  code: string;
  message: string;
}

export interface ValidationReport {
  valid: boolean;
  workflow_id: string | null;
  version: number | null;
  content_hash: string | null;
  existing: "new" | "identical" | null;
  errors: DefinitionProblem[];
  warnings: DefinitionProblem[];
}

export interface StoredDefinition {
  id: string;
  workflow_id: string;
  version: number;
  name: string;
  status: "active" | "retired";
  content_hash: string;
  step_count: number;
  imported_by: string | null;
  imported_by_username: string | null;
  imported_at: string;
  status_changed_at: string | null;
  executions: number;
}

export interface ImportResult {
  created: boolean;
  definition: StoredDefinition;
  warnings: DefinitionProblem[];
}

export interface LibraryHandler {
  name: string;
  step_type: string;
  summary: string;
  output: string;
  params_schema: Record<string, unknown>;
}
