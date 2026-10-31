/** Payments operations (Phase 41). Amounts are minor units of the payment's currency. */
export interface OutgoingPayment {
  id: string;
  payment_number: string;
  account_number: string;
  beneficiary_name: string;
  beneficiary_bank: string;
  beneficiary_account: string;
  amount: number;
  currency: string;
  reference: string;
  status: "awaiting_approval" | "pending" | "in_clearing" | "settled" | "returned" | "rejected" | "recalled";
  high_value: boolean;
  bulk_file_id: string | null;
  return_code: string | null;
  reason: string | null;
  settled_on: string | null;
  created_at: string;
}

export interface ClearingBatch {
  id: string;
  batch_number: string;
  currency: string;
  business_date: string;
  payments: number;
  total: number;
  settled_count: number;
  returned_count: number;
  status: "submitted" | "settled";
  created_at: string;
}

export interface BulkLine {
  line: number;
  name: string;
  bank: string;
  account: string;
  amount: number | null;
  reference: string;
  error?: string;
}

export interface BulkFile {
  id: string;
  file_number: string;
  account_number: string;
  file_name: string;
  currency: string;
  lines: BulkLine[];
  valid_count: number;
  invalid_count: number;
  valid_total: number;
  status: "received" | "released" | "rejected";
  decision_note: string | null;
  created_at: string;
}

export interface Recall {
  id: string;
  recall_number: string;
  payment_number: string;
  reason_code: "DUPL" | "FRAD" | "TECH" | "CUST";
  status: "requested" | "sent" | "accepted" | "refused" | "withdrawn";
  outcome_note: string | null;
  created_at: string;
}

export interface PaymentOpsSummary {
  awaiting_approval: number;
  pending: number;
  returned: number;
  bulk_received: number;
  open_recalls: number;
}

export const RECALL_REASONS = { DUPL: "Duplicate payment", FRAD: "Fraud", TECH: "Technical error", CUST: "Customer request" } as const;
