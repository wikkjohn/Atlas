import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Panel } from "@/components/Panel";
import { formatTimestamp } from "@/features/dashboard/format";
import { formatBytes, humanize } from "@/services/format";
import { useHistoryOverview } from "@/services/simulations";
const TABLE_LABELS = {
    workflow_executions: "Executions",
    workflow_step_runs: "Step runs",
    workflow_events: "Events",
};
function usage(partitions, table, realm) {
    const p = partitions.find((x) => x.table === table && x.realm === realm);
    return p ? `${p.rows_estimate.toLocaleString()} rows · ${formatBytes(p.bytes)}` : "—";
}
export function SimulationHistoryPanel() {
    const overview = useHistoryOverview();
    const data = overview.data;
    const tables = [...new Set((data?.partitions ?? []).map((p) => p.table))];
    return (_jsxs(Panel, { title: "Simulation history", subtitle: "Workflow history is partitioned: the live bank's and the simulations' are separate tables. Archive a run from the Simulation Center to move its history to files; `python -m app.cli simulation-history reset` drops all simulation history at once. Results and case outcomes always stay.", children: [_jsx(ErrorMessage, { error: overview.error }), data && (_jsxs("div", { className: "space-y-4 text-sm", children: [_jsxs("table", { "aria-label": "History partitions", className: "min-w-full", children: [_jsx("thead", { className: "text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-2 py-1", children: "Table" }), _jsx("th", { className: "px-2 py-1", children: "Live bank" }), _jsx("th", { className: "px-2 py-1", children: "Simulations" })] }) }), _jsx("tbody", { className: "divide-y divide-slate-100", children: tables.map((t) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 text-slate-900", children: TABLE_LABELS[t] ?? t }), _jsx("td", { className: "px-2 py-1.5 text-slate-600 tabular-nums", children: usage(data.partitions, t, "live") }), _jsx("td", { className: "px-2 py-1.5 text-slate-600 tabular-nums", children: usage(data.partitions, t, "simulation") })] }, t))) })] }), _jsxs("p", { className: "text-xs text-slate-600", children: ["Runs with history in the database: ", data.runs_by_history_state.present, " \u00B7 archived:", " ", data.runs_by_history_state.archived, " \u00B7 removed by a reset: ", data.runs_by_history_state.purged, ". Archive files: ", formatBytes(data.archive_bytes), " in ", _jsx("span", { className: "font-mono", children: data.archive_directory }), ". Automatic archiving of runs older than 30 days is", " ", data.retention_schedule_enabled ? "on" : "off", " (schedule simulation-history-retention, under Background jobs)."] }), data.recent_archives.length > 0 && (_jsx("table", { "aria-label": "Recent archives", className: "min-w-full", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: data.recent_archives.map((a) => (_jsxs("tr", { children: [_jsxs("td", { className: "px-2 py-1.5 text-slate-900", children: ["Run #", a.run_number] }), _jsx("td", { className: "px-2 py-1.5 text-slate-600", children: a.kind === "archive" ? "Archived" : humanize("removed_by_reset") }), _jsxs("td", { className: "px-2 py-1.5 text-right text-xs text-slate-600 tabular-nums", children: [a.rows.toLocaleString(), " rows", a.kind === "archive" && ` · ${formatBytes(a.bytes)}`] }), _jsxs("td", { className: "px-2 py-1.5 text-right text-xs text-slate-500", children: [formatTimestamp(a.created_at), a.created_by_username && ` · ${a.created_by_username}`] })] }, a.id))) }) }))] }))] }));
}
