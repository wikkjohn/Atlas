/** Trade finance (Phase 37). Amounts are minor units of the instrument's currency. */
export interface TradeInstrument {
  id: string;
  instrument_number: string;
  kind: "letter_of_credit" | "guarantee";
  customer_number: string;
  customer_name: string;
  beneficiary_name: string;
  beneficiary_country: string;
  purpose: string;
  amount: number;
  currency: string;
  margin_bps: number;
  margin: number;
  drawn: number;
  expires_on: string;
  status: "requested" | "issued" | "declined" | "paid" | "expired";
  needs_committee: boolean;
  approved: boolean;
  committee_approved: boolean;
  screening_list: string | null;
  created_at: string;
}

export interface TradeDemand {
  id: string;
  demand_number: string;
  instrument_id: string;
  amount: number;
  presented_on: string;
  discrepancies: string[];
  status: "pending" | "paid" | "rejected";
  decision_note: string | null;
  decided_at: string | null;
}

export interface TradeSummary {
  requested: number;
  issued: number;
  pending_demands: number;
  paid: number;
  expired: number;
}

export const DISCREPANCIES = ["late_shipment", "late_presentation", "inconsistent_documents", "missing_document", "description_mismatch"] as const;
