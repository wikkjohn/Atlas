import type { AuditEvent, Country, Employee, Organization } from "@/types/enterprise";

export const japan: Country = {
  id: "country-jp",
  iso_country_code: "JP",
  country_name: "Japan",
  region: "asia_pacific",
  default_currency: "JPY",
  default_timezone: "Asia/Tokyo",
  supported_languages: ["ja-JP"],
  operational_status: "active",
  created_at: "2026-10-27T00:00:00Z",
  updated_at: "2026-10-27T00:00:00Z",
};

export const germany: Country = {
  ...japan,
  id: "country-de",
  iso_country_code: "DE",
  country_name: "Germany",
  region: "europe",
  default_currency: "EUR",
  default_timezone: "Europe/Berlin",
  supported_languages: ["de-DE", "en"],
};

function org(partial: Partial<Organization> & Pick<Organization, "id" | "name" | "organization_type">): Organization {
  return {
    parent_organization_id: null,
    country_id: null,
    country_code: null,
    country_name: null,
    currency: null,
    region: null,
    status: "active",
    generated_from: null,
    child_count: 0,
    employee_count: 0,
    created_at: "2026-10-27T00:00:00Z",
    updated_at: "2026-10-27T00:00:00Z",
    ...partial,
  };
}

export const bank = org({ id: "org-bank", name: "ATLAS Global Bank", organization_type: "global_bank", child_count: 1 });
export const asiaHq = org({
  id: "org-apac",
  name: "Asia-Pacific HQ",
  organization_type: "regional_headquarters",
  parent_organization_id: "org-bank",
  region: "asia_pacific",
  child_count: 0,
});
export const onboarding = org({
  id: "org-onboarding",
  name: "Customer Onboarding",
  organization_type: "department",
  parent_organization_id: "org-retail",
  country_code: "JP",
  country_name: "Japan",
  currency: "JPY",
  region: "asia_pacific",
  employee_count: 1,
});

export const manager: Employee = {
  id: "emp-1",
  employee_number: "AGB-0000001",
  first_name: "Aiko",
  last_name: "Tanaka",
  full_name: "Aiko Tanaka",
  email: "aiko.tanaka@atlasbank.example",
  organization_id: onboarding.id,
  organization_name: onboarding.name,
  department_id: onboarding.id,
  department_name: onboarding.name,
  manager: null,
  job_title: "Head of Customer Onboarding",
  role: "department_manager",
  country_id: japan.id,
  country_code: "JP",
  employment_status: "active",
  annual_compensation: 18_000_000,
  compensation_currency: "JPY",
  created_at: "2026-10-27T00:00:00Z",
  updated_at: "2026-10-27T00:00:00Z",
};

export const analyst: Employee = {
  ...manager,
  id: "emp-2",
  employee_number: "AGB-0000002",
  first_name: "Ren",
  last_name: "Ito",
  full_name: "Ren Ito",
  email: "ren.ito@atlasbank.example",
  job_title: "KYC Analyst",
  role: "banking_employee",
  manager: { id: "emp-1", employee_number: "AGB-0000001", full_name: "Aiko Tanaka", job_title: "Head of Customer Onboarding" },
  annual_compensation: 6_500_000,
};

export const loginEvent: AuditEvent = {
  id: "audit-1",
  actor_id: "user-admin",
  actor_username: "admin",
  action: "employee.updated",
  entity_type: "employee",
  entity_id: "emp-2",
  timestamp: "2026-10-27T10:00:00Z",
  correlation_id: "trace-123",
  metadata: { changes: { annual_compensation: { changed: true } } },
};
