export interface FxRate {
  currency: string;
  rate_date: string;
  units_per_usd: string;
}

export interface FxQuote {
  sell_currency: string;
  sell_amount: number;
  buy_currency: string;
  buy_amount: number;
  mid_rate: string;
  customer_rate: string;
  margin_bps: number;
  rate_date: string;
  base_amount: number;
}

export interface FxPosition {
  currency: string;
  position: number;
  units_per_usd: string;
  value_usd: number;
}

export interface FxPositions {
  as_of: string;
  positions: FxPosition[];
  total_value_usd: number;
  booked_usd: number;
  unbooked_usd: number;
}

export interface FxRevaluation {
  id: string;
  run_number: number;
  as_of: string;
  positions: FxPosition[];
  total_value: number;
  previously_booked: number;
  posted: number;
  journal_entry_id: string | null;
  created_at: string;
}

export interface FxDeal {
  id: string;
  deal_number: string;
  purpose: string;
  reference: string;
  rate_date: string;
  sell_currency: string;
  sell_amount: number;
  buy_currency: string;
  buy_amount: number;
  mid_rate: string;
  customer_rate: string;
  margin_bps: number;
  created_at: string;
}
