import { Play } from "lucide-react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { formatTimestamp } from "@/features/dashboard/format";
import { useCountries } from "@/services/enterprise";
import { useJobSchedules, useJobs, useRunSchedule, useUpdateSchedule } from "@/services/jobs";
import { humanize } from "@/services/format";
import type { Job, JobStatus } from "@/types/jobs";

const STATUS_TONE: Record<JobStatus, Tone> = {
  queued: "neutral",
  running: "warn",
  succeeded: "good",
  failed: "bad",
  cancelled: "neutral",
};

export function every(seconds: number): string {
  if (seconds % 86_400 === 0) return seconds === 86_400 ? "daily" : `every ${seconds / 86_400} days`;
  if (seconds % 3_600 === 0) return seconds === 3_600 ? "hourly" : `every ${seconds / 3_600} h`;
  return seconds === 60 ? "every minute" : `every ${Math.round(seconds / 60)} min`;
}

function duration(job: Job): string {
  const ms = job.result?.duration_ms;
  return typeof ms === "number" ? (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`) : "—";
}

function JobStatusPill({ job }: { job: Job }) {
  return <StatusPill compact tone={STATUS_TONE[job.status]} label={humanize(job.status)} />;
}

export function JobsPanel() {
  const { can } = useAuth();
  const manage = can("jobs:manage");
  const schedules = useJobSchedules();
  const jobs = useJobs({ limit: 15 });
  const update = useUpdateSchedule();
  const run = useRunSchedule();
  const countries = useCountries();

  return (
    <Panel
      title="Background jobs"
      subtitle="Reconciliation, loan servicing, workflow timers, simulations and experiments run as durable jobs. Worker processes (python -m app.cli worker) claim them; without one, the API runs the jobs it queues itself. Schedules queue at most one job at a time. A schedule with a business calendar runs on that country's business days only, moving past weekends and public holidays."
    >
      <ErrorMessage error={schedules.error ?? jobs.error ?? update.error ?? run.error} />
      <table aria-label="Job schedules" className="min-w-full text-sm">
        <thead className="text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
          <tr>
            <th className="px-2 py-1">Schedule</th>
            <th className="px-2 py-1">Runs</th>
            <th className="px-2 py-1">Business days</th>
            <th className="px-2 py-1">Next</th>
            <th className="px-2 py-1">Last job</th>
            <th className="px-2 py-1" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {schedules.data?.map((s) => (
            <tr key={s.id}>
              <td className="px-2 py-1.5">
                <div className="font-medium text-slate-900">{s.name}</div>
                <div className="text-xs text-slate-500">{s.description}</div>
              </td>
              <td className="px-2 py-1.5 text-slate-700">{every(s.interval_seconds)}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {manage ? (
                  <select
                    aria-label={`Business calendar of ${s.name}`}
                    className="rounded-md border border-slate-200 px-1.5 py-0.5 text-xs"
                    value={s.business_calendar ?? ""}
                    disabled={update.isPending}
                    onChange={(e) => update.mutate({ name: s.name, business_calendar: e.target.value })}
                  >
                    <option value="">Every day</option>
                    {countries.data?.items.map((c) => (
                      <option key={c.id} value={c.iso_country_code}>
                        {c.country_name}
                      </option>
                    ))}
                  </select>
                ) : (
                  (s.business_calendar ?? "Every day")
                )}
              </td>
              <td className="px-2 py-1.5 text-xs text-slate-600">{s.enabled ? formatTimestamp(s.next_run_at) : "Off"}</td>
              <td className="px-2 py-1.5">{s.last_job ? <JobStatusPill job={s.last_job} /> : <span className="text-xs text-slate-400">—</span>}</td>
              <td className="px-2 py-1.5">
                {manage && (
                  <div className="flex items-center justify-end gap-2">
                    <label className="flex items-center gap-1 text-xs text-slate-600">
                      <input
                        type="checkbox"
                        aria-label={`Enable ${s.name}`}
                        checked={s.enabled}
                        disabled={update.isPending}
                        onChange={(e) => update.mutate({ name: s.name, enabled: e.target.checked })}
                      />
                      On
                    </label>
                    <Button size="sm" variant="secondary" aria-label={`Run ${s.name} now`} disabled={run.isPending} onClick={() => run.mutate(s.name)}>
                      <Play aria-hidden className="h-3 w-3" /> Run now
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3 className="mt-5 mb-1 text-xs font-medium tracking-wide text-slate-500 uppercase">Recent jobs</h3>
      <table aria-label="Recent jobs" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {jobs.data?.items.map((j) => (
            <tr key={j.id}>
              <td className="px-2 py-1.5 font-mono text-xs">#{j.job_number}</td>
              <td className="px-2 py-1.5">
                <div className="text-slate-900">{j.kind}</div>
                <div className="text-[11px] text-slate-400">
                  {j.schedule_name ?? j.created_by_username ?? "system"} · {formatTimestamp(j.created_at)}
                </div>
              </td>
              <td className="px-2 py-1.5">
                <JobStatusPill job={j} />
                {j.last_error && <div className="mt-0.5 max-w-xs truncate text-[11px] text-rose-700" title={j.last_error}>{j.last_error}</div>}
              </td>
              <td className="px-2 py-1.5 text-xs text-slate-600 tabular-nums">
                {j.attempts}/{j.max_attempts} attempts
              </td>
              <td className="px-2 py-1.5 text-right text-xs text-slate-600 tabular-nums">{duration(j)}</td>
            </tr>
          ))}
          {jobs.data?.items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No jobs yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}
