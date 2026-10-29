export interface RouteMetrics {
  method: string;
  route: string;
  count: number;
  errors: number;
  by_status: Record<string, number>;
  avg_ms: number;
  p50_ms: number | null;
  p95_ms: number | null;
  max_ms: number;
}

export interface KindThroughput {
  kind: string;
  finished: number;
  succeeded: number;
  failed: number;
  per_minute: number;
  avg_ms: number | null;
  p95_ms: number | null;
  max_ms: number | null;
}

export interface WorkerInfo {
  name: string;
  hostname: string;
  pid: number;
  state: "running" | "lost" | "stopped";
  started_at: string;
  last_seen_at: string;
  stopped_at: string | null;
  succeeded: number;
  failed: number;
  retried: number;
  current_job_kind: string | null;
}

export interface ObservabilityOverview {
  process: {
    version: string;
    pid: number;
    uptime_seconds: number;
    jobs_execution: "inline" | "worker";
    slow_query_ms: number;
  };
  requests: RouteMetrics[];
  queue: { due: number; scheduled_later: number; running: number; oldest_due_seconds: number | null };
  throughput: KindThroughput[];
  workers: WorkerInfo[];
  database: { size_bytes: number; connections: number; cache_hit_percent: number | null };
}

export interface SlowQueryGroup {
  statement: string;
  context: string | null;
  count: number;
  avg_ms: number;
  max_ms: number;
  total_ms: number;
  last_seen: string;
}
