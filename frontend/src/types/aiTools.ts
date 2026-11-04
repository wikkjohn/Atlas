// Mirrors backend/app/modules/ai_tools/schemas.py.

export interface AiTool {
  id: string;
  tool_id: string;
  tool_name: string;
  tool_version: string;
  provider: string;
  description: string;
  adapter: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  allowed_actions: string[];
  permissions: string[];
  compatible_workflows: string[];
  configuration: Record<string, unknown>;
  status: "active" | "disabled";
  created_by_username: string | null;
  created_at: string;
  invocations: number;
  failures: number;
}

export interface AiAdapter {
  key: string;
  name: string;
  provider: string;
  description: string;
  supported_actions: string[];
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  configuration_schema: Record<string, unknown>;
}

export interface AiAction {
  action: string;
  grantable: boolean;
  description: string;
}

export interface ToolCreate {
  tool_id: string;
  tool_name: string;
  tool_version: string;
  provider: string;
  description: string;
  adapter: string;
  allowed_actions: string[];
  compatible_workflows: string[];
  permissions: string[];
  configuration: Record<string, unknown>;
}

export type InvocationStatus =
  | "succeeded"
  | "failed"
  | "timeout"
  | "invalid_input"
  | "invalid_output"
  | "blocked";

export interface Invocation {
  id: string;
  tool_record_id: string;
  tool_id: string;
  tool_version: string;
  action: string;
  status: InvocationStatus;
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  duration_ms: number;
  usage: Record<string, unknown>;
  invoked_by: string | null;
  execution_id: string | null;
  simulation_run_id: string | null;
  transcript: Record<string, unknown> | null;
  record_hash: string | null;
  occurred_at: string;
  created_at: string;
}

// --- Guardrails (Phase 79): mirrors backend/app/modules/ai_tools/guardrails.py ---------------

export interface ToolRun {
  id: string;
  run_number: number;
  mode: string;
  created_at: string;
  calls: number;
}

export interface BiasGroup {
  group: string;
  n: number;
  approve_rate: number | null;
  reject_rate: number | null;
  escalate_rate: number | null;
  should_approve: number;
  false_rejections: number;
  false_rejection_rate: number | null;
  should_reject: number;
  false_approval_rate: number | null;
}

export type BiasFinding = "disparity" | "no_disparity" | "insufficient_data";

export interface BiasAttribute {
  attribute: string;
  groups: BiasGroup[];
  excluded_groups: string[];
  approval_ratio: number | null;
  false_rejection_gap: number | null;
  test: "equal_opportunity" | "demographic_parity";
  p_value: number | null;
  p_adjusted: number | null;
  finding: BiasFinding;
  four_fifths_rule: boolean | null;
}

export interface BiasReport {
  tool_id: string;
  tool_version: string;
  run_id: string | null;
  recommendations: number;
  with_ground_truth: number;
  min_group: number;
  attributes: BiasAttribute[];
  flagged: string[];
  status: "clear" | "flagged" | "insufficient_data";
  method: string;
}

export type DriftStatus = "stable" | "moderate" | "significant" | "no_data";

export interface DriftComparison {
  psi: number | null;
  p_value: number | null;
  status: DriftStatus;
}

export interface DriftReport {
  tool_id: string;
  tool_version: string;
  windows: Record<string, string>;
  reference: { calls: number; errors: number };
  current: { calls: number; errors: number };
  recommendations: DriftComparison & {
    shares: Record<string, { reference: number | null; current: number | null }>;
  };
  confidence: { reference_mean: number | null; current_mean: number | null; p_value: number | null };
  error_rate: { reference: number | null; current: number | null; p_value: number | null };
  inputs: (DriftComparison & { attribute: string })[];
  status: DriftStatus;
  method: string;
}

export interface AuditVerification {
  checked: number;
  valid: number;
  unhashed: number;
  mismatched: number;
  mismatched_ids: string[];
  status: "intact" | "altered";
}
