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
  // Phase 12: every run is recorded.
  id: string | null;
  run_number: number | null;
  mode: ReconciliationMode;
  window_start: string | null;
  window_end: string | null;
  duration_ms: number | null;
}

export type ReconciliationMode = "full" | "incremental";

export interface ReconciliationRun {
  id: string;
  run_number: number;
  mode: ReconciliationMode;
  ok: boolean;
  window_start: string | null;
  window_end: string;
  entries_checked: number;
  lines_checked: number;
  duration_ms: number;
  failed_checks: string[];
  run_by_username: string | null;
  created_at: string;
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
  // Cross-currency payments (Phase 24).
  creditor_currency?: string | null;
  creditor_amount?: number | null;
  fx_deal_number?: string | null;
  fx_rate?: string | null;
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

export type LoanStatus = "active" | "repaid" | "written_off";
export type ArrearsBucket = "current" | "1-29" | "30-59" | "60-89" | "90+";

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
  status: LoanStatus;
  outstanding: number;
  requested_by_username: string | null;
  underwritten_by_username: string | null;
  committee_approved_by_username: string | null;
  workflow_execution_id: string | null;
  disbursed_at: string;
  // Servicing (Phase 10), measured on the lending business date.
  instalments_paid: number;
  instalments_total: number;
  next_due_date: string | null;
  next_due_amount: number | null;
  days_past_due: number;
  arrears_amount: number;
  arrears_bucket: ArrearsBucket;
  closed_on: string | null;
  written_off_by_username: string | null;
}

export type InstalmentStatus = "scheduled" | "due" | "paid" | "prepaid" | "written_off";

export interface Instalment {
  number: number;
  due_date: string;
  principal: number;
  interest: number;
  amount: number;
  status: InstalmentStatus;
  paid_on: string | null;
}

export interface PayoffQuote {
  principal: number;
  accrued_interest: number;
  total: number;
  as_of: string;
}

export interface ServicingSummary {
  loans: number;
  accrued: number;
  collected: number;
  missed: number;
  repaid: number;
  in_arrears: number;
  arrears_amount: Record<string, number>;
  buckets: Partial<Record<ArrearsBucket, number>>;
}

export interface ServicingRun {
  id: string;
  run_number: number;
  as_of: string;
  started_by_username: string | null;
  summary: ServicingSummary;
  created_at: string;
}
