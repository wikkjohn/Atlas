/** Commercial lending (Phase 35). Amounts are minor units of the facility's currency. */
export interface Covenant {
  kind: "min_dscr" | "max_leverage";
  threshold_centi: number;
}

export interface Facility {
  id: string;
  facility_number: string;
  customer_number: string;
  customer_name: string;
  facility_type: "term_loan" | "revolving";
  purpose: string;
  credit_limit: number;
  currency: string;
  annual_rate_bps: number;
  term_months: number;
  drawn: number;
  available: number;
  status: "proposed" | "active" | "frozen" | "declined" | "terminated";
  frozen_reason: string | null;
  draw_block: string | null;
  needs_committee: boolean;
  approved: boolean;
  committee_approved: boolean;
  review_due_on: string | null;
  matures_on: string | null;
  covenants: Covenant[];
  created_at: string;
}

export interface CovenantResult {
  kind: string;
  threshold_centi: number;
  actual_centi: number;
  passed: boolean;
}

export interface CovenantTest {
  id: string;
  facility_id: string;
  period_end: string;
  ebitda: number;
  debt_service: number;
  total_debt: number;
  results: CovenantResult[];
  breached: boolean;
  waived: boolean;
  created_at: string;
}

export interface FacilityReview {
  id: string;
  review_number: string;
  facility_id: string;
  due_on: string;
  outcome: "renewed" | "terminated" | null;
  new_limit: number | null;
  decided_at: string | null;
}

export interface CommercialSummary {
  proposed: number;
  active: number;
  frozen: number;
  reviews_due: number;
  open_reviews: number;
}
