import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Banknote, Bot, Clock, FlaskConical, Globe2, PlayCircle, RefreshCw, Users, Wallet, Workflow, XCircle, CheckCircle2, Activity, } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "@/app/auth";
import { BackendUnavailable } from "@/components/BackendUnavailable";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { SyntheticDataBadge } from "@/components/SyntheticDataBadge";
import { formatTimestamp } from "@/features/dashboard/format";
import { HealthTiles } from "@/features/dashboard/PlatformHealth";
import { useAnalyticsOverview } from "@/services/analytics";
import { BackendUnreachableError } from "@/services/api";
import { humanize } from "@/services/format";
import { useHealth, useSystemInfo, useSystemStatus } from "@/services/queries";
import { MODE_LABELS } from "@/types/simulations";
const TILE = {
    employees: { icon: Users, to: "/employees", permission: "employees:read" },
    countries: { icon: Globe2, to: "/countries", permission: "countries:read" },
    workflows: { icon: Workflow, to: "/workflows", permission: "workflows:read" },
    active_simulations: { icon: PlayCircle, to: "/simulations", permission: "simulations:read" },
    completed_executions: { icon: CheckCircle2, to: "/workflows?tab=executions", permission: "workflows:read" },
    failed_executions: { icon: XCircle, to: "/workflows?tab=executions", permission: "workflows:read" },
    accounts: { icon: Banknote, to: "/accounts", permission: "accounts:read" },
    ai_tools: { icon: Bot, to: "/ai-lab", permission: "ai_tools:read" },
    experiments: { icon: FlaskConical, to: "/experiments", permission: "experiments:read" },
    avg_process_duration: { icon: Clock, to: "/simulations", permission: "simulations:read" },
    simulation_cost: { icon: Wallet, to: "/benchmarking", permission: "experiments:read" },
};
function formatMetric(m, currency) {
    if (m.value === null)
        return "—";
    if (m.unit === "hours")
        return `${m.value.toFixed(2)} h`;
    if (m.unit === "currency")
        return `${m.value.toLocaleString(undefined, { maximumFractionDigits: 0 })} ${currency}`;
    return m.value.toLocaleString();
}
function MetricTile({ metric, currency }) {
    const { can } = useAuth();
    const tile = TILE[metric.key];
    const Icon = tile?.icon ?? Activity;
    const body = (_jsxs(_Fragment, { children: [_jsxs("div", { className: "flex items-center justify-between gap-2", children: [_jsxs("span", { className: "flex items-center gap-2 text-xs font-medium text-slate-500", children: [_jsx(Icon, { "aria-hidden": true, className: "h-4 w-4 text-slate-400" }), metric.label] }), metric.estimate && (_jsx("span", { className: "rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-amber-800 uppercase", children: "Estimate" }))] }), _jsx("div", { className: "mt-2 text-2xl font-semibold tracking-tight text-slate-900 tabular-nums", children: formatMetric(metric, metric.unit === "currency" ? "" : currency) }), _jsx("div", { className: "mt-1 text-[11px] leading-snug text-slate-500", children: metric.detail })] }));
    // The cost estimate is wider so eleven tiles close the last row of four.
    const span = metric.key === "simulation_cost" ? "xl:col-span-2" : "";
    const className = `block rounded-xl border border-slate-200 bg-white p-4 shadow-sm ${span}`;
    const linked = tile && (!tile.permission || can(tile.permission));
    return linked ? (_jsx(Link, { to: tile.to, "aria-label": `${metric.label}: ${formatMetric(metric, "")}`, className: `${className} transition hover:border-slate-300 hover:shadow`, children: body })) : (_jsx("div", { role: "group", "aria-label": metric.label, className: className, children: body }));
}
const OUTCOME_TONE = { completed: "good", waiting: "warn", running: "warn", failed: "bad", cancelled: "neutral" };
export function OverviewPage() {
    const health = useHealth();
    const status = useSystemStatus();
    const info = useSystemInfo();
    const analytics = useAnalyticsOverview();
    const refreshAll = () => {
        void health.refetch();
        void status.refetch();
        void info.refetch();
        void analytics.refetch();
    };
    const refreshing = health.isFetching || status.isFetching || info.isFetching || analytics.isFetching;
    const header = (_jsxs("div", { className: "mb-6 flex flex-wrap items-end justify-between gap-4", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-xl font-semibold text-slate-900", children: "Enterprise Overview" }), _jsx("p", { className: "mt-1 text-sm text-slate-500", children: "ATLAS Global Bank at a glance \u2014 workforce, banking, workflows, simulations and AI experiments. Every figure is computed from the platform's synthetic records." })] }), _jsxs("div", { className: "flex items-center gap-3", children: [_jsx(SyntheticDataBadge, {}), analytics.dataUpdatedAt > 0 && (_jsxs("span", { className: "text-xs text-slate-500", children: ["Updated ", new Date(analytics.dataUpdatedAt).toLocaleTimeString()] })), _jsxs("button", { type: "button", onClick: refreshAll, disabled: refreshing, className: "inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-60", children: [_jsx(RefreshCw, { "aria-hidden": true, className: `h-4 w-4 ${refreshing ? "animate-spin" : ""}` }), "Refresh"] })] })] }));
    if (health.error instanceof BackendUnreachableError) {
        return (_jsxs(_Fragment, { children: [header, _jsx(BackendUnavailable, { onRetry: refreshAll, retrying: refreshing, detail: health.error.cause instanceof Error ? health.error.cause.message : undefined })] }));
    }
    const data = analytics.data;
    const currency = data?.cost_assumptions.currency_label ?? "";
    const outcomes = Object.entries(data?.workflow_outcomes ?? {});
    const totalLive = outcomes.reduce((sum, [, n]) => sum + n, 0);
    return (_jsxs(_Fragment, { children: [header, health.error && (_jsxs("div", { role: "alert", className: "mb-6 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800", children: ["Health check failed: ", health.error.message] })), _jsx(ErrorMessage, { error: analytics.error, className: "mb-6" }), _jsx("section", { "aria-label": "Key metrics", className: "grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4", children: data
                    ? data.metrics.map((m) => _jsx(MetricTile, { metric: m, currency: currency }, m.key))
                    : !analytics.error &&
                        Array.from({ length: 8 }, (_, i) => (_jsx("div", { className: "h-28 animate-pulse rounded-xl border border-slate-200 bg-white" }, i))) }), data && (_jsxs("div", { className: "mt-6 grid grid-cols-1 gap-6 xl:grid-cols-3", children: [_jsxs(Panel, { title: "Workflow operations", subtitle: "Live cases of every workflow (simulated cases are counted per run)", children: [totalLive === 0 ? (_jsx("p", { className: "text-sm text-slate-500", children: "No live workflow executions yet." })) : (_jsx("ul", { "aria-label": "Live executions by status", className: "space-y-2 text-sm", children: outcomes
                                    .sort(([a], [b]) => a.localeCompare(b))
                                    .map(([state, n]) => (_jsxs("li", { className: "flex items-center justify-between gap-3", children: [_jsx(StatusPill, { tone: OUTCOME_TONE[state] ?? "neutral", label: humanize(state) }), _jsxs("span", { className: "flex flex-1 items-center gap-2", children: [_jsx("span", { className: "h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100", children: _jsx("span", { className: "block h-full rounded-full bg-slate-400", style: { width: `${(n / totalLive) * 100}%` } }) }), _jsx("span", { className: "w-10 text-right tabular-nums text-slate-700", children: n })] })] }, state))) })), _jsxs("p", { className: "mt-4 text-xs text-slate-600", children: [_jsxs(Link, { to: "/workflows?tab=tasks", className: "font-medium text-navy-700 hover:underline", children: [data.open_tasks, " open task", data.open_tasks === 1 ? "" : "s"] }), " ", "waiting for an authorized person."] })] }), _jsx(Panel, { title: "Recent simulation runs", children: data.recent_runs.length === 0 ? (_jsx("p", { className: "text-sm text-slate-500", children: "No simulation has been run yet." })) : (_jsx("ul", { "aria-label": "Recent simulation runs", className: "divide-y divide-slate-100 text-sm", children: data.recent_runs.map((r) => (_jsxs("li", { className: "flex items-center justify-between gap-2 py-2", children: [_jsxs(Link, { to: `/simulations?run=${r.id}`, className: "font-medium text-slate-900 hover:underline", children: ["Run #", r.run_number, _jsxs("span", { className: "ml-1 text-xs font-normal text-slate-500", children: [MODE_LABELS[r.mode] ?? humanize(r.mode), " \u00B7 ", r.applications.toLocaleString(), " apps"] })] }), _jsx(StatusPill, { tone: r.status === "completed" ? "good" : r.status === "failed" ? "bad" : "warn", label: humanize(r.status), compact: true })] }, r.id))) })) }), _jsx(Panel, { title: "Recent experiments", children: data.recent_experiments.length === 0 ? (_jsx("p", { className: "text-sm text-slate-500", children: "No experiment has been run yet." })) : (_jsx("ul", { "aria-label": "Recent experiments", className: "divide-y divide-slate-100 text-sm", children: data.recent_experiments.map((e) => (_jsxs("li", { className: "flex items-center justify-between gap-2 py-2", children: [_jsxs(Link, { to: `/experiments?experiment=${e.id}`, className: "min-w-0 truncate font-medium text-slate-900 hover:underline", children: ["#", e.experiment_number, " ", e.name] }), e.verdict ? (_jsx(StatusPill, { tone: e.verdict === "successful" ? "good" : "bad", label: e.verdict === "successful" ? "Successful" : "Not successful", compact: true })) : (_jsx(StatusPill, { tone: e.status === "failed" ? "bad" : "warn", label: humanize(e.status), compact: true }))] }, e.id))) })) })] })), _jsxs("section", { "aria-label": "Platform health", className: "mt-6 space-y-3", children: [_jsxs("div", { className: "flex items-center justify-between", children: [_jsx("h2", { className: "text-sm font-semibold text-slate-900", children: "Platform health" }), _jsx(Link, { to: "/settings", className: "text-xs font-medium text-navy-700 hover:underline", children: "System settings" })] }), _jsx(HealthTiles, { health: health, status: status, info: info })] }), data && (_jsxs("p", { className: "mt-6 text-xs text-slate-500", children: ["Figures as of ", formatTimestamp(data.generated_at), ". The operating cost is an estimate from the default, stated assumptions (", currency, ") applied to what the simulation runs recorded \u2014 not measured spending."] }))] }));
}
