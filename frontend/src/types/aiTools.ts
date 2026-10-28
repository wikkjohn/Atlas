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
  occurred_at: string;
  created_at: string;
}
