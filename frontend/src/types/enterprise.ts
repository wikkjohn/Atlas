// Types mirror the Pydantic schemas of the Phase 2 modules (backend/app/modules/*/schemas.py).

export type Permission =
  | "countries:read"
  | "countries:manage"
  | "organizations:read"
  | "organizations:manage"
  | "employees:read"
  | "employees:manage"
  | "employees:read_compensation"
  | "users:read"
  | "users:manage"
  | "audit:read"
  | "customers:read"
  | "customers:manage"
  | "customers:review"
  | "accounts:read"
  | "accounts:request"
  | "accounts:approve"
  | "accounts:transact"
  | "accounts:manage"
  | "ledger:read"
  | "ledger:post"
  | "workflows:read"
  | "workflows:start"
  | "workflows:manage"
  | "simulations:read"
  | "simulations:run"
  | "ai_tools:read"
  | "ai_tools:manage"
  | "ai_tools:invoke"
  | "accounts:approve_low_risk";

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface CurrentUser {
  id: string;
  username: string;
  email: string;
  display_name: string;
  role: string;
  role_name: string;
  employee_id: string | null;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  permissions: Permission[];
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: CurrentUser;
}

export type Region = "americas" | "europe" | "middle_east_africa" | "asia_pacific";
export type CountryStatus = "active" | "planned" | "suspended";

export interface Country {
  id: string;
  iso_country_code: string;
  country_name: string;
  region: Region;
  default_currency: string;
  default_timezone: string;
  supported_languages: string[];
  operational_status: CountryStatus;
  created_at: string;
  updated_at: string;
}

export type OrganizationType =
  | "global_bank"
  | "regional_headquarters"
  | "country_subsidiary"
  | "business_division"
  | "department"
  | "team";

export interface Organization {
  id: string;
  name: string;
  organization_type: OrganizationType;
  parent_organization_id: string | null;
  country_id: string | null;
  country_code: string | null;
  country_name: string | null;
  currency: string | null;
  region: Region | null;
  status: "active" | "inactive";
  child_count: number;
  employee_count: number;
  created_at: string;
  updated_at: string;
}

export interface EmployeeRef {
  id: string;
  employee_number: string;
  full_name: string;
  job_title: string;
}

export type EmploymentStatus = "active" | "on_leave" | "terminated";

export interface Employee {
  id: string;
  employee_number: string;
  first_name: string;
  last_name: string;
  full_name: string;
  email: string;
  organization_id: string;
  organization_name: string;
  department_id: string;
  department_name: string;
  manager: EmployeeRef | null;
  job_title: string;
  role: string;
  country_id: string;
  country_code: string;
  employment_status: EmploymentStatus;
  annual_compensation: number | null;
  compensation_currency: string | null;
  created_at: string;
  updated_at: string;
}

export interface AuditEvent {
  id: string;
  actor_id: string | null;
  actor_username: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  timestamp: string;
  correlation_id: string | null;
  metadata: Record<string, unknown>;
}

export interface Role {
  id: string;
  code: string;
  name: string;
  description: string;
  permissions: Permission[];
}
