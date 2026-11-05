/** Phase 85: the audit-log archive and the data-retention schedule. */

export interface AuditArchive {
  id: string;
  archive_number: number;
  before: string;
  first_event_at: string | null;
  last_event_at: string | null;
  events: number;
  location: string;
  bytes: number;
  sha256: string;
  previous_sha256: string | null;
  created_by: string | null;
  created_at: string;
  verified_at: string | null;
  verification: ArchiveVerification | null;
}

export interface ArchiveVerification {
  ok: boolean;
  problems: string[];
  sha256: string | null;
  events: number | null;
}

export interface ArchivedEvent {
  id: string;
  actor_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  timestamp: string;
  correlation_id: string | null;
  metadata: Record<string, unknown>;
}

export interface RetentionClass {
  id: string;
  name: string;
  tables: string[];
  purpose: string;
  retention: string;
  days: number | null;
  action: "delete" | "archive" | "keep" | "review";
  rows: number;
  due: number;
  cutoff: string | null;
  applied_by: string | null;
}

export interface RetentionReview {
  as_of: string;
  classes: RetentionClass[];
  due_total: number;
  last_run: { run_number: number; applied_at: string; results: Record<string, Record<string, number | null>> } | null;
}

/** Phase 87: a backup, verification, restore or recovery drill, as recorded by the CLI. */
export interface BackupRun {
  run_number: number;
  kind: "backup" | "verify" | "restore" | "drill";
  ok: boolean;
  location: string;
  details: {
    measured?: { backup_s: number; rto_s: number; rpo_s: number; total_s: number };
    backup_bytes?: number;
    checks?: { name: string; passed: boolean; detail: string }[];
    error?: string;
    [key: string]: unknown;
  };
  started_at: string;
  finished_at: string;
}

export interface BackupStatus {
  latest_backup: BackupRun | null;
  latest_drill: BackupRun | null;
  recovery_point_age_s: number | null;
  runs: BackupRun[];
}
