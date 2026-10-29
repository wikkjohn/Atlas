import { ErrorMessage } from "@/components/ErrorMessage";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { formatDuration, formatMilliseconds, formatTimestamp } from "@/features/dashboard/format";
import { formatBytes, humanize } from "@/services/format";
import { useObservability, useSlowQueries } from "@/services/observability";
import type { WorkerInfo } from "@/types/observability";

const WORKER_TONE: Record<WorkerInfo["state"], Tone> = { running: "good", lost: "bad", stopped: "neutral" };
const TOP_ROUTES = 8;

function Tile({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 px-3 py-2">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-lg font-semibold text-slate-900 tabular-nums">{value}</dd>
      {hint && <dd className="text-[11px] text-slate-500">{hint}</dd>}
    </div>
  );
}

function Heading({ children }: { children: string }) {
  return <h3 className="mt-5 mb-1 text-xs font-medium tracking-wide text-slate-500 uppercase">{children}</h3>;
}

export function ObservabilityPanel() {
  const overview = useObservability();
  const slow = useSlowQueries();
  const o = overview.data;

  return (
    <Panel
      title="Observability"
      subtitle="Request latency of this API process, the job queue and worker throughput, and statements slower than the threshold from every process. Refreshes every 10 seconds; Prometheus can scrape /api/metrics when ATLAS_METRICS_TOKEN is set."
    >
      <ErrorMessage error={overview.error ?? slow.error} />
      {o && (
        <>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Tile
              label="Jobs due"
              value={o.queue.due}
              hint={o.queue.oldest_due_seconds !== null ? `oldest waiting ${formatDuration(o.queue.oldest_due_seconds)}` : "none waiting"}
            />
            <Tile label="Jobs running" value={o.queue.running} hint={`${o.queue.scheduled_later} scheduled later`} />
            <Tile
              label="Workers"
              value={o.workers.filter((w) => w.state === "running").length}
              hint={o.process.jobs_execution === "inline" ? "jobs also run in the API (inline mode)" : "dedicated worker processes"}
            />
            <Tile
              label="Database"
              value={formatBytes(o.database.size_bytes)}
              hint={`${o.database.connections} connections · cache hits ${o.database.cache_hit_percent ?? "—"}%`}
            />
          </dl>

          <Heading>Job throughput, last hour</Heading>
          <table aria-label="Job throughput" className="min-w-full text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr>
                <th className="px-2 py-1 font-medium">Kind</th>
                <th className="px-2 py-1 text-right font-medium">Finished</th>
                <th className="px-2 py-1 text-right font-medium">Failed</th>
                <th className="px-2 py-1 text-right font-medium">Per minute</th>
                <th className="px-2 py-1 text-right font-medium">Average</th>
                <th className="px-2 py-1 text-right font-medium">p95</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {o.throughput.map((k) => (
                <tr key={k.kind}>
                  <td className="px-2 py-1.5 text-slate-900">{k.kind}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{k.finished}</td>
                  <td className={`px-2 py-1.5 text-right tabular-nums ${k.failed ? "text-rose-700" : ""}`}>{k.failed}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{k.per_minute}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{formatMilliseconds(k.avg_ms)}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{formatMilliseconds(k.p95_ms)}</td>
                </tr>
              ))}
              {o.throughput.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-2 py-3 text-center text-xs text-slate-500">No job finished in the last hour.</td>
                </tr>
              )}
            </tbody>
          </table>

          <Heading>Workers</Heading>
          {o.workers.length === 0 ? (
            <p className="text-xs text-slate-500">No worker process has run in the last day.</p>
          ) : (
            <table aria-label="Workers" className="min-w-full text-sm">
              <tbody className="divide-y divide-slate-100">
                {o.workers.map((w) => (
                  <tr key={w.name}>
                    <td className="px-2 py-1.5">
                      <div className="font-mono text-xs text-slate-900">{w.name}</div>
                      <div className="text-[11px] text-slate-500">
                        started {formatTimestamp(w.started_at)} · last seen {formatTimestamp(w.last_seen_at)}
                      </div>
                    </td>
                    <td className="px-2 py-1.5">
                      <StatusPill compact tone={WORKER_TONE[w.state]} label={humanize(w.state)} />
                    </td>
                    <td className="px-2 py-1.5 text-xs text-slate-600">{w.current_job_kind ?? "idle"}</td>
                    <td className="px-2 py-1.5 text-right text-xs text-slate-600 tabular-nums">
                      {w.succeeded} ok · {w.failed} failed · {w.retried} retried
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <Heading>Busiest requests (this API process)</Heading>
          <table aria-label="Request latency" className="min-w-full text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr>
                <th className="px-2 py-1 font-medium">Route</th>
                <th className="px-2 py-1 text-right font-medium">Requests</th>
                <th className="px-2 py-1 text-right font-medium">Errors</th>
                <th className="px-2 py-1 text-right font-medium">p50</th>
                <th className="px-2 py-1 text-right font-medium">p95</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {o.requests.slice(0, TOP_ROUTES).map((r) => (
                <tr key={`${r.method} ${r.route}`}>
                  <td className="px-2 py-1.5 font-mono text-xs text-slate-900">
                    {r.method} {r.route}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{r.count}</td>
                  <td className={`px-2 py-1.5 text-right tabular-nums ${r.errors ? "text-rose-700" : ""}`}>{r.errors}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{formatMilliseconds(r.p50_ms)}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{formatMilliseconds(r.p95_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <Heading>Slow queries</Heading>
          {o.process.slow_query_ms === 0 ? (
            <p className="text-xs text-slate-500">The slow-query log is off (ATLAS_SLOW_QUERY_MS=0).</p>
          ) : slow.data && slow.data.length === 0 ? (
            <p className="text-xs text-slate-500">No statement has taken longer than {o.process.slow_query_ms} ms.</p>
          ) : (
            <table aria-label="Slow queries" className="min-w-full text-sm">
              <tbody className="divide-y divide-slate-100">
                {slow.data?.map((q) => (
                  <tr key={`${q.context} ${q.statement}`}>
                    <td className="px-2 py-1.5">
                      <div className="max-w-xl truncate font-mono text-xs text-slate-900" title={q.statement}>
                        {q.statement}
                      </div>
                      <div className="text-[11px] text-slate-500">
                        {q.context ?? "no request or job"} · last {formatTimestamp(q.last_seen)}
                      </div>
                    </td>
                    <td className="px-2 py-1.5 text-right text-xs text-slate-600 tabular-nums">
                      {q.count}× · avg {formatMilliseconds(q.avg_ms)} · max {formatMilliseconds(q.max_ms)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </Panel>
  );
}
