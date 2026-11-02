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
