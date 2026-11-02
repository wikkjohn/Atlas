/** Customer service (Phase 51). Redress is in minor units of the account's currency. */

export type CaseCategory = "enquiry" | "request" | "complaint";
export type CasePriority = "low" | "normal" | "high" | "urgent";

export interface ServiceCase {
  id: string;
  case_number: string;
  customer_number: string;
  customer_name: string;
  account_number: string | null;
  category: CaseCategory;
  channel: "phone" | "email" | "chat" | "branch" | "letter";
  topic: string;
  priority: CasePriority;
  subject: string;
  description: string;
  status: "open" | "awaiting_customer" | "resolved";
  opened_at: string;
  first_response_due: string;
  resolve_due: string;
  first_responded_at: string | null;
  response_breached: boolean;
  resolution_breached: boolean;
  escalated: boolean;
  resolved_at: string | null;
  resolution: string | null;
  outcome: "upheld" | "partly_upheld" | "not_upheld" | null;
  redress_amount: number | null;
  redress_status: "proposed" | "paid" | "withdrawn" | null;
  redress_entry: string | null;
  currency: string | null;
}

export interface ServiceSummary {
  open: number;
  awaiting_customer: number;
  complaints_open: number;
  breached: number;
  due_today: number;
  redress_to_approve: number;
  avg_first_response_minutes: number | null;
}

export const TOPICS = ["account", "card", "payments", "lending", "fees", "digital", "other"] as const;
export const CHANNELS = ["phone", "email", "chat", "branch", "letter"] as const;
