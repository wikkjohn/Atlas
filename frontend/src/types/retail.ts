/** Retail banking (Phase 29). Money amounts are minor units unless the field says USD. */
export interface RetailProduct {
  account_type: string;
  name: string;
  credit_rate_bps: number;
  overdraft_rate_bps: number;
  monthly_fee_usd_cents: number;
  max_overdraft_usd: number;
  updated_at: string;
}

export interface StandingOrder {
  id: string;
  order_number: string;
  debtor_account_number: string;
  creditor_account_number: string;
  amount: number;
  currency: string;
  frequency: "weekly" | "monthly";
  next_date: string;
  end_date: string | null;
  reference: string;
  status: "active" | "cancelled" | "ended" | "failed";
  failures: number;
  last_error: string | null;
  payments_made: number;
  created_at: string;
}

export interface Statement {
  id: string;
  statement_number: string;
  account_id: string;
  account_number: string;
  period_start: string;
  period_end: string;
  currency: string;
  opening_balance: number;
  closing_balance: number;
  total_credits: number;
  total_debits: number;
  lines: number;
  overdraft_limit: number;
  issued_at: string;
}

export interface StatementEntry {
  date: string;
  entry_number: string;
  description: string;
  source: string;
  amount: number;
  balance: number;
}

export interface StatementDetail extends Statement {
  entries: StatementEntry[];
}

export interface MonthEndRun {
  id: string;
  period_start: string;
  period_end: string;
  accounts: number;
  statements: number;
  entries: number;
  totals: Record<string, { interest_paid: number; interest_charged: number; fees: number }>;
  completed_at: string;
}

export interface RetailSummary {
  overdrafts: number;
  active_standing_orders: number;
  statements: number;
}
