/** Mortgages (Phase 33). Amounts are minor units of the property's currency unless named in USD. */
export interface MortgageProduct {
  product_code: string;
  name: string;
  max_ltv_bps: number;
  annual_rate_bps: number;
  max_term_years: number;
  min_loan_usd: number;
  max_loan_usd: number;
}

export interface Valuation {
  id: string;
  valuation_number: string;
  method: "desktop" | "surveyor";
  value: number;
  currency: string;
  valued_on: string;
  notes: string | null;
}

export interface Property {
  id: string;
  property_number: string;
  customer_number: string;
  customer_name: string;
  country_code: string;
  property_type: "house" | "flat";
  address: string;
  purchase_price: number;
  currency: string;
  latest_valuation: Valuation | null;
  charged_loan_number: string | null;
  created_at: string;
}

export interface MortgageApplication {
  customer_number: string;
  property_number: string;
  product_code: string;
  account_number: string;
  loan_amount: number;
  term_years: number;
  declared_monthly_income: number;
}

export interface QuoteCheck {
  rule: string;
  passed: boolean;
  detail: string;
}

export interface Quote {
  eligible: boolean;
  checks: QuoteCheck[];
  currency: string;
  loan_amount: number;
  term_months: number;
  annual_rate_bps: number;
  monthly_payment: number;
  ltv_bps: number;
  valuation_number: string | null;
  valuation_method: string | null;
  income_estimate: number;
  credit_score: number;
}

export interface MortgageOffer {
  id: string;
  offer_number: string;
  customer_number: string;
  property_number: string;
  product_code: string;
  loan_amount: number;
  currency: string;
  term_months: number;
  annual_rate_bps: number;
  monthly_payment: number;
  ltv_bps: number;
  status: "pending" | "offered" | "declined" | "accepted" | "completed" | "withdrawn";
  expired: boolean;
  expires_on: string | null;
  loan_number: string | null;
  created_at: string;
}

export interface MortgageSummary {
  properties: number;
  pending: number;
  offered: number;
  accepted: number;
  active_mortgages: number;
}
