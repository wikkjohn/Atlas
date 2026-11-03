/** IT operations (Phase 59): the application catalogue, incidents and change requests. */

export interface Application {
  id: string;
  application_number: string;
  name: string;
  description: string;
  department: string;
  tier: 1 | 2 | 3;
  status: "active" | "retired";
  open_incidents: number;
  owner: string | null;
  technology: string;
  hosting: "on_premise" | "private_cloud" | "public_cloud" | "saas";
  vendor: string | null;
  generated_from: string | null;
}

/** The registry (Phase 63): one application's links and what stops if it stops. */
export interface DependencyLink {
  id: string;
  kind: "data" | "api" | "batch" | "auth";
  application_number: string;
  name: string;
  tier: number;
  application_id: string;
}

export interface Impact {
  affected: number;
  direct: number;
  depth: number;
  by_tier: Record<string, number>;
  departments: number;
  top_departments: { department: string; applications: number }[];
  sample: { application_number: string; name: string; tier: number; depth: number; department: string }[];
}

export interface ApplicationDetail {
  application: Application;
  dependencies: DependencyLink[];
  dependents: DependencyLink[];
  impact: Impact;
}

export interface EstateSummary {
  applications: number;
  dependencies: number;
  unconnected: number;
  generated: number;
  by_tier: Record<string, number>;
  by_technology: Record<string, number>;
  by_hosting: Record<string, number>;
}

export interface Incident {
  id: string;
  incident_number: string;
  application_number: string;
  application: string;
  tier: number;
  title: string;
  impact: "high" | "medium" | "low";
  urgency: "high" | "medium" | "low";
  priority: 1 | 2 | 3 | 4;
  status: "open" | "acknowledged" | "resolved" | "closed";
  respond_by: string;
  resolve_by: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  response_breached: boolean;
  resolution_breached: boolean;
  resolution: string | null;
  review: string | null;
  change_number: string | null;
  created_at: string;
}

export interface ChangeRequest {
  id: string;
  change_number: string;
  application_number: string;
  application: string;
  tier: number;
  title: string;
  kind: "standard" | "normal" | "emergency";
  risk: "low" | "medium" | "high";
  needs_cab: boolean;
  planned_start: string;
  planned_end: string;
  incident_number: string | null;
  status: "requested" | "approved" | "rejected" | "implemented" | "failed";
  created_at: string;
}

export interface ItopsSummary {
  applications: number;
  incidents_open: number;
  p1_open: number;
  incidents_breached: number;
  incidents_to_close: number;
  changes_to_approve: number;
  changes_scheduled: number;
  changes_failed_30d: number;
  frozen_now: boolean;
}

/** The simulated application (Phase 64): how it answers calls, and whether it is up. */
export interface AppState {
  status: "up" | "degraded" | "down";
  cause: string | null;
  path: string[];
}

export interface AppContract {
  application_number: string;
  median_ms: { read: number; write: number };
  p95_ms: { read: number; write: number };
  error_rate: number;
  timeout_ms: number;
  sync_dependencies: number;
  operations: string[];
  state: AppState;
  blast_radius: number;
}

export interface CallSample {
  application_number: string;
  operation: string;
  calls: number;
  seed: number;
  ok: number;
  failed: number;
  errors: Record<string, number>;
  p50_ms: number;
  p95_ms: number;
  max_ms: number;
  state: AppState;
}

export interface Outage {
  id: string;
  outage_number: string;
  application_number: string;
  application: string;
  tier: number;
  kind: "down" | "degraded";
  reason: string;
  starts_at: string;
  ends_at: string | null;
  status: "scheduled" | "in_force" | "ended";
  incident_number: string | null;
  failing: number;
}
