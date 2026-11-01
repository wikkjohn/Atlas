/** Finance (Phase 49). Amounts are minor units of the named currency. */

export interface CloseCheck {
  check: "period_ended" | "trial_balance" | "reconciliation" | "provisions_posted";
  passed: boolean;
  blocking: boolean;
  detail: string;
}

export interface CurrencyResult {
  income: number;
  expense: number;
  net_income: number;
  accounts: { code: string; type: "income" | "expense"; balance: number }[];
}

export interface PeriodClose {
  id: string;
  close_number: string;
  period: string;
  period_start: string;
  period_end: string;
  status: "prepared" | "closed" | "rejected";
  checks: CloseCheck[];
  results: Record<string, CurrencyResult>;
  note: string | null;
  created_at: string;
}

export type ReportType = "balance_sheet" | "income_statement" | "large_exposures" | "credit_quality";

export interface RegulatoryReport {
  id: string;
  report_number: string;
  report_type: ReportType;
  period: string;
  status: "prepared" | "submitted" | "rejected";
  rows: Record<string, string | number | boolean | null>[];
  summary: Record<string, unknown>;
  reference: string | null;
  note: string | null;
  created_at: string;
}

export interface CostAllocation {
  id: string;
  allocation_number: string;
  period: string;
  currency: string;
  pool: number;
  driver: string;
  lines: { department_id: string; department: string; headcount: number; amount: number; account_code: string }[];
  status: "calculated" | "posted" | "rejected";
  note: string | null;
  created_at: string;
}

export interface JournalLine {
  account_code: string;
  direction: "debit" | "credit";
  amount: number;
}

export interface ManualJournal {
  id: string;
  journal_number: string;
  currency: string;
  effective_date: string;
  description: string;
  lines: JournalLine[];
  amount: number;
  status: "proposed" | "posted" | "rejected";
  entry_number: string | null;
  note: string | null;
  created_at: string;
}

export interface FinanceSummary {
  last_closed_period: string | null;
  next_period: string | null;
  closes_to_approve: number;
  reports_to_submit: number;
  reports_submitted: number;
  allocations_to_post: number;
  journals_to_approve: number;
}

export const REPORT_LABELS: Record<ReportType, string> = {
  balance_sheet: "Balance sheet",
  income_statement: "Income statement",
  large_exposures: "Large exposures",
  credit_quality: "Credit quality",
};

export const CHECK_LABELS: Record<CloseCheck["check"], string> = {
  period_ended: "Month ended",
  trial_balance: "Trial balance",
  reconciliation: "Reconciliation",
  provisions_posted: "ECL provisions",
};
