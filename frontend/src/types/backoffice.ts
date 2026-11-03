/** Thin departments (Phase 61): legal, audit, marketing, facilities and the rest. Amounts are US cents. */

export interface DepartmentProcess {
  code: string;
  name: string;
  description: string;
  approval: boolean;
  sla_hours: number;
  amount_label: string | null;
  budget_usd: number | null;
  major_above_usd: number | null;
  workflow_id: string;
}

export interface DepartmentCounts {
  submitted: number;
  approved: number;
  rejected: number;
  completed: number;
  overdue: number;
  breached: number;
}

export interface ThinDepartment {
  code: string;
  name: string;
  description: string;
  processes: DepartmentProcess[];
  counts: DepartmentCounts;
}

export interface DepartmentRequest {
  id: string;
  request_number: string;
  department: string;
  process: string;
  process_name: string;
  title: string;
  details: string;
  amount: number | null;
  over_budget: boolean;
  needs_executive: boolean;
  status: "submitted" | "approved" | "rejected" | "completed";
  due_at: string;
  breached: boolean;
  note: string | null;
  created_at: string;
}
