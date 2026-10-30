export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface Job {
  id: string;
  job_number: number;
  kind: string;
  payload: Record<string, unknown>;
  status: JobStatus;
  attempts: number;
  max_attempts: number;
  run_at: string;
  result: Record<string, unknown> | null;
  last_error: string | null;
  locked_by: string | null;
  schedule_name: string | null;
  created_by_username: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface JobSchedule {
  id: string;
  name: string;
  description: string;
  kind: string;
  payload: Record<string, unknown>;
  interval_seconds: number;
  enabled: boolean;
  /** Runs only on this country's business days (Phase 26); null runs every day. */
  business_calendar: string | null;
  next_run_at: string;
  last_job: Job | null;
}
