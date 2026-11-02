/** Collections and recoveries (Phase 53). Amounts are minor units of the loan's currency. */

export interface ArrearsRow {
  loan_number: string;
  customer_number: string;
  customer_name: string;
  currency: string;
  days_past_due: number;
  amount: number;
  instalments: number;
  bucket: string;
  oldest_due: string | null;
  plan_number: string | null;
  plan_status: string | null;
}

export interface PlanPayment {
  n: number;
  due: string;
  amount: number;
  status: "due" | "paid" | "missed" | "settled";
  on: string | null;
}

export interface PaymentPlan {
  id: string;
  plan_number: string;
  loan_number: string;
  currency: string;
  status: "proposed" | "active" | "completed" | "broken" | "rejected";
  arrears_amount: number;
  days_past_due: number;
  payments: number;
  interval_days: number;
  schedule: PlanPayment[];
  missed: number;
  start_date: string;
  note: string | null;
  created_at: string;
}

export interface WrittenOffRow {
  loan_number: string;
  customer_number: string;
  customer_name: string;
  currency: string;
  written_off_on: string | null;
  written_off: number;
  recovered: number;
  remaining: number;
}

export interface Recovery {
  id: string;
  recovery_number: string;
  loan_number: string;
  kind: "payment" | "agency" | "debt_sale";
  amount: number;
  currency: string;
  status: "recorded" | "posted" | "rejected";
  entry_number: string | null;
  note: string | null;
  created_at: string;
}

export interface CollectionsSummary {
  plans_proposed: number;
  plans_active: number;
  plans_broken: number;
  plans_completed: number;
  debt_sales_to_approve: number;
  loans_written_off: number;
}
