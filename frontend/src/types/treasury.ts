/** Treasury (Phase 39). Deal and trade amounts are minor units of their currency; limits and
 * exposures are whole US dollars. */
export interface Counterparty {
  id: string;
  code: string;
  name: string;
  country_code: string;
  rating: string;
  limit_usd: number;
  exposure_usd: number;
  investment_grade: boolean;
}

export interface Deal {
  id: string;
  deal_number: string;
  kind: "placement" | "borrowing";
  counterparty_code: string;
  counterparty_name: string;
  currency: string;
  principal: number;
  rate_bps: number;
  day_basis: number;
  value_date: string;
  maturity_date: string;
  interest: number;
  status: "booked" | "settled" | "matured" | "cancelled";
  created_at: string;
}

export interface FxTrade {
  id: string;
  trade_number: string;
  counterparty_code: string;
  sell_currency: string;
  sell_amount: number;
  buy_currency: string;
  buy_amount: number;
  mid_rate: string;
  trade_date: string;
  status: "booked" | "settled" | "cancelled";
  created_at: string;
}

export interface LiquidityRow {
  currency: string;
  cash: number;
  inflows: number;
  deposits: number;
  outflows: number;
  liquid: number;
  stressed_outflow: number;
  coverage_bps: number | null;
  below_minimum: boolean;
}

export interface Liquidity {
  as_of: string;
  horizon_days: number;
  run_off_bps: number;
  minimum_bps: number;
  currencies: LiquidityRow[];
}

export interface DeskPosition {
  currency: string;
  position: number;
  value_usd: number; // US cents
  limit_usd: number;
  utilisation_bps: number | null;
  over_limit: boolean;
  excess_usd: number;
}

export interface FxDesk {
  as_of: string;
  positions: DeskPosition[];
  total_value_usd: number;
}

export interface TreasurySummary {
  booked: number;
  placements: number;
  borrowings: number;
  fx_trades_booked: number;
}
