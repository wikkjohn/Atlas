/** Compliance (Phase 45). Amounts are minor units of the named currency. */
export type AmlRule = "large_cash" | "structuring" | "rapid_movement" | "high_risk_turnover";

export interface MonitoringRun {
  id: string;
  run_number: string;
  window_start: string;
  window_end: string;
  accounts_scanned: number;
  alerts_raised: number;
  created_at: string;
}

export interface AmlAlert {
  id: string;
  alert_number: string;
  customer_number: string;
  customer_name: string;
  account_number: string;
  rule: AmlRule;
  score: number;
  currency: string;
  amount: number;
  details: Record<string, unknown>;
  window_start: string;
  window_end: string;
  status: "open" | "in_case" | "dismissed" | "closed" | "escalated";
  case_number: string | null;
  note: string | null;
  created_at: string;
}

export interface ComplianceCase {
  id: string;
  case_number: string;
  customer_number: string;
  customer_name: string;
  status: "investigating" | "sar_drafted" | "sar_filed" | "closed";
  alerts: string[];
  sar_number: string | null;
  note: string | null;
  created_at: string;
}

export interface Sar {
  id: string;
  sar_number: string;
  case_number: string;
  customer_number: string;
  narrative: string;
  currency: string;
  amount: number;
  status: "draft" | "filed";
  filing_reference: string | null;
  created_at: string;
  filed_at: string | null;
}

export interface KycReview {
  id: string;
  review_number: string;
  customer_number: string;
  customer_name: string;
  due_on: string;
  status: "due" | "completed";
  risk_before: string;
  risk_after: string | null;
  outcome: "confirmed" | "raised" | "lowered" | null;
  completed_on: string | null;
}

export interface ComplianceSummary {
  open_alerts: number;
  open_cases: number;
  draft_sars: number;
  filed_sars: number;
  reviews_due: number;
  reviews_overdue: number;
}

export const RULE_LABELS: Record<AmlRule, string> = {
  large_cash: "Large cash deposit",
  structuring: "Structuring",
  rapid_movement: "Rapid movement of funds",
  high_risk_turnover: "High-risk customer turnover",
};
