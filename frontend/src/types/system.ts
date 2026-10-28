// Types mirror the Pydantic response models in backend/app/api/system.py.

export type ComponentStatus = "ok" | "unavailable" | "disabled";

export interface ComponentHealth {
  status: ComponentStatus;
  critical: boolean;
  latency_ms: number | null;
  error: string | null;
}

export interface HealthResponse {
  status: "ok" | "degraded" | "unavailable";
  timestamp: string;
  components: Record<string, ComponentHealth>;
}

export interface PlatformModule {
  key: string;
  name: string;
  phase: number;
  status: "available" | "planned";
  description: string;
}

export interface SystemInfo {
  name: string;
  version: string;
  environment: string;
  build_sha: string | null;
  api_versions: string[];
  python_version: string;
  started_at: string;
  uptime_seconds: number;
  data_policy: string;
  modules: PlatformModule[];
}

export interface MigrationStatus {
  current_revisions: string[];
  head_revisions: string[];
  up_to_date: boolean;
}

export interface DatabaseStatus {
  connected: boolean;
  latency_ms: number | null;
  error: string | null;
  server_version: string | null;
  database_name: string | null;
  table_count: number | null;
  migrations: MigrationStatus | null;
  initialized_at: string | null;
}

export interface SystemStatus {
  status: "operational" | "needs_migration" | "unavailable";
  timestamp: string;
  uptime_seconds: number;
  database: DatabaseStatus;
  redis: ComponentHealth;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: unknown;
    correlation_id: string | null;
  };
}
