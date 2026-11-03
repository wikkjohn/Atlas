/** Phase 74: the outbox — events between departments and their deliveries. */
export type DeliveryStatus = "pending" | "delivered" | "failed" | "dead";

export interface EventDelivery {
  id: string;
  subscriber: string;
  status: DeliveryStatus;
  attempts: number;
  next_attempt_at: string;
  last_error: string | null;
  delivered_at: string | null;
}

export interface DomainEvent {
  id: string;
  seq: number;
  topic: string;
  key: string;
  publisher: string;
  payload: Record<string, unknown>;
  occurred_at: string;
  deliveries: EventDelivery[];
}

export interface EventSummary {
  events: number;
  topics: Record<string, number>;
  subscribers: { topic: string; name: string; department: string; deliveries: Partial<Record<DeliveryStatus, number>> }[];
  waiting: number;
  dead: number;
  oldest_waiting_seconds: number | null;
}

export interface AccessGrant {
  id: string;
  grant_number: string;
  employee_id: string;
  employee_number: string | null;
  employee_name: string | null;
  profile: string;
  status: "requested" | "granted" | "revoked";
  requested_at: string;
  granted_at: string | null;
  revoked_at: string | null;
  revoke_reason: string | null;
}
