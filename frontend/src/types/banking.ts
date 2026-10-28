// Types mirror the Pydantic schemas of the Phase 3 modules (customers, accounts, ledger).

export type CustomerType = "individual" | "business";
export type KycStatus = "not_started" | "pending" | "verified" | "rejected";
export type RiskRating = "unrated" | "low" | "medium" | "high";

export interface Customer {
  id: string;
  customer_number: string;
  customer_type: CustomerType;
  name: string;
  date_of_birth_or_incorporation: string;
  country_id: string;
  country_code: string;
  currency: string;
  risk_rating: RiskRating;
  kyc_status: KycStatus;
  created_at: string;
  updated_at: string;
}

export type AccountType = "current" | "savings" | "business_current";
export type AccountStatus = "open" | "frozen" | "closed";
export type RequestStatus = "pending" | "approved" | "rejected";

export interface AccountRequest {
  id: string;
  customer_id: string;
  customer_number: string;
  customer_name: string;
  customer_risk_rating: RiskRating;
  account_type: AccountType;
  currency: string;
  status: RequestStatus;
  requested_by: string;
  requested_by_username: string | null;
  decided_by: string | null;
  decided_by_username: string | null;
  decided_at: string | null;
  decision_note: string | null;
  account_id: string | null;
  created_at: string;
}

export interface Account {
  id: string;
  account_number: string;
  customer_id: string;
  customer_number: string;
  customer_name: string;
  account_type: AccountType;
  currency: string;
  status: AccountStatus;
  ledger_account_id: string;
  ledger_account_code: string;
  balance: number;
  opened_at: string;
  closed_at: string | null;
}

export interface Eligibility {
  eligible: boolean;
  reasons: string[];
}

export interface MovementResult {
  account: Account;
  journal_entry_id: string;
  entry_number: string;
  replayed: boolean;
}

export interface StatementLine {
  entry_id: string;
  entry_number: string;
  posted_at: string;
  description: string;
  source: string;
  direction: "debit" | "credit";
  amount: number;
  memo: string | null;
}

export interface LedgerAccount {
  id: string;
  code: string;
  name: string;
  account_type: "asset" | "liability" | "equity" | "income" | "expense";
  currency: string;
  normal_balance: "debit" | "credit";
  balance: number;
  created_at: string;
}

export interface JournalLine {
  line_number: number;
  ledger_account_id: string;
  ledger_account_code: string;
  ledger_account_name: string;
  direction: "debit" | "credit";
  amount: number;
  memo: string | null;
}

export interface JournalEntry {
  id: string;
  entry_number: string;
  currency: string;
  description: string;
  source: string;
  status: "posted" | "reversed";
  effective_date: string;
  posted_at: string;
  posted_by: string | null;
  correlation_id: string | null;
  reversal_of_id: string | null;
  reversed_by_id: string | null;
  total: number;
  lines: JournalLine[];
}

export interface ReconciliationReport {
  ok: boolean;
  checked_at: string;
  entries_checked: number;
  lines_checked: number;
  checks: { name: string; passed: boolean; detail: string; failures: Record<string, unknown>[] }[];
}

// --- Phase 9: payments and lending ------------------------------------------------------

export type PaymentStatus = "pending" | "released" | "rejected";

export interface Payment {
  id: string;
  payment_number: string;
  debtor_account_number: string;
  debtor_name: string;
  creditor_account_number: string;
  creditor_name: string;
  amount: number;
  currency: string;
  reference: string;
  status: PaymentStatus;
  high_value: boolean;
  initiated_by_username: string | null;
  approved_by_username: string | null;
  journal_entry_id: string | null;
  rejection_reason: string | null;
  workflow_execution_id: string | null;
  created_at: string;
  decided_at: string | null;
}

export type LoanPurpose = "home_improvement" | "vehicle" | "education" | "debt_consolidation" | "other";

export interface Loan {
  id: string;
  loan_number: string;
  customer_id: string;
  customer_number: string;
  customer_name: string;
  disbursement_account_number: string;
  principal: number;
  currency: string;
  annual_rate_bps: number;
  term_months: number;
  monthly_payment: number;
  purpose: LoanPurpose;
  status: "active" | "repaid";
  outstanding: number;
  requested_by_username: string | null;
  underwritten_by_username: string | null;
  committee_approved_by_username: string | null;
  workflow_execution_id: string | null;
  disbursed_at: string;
}
