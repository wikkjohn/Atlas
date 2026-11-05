import { ErrorMessage } from "@/components/ErrorMessage";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { formatTimestamp } from "@/features/dashboard/format";
import { useBackups } from "@/services/governance";
import type { BackupRun } from "@/types/governance";

function age(seconds: number): string {
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h`;
  return `${Math.round(seconds / 86400)} days`;
}

function describe(run: BackupRun): string {
  const m = run.details.measured;
  if (run.kind === "drill" && m) return `restored and checked in ${m.rto_s.toFixed(1)} s (recovery point ${m.rpo_s.toFixed(0)} s old)`;
  if (run.details.error) return String(run.details.error);
  return run.location;
}

/** Phase 87: the latest backup and recovery drill, and the recent runs. Read only. */
export function BackupPanel() {
  const backups = useBackups();
  const data = backups.data;
  return (
    <Panel
      title="Backups and recovery drills"
      subtitle="Taken with python -m app.cli backup: a snapshot dump, the archive files and a manifest each restore is checked against"
      className="mb-4"
    >
      <ErrorMessage error={backups.error} />
      {data && (
        <>
          <dl className="mb-3 grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-xs text-slate-500">Latest backup</dt>
              <dd>{data.latest_backup ? formatTimestamp(data.latest_backup.finished_at) : "None yet"}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Latest passing drill</dt>
              <dd>
                {data.latest_drill
                  ? `${formatTimestamp(data.latest_drill.finished_at)} · RTO ${data.latest_drill.details.measured?.rto_s.toFixed(1) ?? "?"} s`
                  : "None yet"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Recovery point age</dt>
              <dd>{data.recovery_point_age_s === null ? "No backup" : age(data.recovery_point_age_s)}</dd>
            </div>
          </dl>
          {data.runs.length === 0 ? (
            <p className="text-sm text-slate-500">No backup has been recorded. Run python -m app.cli backup drill.</p>
          ) : (
            <table aria-label="Backup runs" className="min-w-full text-xs">
              <thead className="text-left text-slate-500">
                <tr>
                  <th className="py-1 pr-3 font-medium">Run</th>
                  <th className="py-1 pr-3 font-medium">Kind</th>
                  <th className="py-1 pr-3 font-medium">Finished</th>
                  <th className="py-1 pr-3 font-medium">Result</th>
                  <th className="py-1 pr-3 font-medium">Detail</th>
                </tr>
              </thead>
              <tbody>
                {data.runs.map((run) => (
                  <tr key={run.run_number} className="border-t border-slate-100">
                    <td className="py-1 pr-3">#{run.run_number}</td>
                    <td className="py-1 pr-3 capitalize">{run.kind}</td>
                    <td className="py-1 pr-3">{formatTimestamp(run.finished_at)}</td>
                    <td className="py-1 pr-3">
                      <StatusPill tone={run.ok ? "good" : "bad"} label={run.ok ? "Passed" : "Failed"} compact />
                    </td>
                    <td className="py-1 pr-3 break-all">{describe(run)}</td>
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
