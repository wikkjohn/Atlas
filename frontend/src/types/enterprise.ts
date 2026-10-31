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
  | "fx:manage"
  | "retail:manage"
  | "cards:manage"
  | "mortgages:manage"
  | "trade:manage"
  | "ledger:post"
  | "workflows:read"
  | "workflows:start"
  | "workflows:manage"
  | "workflows:define"
  | "simulations:read"
  | "simulations:run"
  | "simulations:manage"
  | "ai_tools:read"
  | "ai_tools:manage"
  | "ai_tools:invoke"
  | "accounts:approve_low_risk"
  | "experiments:read"
  | "experiments:run"
  | "analytics:read"
  | "payments:read"
  | "payments:review"
  | "payments:approve"
  | "payments:release_low_risk"
  | "loans:read"
  | "loans:approve"
  | "loans:approve_large"
  | "loans:approve_low_risk"
  | "loans:repay"
  | "loans:service"
  | "jobs:read"
  | "jobs:manage"
  | "observability:read";

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

/** A user as listed by GET /api/v1/users. */
export interface UserAccount {
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
  is_service_account: boolean;
}

export interface UserCreate {
  username: string;
  email: string;
  display_name: string;
  password: string;
  role: string;
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
  // Reference data (Phase 23).
  iso_alpha3?: string | null;
  calling_code?: string | null;
  weekend_days?: number[];
  easter?: "western" | "orthodox";
  holiday_observance?: string;
  regulator?: { name: string; abbreviation: string } | null;
  identity_documents?: IdentityDocument[];
  address_format?: AddressFormat | null;
  reference_notes?: string[];
  reference_version?: string | null;
  created_at: string;
  updated_at: string;
}

export interface IdentityDocument {
  type: "national_id" | "passport";
  name: string;
  mask: string;
  example: string;
}

export interface AddressFormat {
  style: string;
  lines: string[];
  postal_code_masks: string[];
  postal_code_example: string | null;
  requires_region: boolean;
}

export interface Currency {
  code: string;
  name: string;
  minor_units: number;
}

export interface CountryCalendar {
  iso_country_code: string;
  year: number;
  weekend_days: number[];
  holidays: { date: string; name: string; observed: string }[];
  business_days: number;
  notes: string[];
}

export interface ValueCheck {
  kind: string;
  value: string;
  valid: boolean;
  masks: string[];
}

export interface CountrySample {
  national_id: string | null;
  passport: string;
  postal_code: string | null;
  address_lines: string[];
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
  /** The blueprint a generated organization came from (Phase 27); null when built by hand. */
  generated_from: string | null;
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

// --- Country rules (Phase 25) ----------------------------------------------------------------

export interface CountryRules {
  kyc: { min_age: number; identity_documents: ("passport" | "national_id")[]; proof_of_address: boolean };
  screening: { lists: string[] };
  payments: { cutoff: string; high_value_major: number; max_payment_major: number };
}

export interface RuleVersion {
  id: string;
  version: number;
  effective_from: string;
  rules: CountryRules;
  note: string;
  created_by_username: string | null;
  created_at: string;
}

export interface CountryRulesView {
  iso_country_code: string;
  on: string;
  current: RuleVersion | null;
  effective: CountryRules;
  versions: RuleVersion[];
}

export interface SanctionsList {
  list_id: string;
  description: string;
  entries: number;
}

export interface SubsidiaryCoverage {
  region: Region;
  countries: number;
  subsidiaries: number;
  generated: number;
  without_subsidiary: string[];
}

/** The subsidiary blueprint and coverage by region (Phase 27). */
export interface SubsidiaryBlueprint {
  version: number;
  generated_from: string;
  regional_headquarters: Record<Region, string>;
  structure: Record<string, Record<string, string[]>>;
  units_per_subsidiary: number;
  staff_per_subsidiary: number;
  usd_salary_band: [number, number];
  coverage: SubsidiaryCoverage[];
}
