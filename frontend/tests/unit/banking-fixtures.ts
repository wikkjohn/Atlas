import type { Account, AccountRequest, Customer, ReconciliationReport } from "@/types/banking";
import type { CurrentUser } from "@/types/enterprise";

import { adminUser } from "./fixtures";

export const pendingCustomer: Customer = {
  id: "cus-1",
  customer_number: "CUS-0000001",
  customer_type: "individual",
  name: "Mara Lindqvist",
  date_of_birth_or_incorporation: "1988-03-14",
  country_id: "country-us",
  country_code: "US",
  currency: "USD",
  risk_rating: "unrated",
  kyc_status: "pending",
  created_at: "2026-10-27T00:00:00Z",
  updated_at: "2026-10-27T00:00:00Z",
};

export const verifiedCustomer: Customer = {
  ...pendingCustomer,
  id: "cus-2",
  customer_number: "CUS-0000002",
  name: "Kenji Watanabe",
  country_code: "JP",
  currency: "JPY",
  risk_rating: "low",
  kyc_status: "verified",
};

export const account: Account = {
  id: "acc-1",
  account_number: "US000000004257",
  customer_id: "cus-2",
  customer_number: "CUS-0000002",
  customer_name: "Kenji Watanabe",
  account_type: "current",
  currency: "USD",
  status: "open",
  ledger_account_id: "la-1",
  ledger_account_code: "2100-US000000004257",
  balance: 1_234_56,
  opened_at: "2026-10-27T10:00:00Z",
  closed_at: null,
};

export const tellerUser: CurrentUser = {
  ...adminUser,
  id: "user-teller",
  username: "employee",
  role: "banking_employee",
  role_name: "Banking Employee",
  display_name: "Demo Banking Employee",
  permissions: [
    "countries:read",
    "organizations:read",
    "employees:read",
    "customers:read",
    "customers:manage",
    "accounts:read",
    "accounts:request",
    "accounts:transact",
  ],
};

export function request(partial: Partial<AccountRequest>): AccountRequest {
  return {
    id: "req-1",
    customer_id: "cus-2",
    customer_number: "CUS-0000002",
    customer_name: "Kenji Watanabe",
    customer_risk_rating: "low",
    account_type: "current",
    currency: "JPY",
    status: "pending",
    requested_by: "user-teller",
    requested_by_username: "employee",
    decided_by: null,
    decided_by_username: null,
    decided_at: null,
    decision_note: null,
    account_id: null,
    created_at: "2026-10-27T10:00:00Z",
    ...partial,
  };
}

export const cleanReport: ReconciliationReport = {
  ok: true,
  checked_at: "2026-10-27T10:00:00Z",
  entries_checked: 3,
  lines_checked: 6,
  checks: [
    { name: "Every entry balances", passed: true, detail: "3 entries checked; 0 unbalanced.", failures: [] },
    { name: "Trial balance per currency", passed: true, detail: "USD: 900 = 900", failures: [] },
  ],
};
