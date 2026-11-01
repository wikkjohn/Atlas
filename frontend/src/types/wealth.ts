/** Wealth and investments (Phase 43). Amounts are minor units of the named currency. */
export interface Security {
  id: string;
  code: string;
  name: string;
  asset_class: "money_market" | "bond" | "fund" | "equity" | "structured";
  currency: string;
  risk_level: number;
  complex: boolean;
  /** Today's price, in minor units of the security's currency. */
  price: number;
  income_bps: number;
}

export interface InvestmentProfile {
  id: string;
  objective: "preservation" | "income" | "balanced" | "growth";
  horizon_years: number;
  knowledge: "none" | "basic" | "informed" | "expert";
  loss_capacity: "low" | "medium" | "high";
  risk_profile: number;
  assessed_on: string;
  expires_on: string;
}

export interface Portfolio {
  id: string;
  portfolio_number: string;
  customer_number: string;
  customer_name: string;
  account_number: string;
  currency: string;
  status: "open" | "closed";
  risk_profile: number | null;
  created_at: string;
}

export interface HoldingLine {
  security_code: string;
  name: string;
  asset_class: Security["asset_class"];
  risk_level: number;
  units: number;
  price: number;
  price_currency: string;
  value: number;
  cost: number;
  gain: number;
}

export interface Valuation {
  portfolio_number: string;
  currency: string;
  as_of: string;
  holdings: HoldingLine[];
  value: number;
  cost: number;
  gain: number;
  cash: number;
}

export interface InvestmentOrder {
  id: string;
  order_number: string;
  portfolio_number: string;
  security_code: string;
  side: "buy" | "sell";
  units: number;
  price: number;
  price_currency: string;
  amount: number;
  fee: number;
  currency: string;
  status: "placed" | "awaiting_approval" | "executed" | "rejected";
  suitable: boolean;
  reasons: { code: string; message: string }[];
  note: string | null;
  executed_on: string | null;
  created_at: string;
}

export interface IncomeDistribution {
  id: string;
  distribution_number: string;
  security_code: string;
  record_date: string;
  income_per_unit: number;
  currency: string;
  holders: number;
  created_at: string;
}

export interface WealthSummary {
  portfolios: number;
  awaiting_approval: number;
  placed: number;
  executed: number;
  profiles: number;
  securities: number;
}
