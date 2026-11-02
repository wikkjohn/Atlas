/** Human resources (Phase 55). Salaries are yearly, in minor units of the department's currency. */

export interface Department {
  id: string;
  name: string;
  headcount: number;
  country: string | null;
  currency: string | null;
}

export interface Capacity {
  department_id: string;
  department: string;
  on: string;
  headcount: number;
  on_leave: number;
  shifts: number;
  rostered: number;
  available: number;
  available_by_role: Record<string, number>;
}

export interface Requisition {
  id: string;
  requisition_number: string;
  department: string;
  job_title: string;
  role: string;
  openings: number;
  filled: number;
  salary_min: number;
  salary_max: number;
  currency: string;
  reason: string;
  status: "open" | "approved" | "filled" | "cancelled";
  created_at: string;
}

export interface Candidate {
  id: string;
  candidate_number: string;
  requisition_number: string;
  name: string;
  status: "applied" | "offered" | "hired" | "declined" | "rejected";
  offered_salary: number | null;
  start_date: string | null;
  employee_number: string | null;
}

export interface LeaveRequest {
  id: string;
  leave_number: string;
  employee_number: string;
  employee_name: string;
  kind: "annual" | "sick" | "unpaid";
  start_date: string;
  end_date: string;
  days: number;
  status: "requested" | "approved" | "rejected" | "cancelled";
  note: string | null;
  created_at: string;
}

export interface Shift {
  id: string;
  shift_number: string;
  department: string;
  on: string;
  start_hour: number;
  hours: number;
  required: number;
  rostered: string[];
}

export interface OnboardingTask {
  id: string;
  employee_number: string;
  employee_name: string;
  code: string;
  title: string;
  due: string;
  completed_at: string | null;
}

export interface HrSummary {
  requisitions_to_approve: number;
  requisitions_recruiting: number;
  offers_out: number;
  leave_to_decide: number;
  on_leave_today: number;
  onboarding_overdue: number;
  shifts_today: number;
}
