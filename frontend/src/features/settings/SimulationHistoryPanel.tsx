import { ErrorMessage } from "@/components/ErrorMessage";
import { Panel } from "@/components/Panel";
import { formatTimestamp } from "@/features/dashboard/format";
import { formatBytes, humanize } from "@/services/format";
import { useHistoryOverview } from "@/services/simulations";
import type { PartitionUsage } from "@/types/simulations";

const TABLE_LABELS: Record<string, string> = {
  workflow_executions: "Executions",
  workflow_step_runs: "Step runs",
  workflow_events: "Events",
};

function usage(partitions: PartitionUsage[], table: string, realm: PartitionUsage["realm"]) {
  const p = partitions.find((x) => x.table === table && x.realm === realm);
  return p ? `${p.rows_estimate.toLocaleString()} rows · ${formatBytes(p.bytes)}` : "—";
}

export function SimulationHistoryPanel() {
  const overview = useHistoryOverview();
  const data = overview.data;
  const tables = [...new Set((data?.partitions ?? []).map((p) => p.table))];

  return (
    <Panel
      title="Simulation history"
      subtitle="Workflow history is partitioned: the live bank's and the simulations' are separate tables. Archive a run from the Simulation Center to move its history to files; `python -m app.cli simulation-history reset` drops all simulation history at once. Results and case outcomes always stay."
    >
      <ErrorMessage error={overview.error} />
      {data && (
        <div className="space-y-4 text-sm">
          <table aria-label="History partitions" className="min-w-full">
            <thead className="text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
              <tr>
                <th className="px-2 py-1">Table</th>
                <th className="px-2 py-1">Live bank</th>
                <th className="px-2 py-1">Simulations</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {tables.map((t) => (
                <tr key={t}>
                  <td className="px-2 py-1.5 text-slate-900">{TABLE_LABELS[t] ?? t}</td>
                  <td className="px-2 py-1.5 text-slate-600 tabular-nums">{usage(data.partitions, t, "live")}</td>
                  <td className="px-2 py-1.5 text-slate-600 tabular-nums">{usage(data.partitions, t, "simulation")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-slate-600">
            Runs with history in the database: {data.runs_by_history_state.present} · archived:{" "}
            {data.runs_by_history_state.archived} · removed by a reset: {data.runs_by_history_state.purged}. Archive
            files: {formatBytes(data.archive_bytes)} in <span className="font-mono">{data.archive_directory}</span>.
            Automatic archiving of runs older than 30 days is{" "}
            {data.retention_schedule_enabled ? "on" : "off"} (schedule simulation-history-retention, under Background
            jobs).
          </p>
          {data.recent_archives.length > 0 && (
            <table aria-label="Recent archives" className="min-w-full">
              <tbody className="divide-y divide-slate-100">
                {data.recent_archives.map((a) => (
                  <tr key={a.id}>
                    <td className="px-2 py-1.5 text-slate-900">Run #{a.run_number}</td>
                    <td className="px-2 py-1.5 text-slate-600">{a.kind === "archive" ? "Archived" : humanize("removed_by_reset")}</td>
                    <td className="px-2 py-1.5 text-right text-xs text-slate-600 tabular-nums">
                      {a.rows.toLocaleString()} rows{a.kind === "archive" && ` · ${formatBytes(a.bytes)}`}
                    </td>
                    <td className="px-2 py-1.5 text-right text-xs text-slate-500">
                      {formatTimestamp(a.created_at)}
                      {a.created_by_username && ` · ${a.created_by_username}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </Panel>
  );
}
