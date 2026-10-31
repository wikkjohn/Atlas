/** Cards (Phase 31). Amounts are minor units of the card's currency. */
export interface CardProduct {
  product_code: string;
  name: string;
  daily_limit_usd: number;
  validity_years: number;
}

export interface Card {
  id: string;
  card_number: string;
  last4: string;
  product_code: string;
  account_id: string;
  account_number: string;
  currency: string;
  daily_limit: number;
  expires_on: string;
  status: "active" | "blocked" | "cancelled";
  blocked_reason: string | null;
  issued_at: string;
}

export interface CardAuthorization {
  id: string;
  auth_code: string;
  card_id: string;
  card_last4: string;
  merchant_name: string;
  merchant_category: string;
  merchant_country: string;
  amount: number;
  currency: string;
  status: "approved" | "declined";
  decline_reason: string | null;
  fraud_score: number;
  fraud_signals: string[];
  created_at: string;
}

export interface CardDispute {
  id: string;
  dispute_number: string;
  auth_code: string;
  reason: string;
  amount: number;
  currency: string;
  status: "open" | "refunded" | "rejected";
  opened_at: string;
  decided_at: string | null;
}

export interface CardSummary {
  active_cards: number;
  blocked_cards: number;
  authorizations: number;
  declined: number;
  open_disputes: number;
}
