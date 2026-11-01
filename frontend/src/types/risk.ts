/** Risk (Phase 47). Amounts are minor units of the named currency unless named `_usd` (whole US dollars). */

export interface ObligorExposure {
  type: "loan" | "mortgage" | "facility" | "overdraft";
  reference: string;
  currency: string;
  ead: number;
  days_past_due: number;
}

export interface Obligor {
  customer_number: string;
  name: string;
  grade: number;
  pd_bps: number;
  limit_usd: number;
  limit_source: "grade" | "set";
  exposure_usd: number;
  excess_usd: number;
  exposures: ObligorExposure[];
}

export type Breach = Omit<Obligor, "exposures">;

export interface CreditRating {
  id: string;
  rating_number: string;
  customer_number: string;
  customer_name: string;
  grade: number;
  suggested_grade: number;
  pd_bps: number;
  factors: Record<string, unknown>;
  rationale: string;
  status: "pending" | "approved" | "rejected";
  rated_on: string;
  expires_on: string;
}

export interface ProvisionTotals {
  stage_1: number;
  stage_2: number;
  stage_3: number;
  ecl: number;
  ead: number;
  previous: number;
  change: number;
}

export interface ProvisionRun {
  id: string;
  run_number: string;
  as_of: string;
  status: "calculated" | "posted" | "rejected";
  exposures: number;
  totals: Record<string, ProvisionTotals>;
  note: string | null;
  created_at: string;
}

export interface ProvisionLine {
  exposure_type: ObligorExposure["type"];
  reference: string;
  currency: string;
  ead: number;
  days_past_due: number;
  grade: number;
  stage: 1 | 2 | 3;
  pd_bps: number;
  lgd_bps: number;
  ecl: number;
}

export interface RiskSummary {
  ratings_pending: number;
  ratings: number;
  runs_to_approve: number;
  last_posted_run: string | null;
  last_posted_as_of: string | null;
}

/** Percent from basis points: 25 -> "0.25 %". */
export const bps = (value: number) => `${(value / 100).toFixed(2)} %`;
