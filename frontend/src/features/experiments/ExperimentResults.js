import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { PairedBarChart } from "@/components/PairedBarChart";
import { StatusPill } from "@/components/StatusPill";
/** Cost lines in reading order (the API's JSON objects do not keep key order). */
export const COST_LINES = [
    ["review_labour", "Review labour"],
    ["automation_oversight", "Oversight of automated decisions"],
    ["ai_execution", "AI execution"],
    ["infrastructure", "Infrastructure"],
    ["exception_handling", "Exception handling"],
    ["manual_escalation", "Manual escalation"],
];
export const MODE_NAMES = { ai_assisted: "B — AI assisted", ai_automated: "C — AI automated tasks" };
export function VerdictPill({ verdict }) {
    if (!verdict)
        return null;
    return verdict === "successful" ? (_jsx(StatusPill, { tone: "good", label: "Successful" })) : (_jsx(StatusPill, { tone: "bad", label: "Not successful" }));
}
export function formatValue(value, unit, currency = "") {
    if (value === null)
        return "—";
    if (unit === "ratio")
        return `${(value * 100).toFixed(1)}%`;
    if (unit === "hours")
        return `${value.toFixed(2)} h`;
    if (unit === "currency")
        return `${currency}${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    return value.toLocaleString();
}
export function formatChange(row) {
    if (row.relative_change === null)
        return "—";
    const pct = row.relative_change * 100;
    return `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`;
}
export function CriteriaList({ experiment }) {
    const evaluation = experiment.evaluation;
    if (!evaluation)
        return null;
    return (_jsx("ul", { "aria-label": "Success criteria", className: "space-y-1.5", children: evaluation.criteria.map((c) => (_jsxs("li", { className: "flex items-start gap-2 text-sm", children: [c.passed ? (_jsx(CheckCircle2, { "aria-label": "Met", className: "mt-0.5 h-4 w-4 shrink-0 text-emerald-600" })) : (_jsx(XCircle, { "aria-label": "Not met", className: "mt-0.5 h-4 w-4 shrink-0 text-rose-600" })), _jsxs("span", { children: [_jsx("span", { className: "font-medium text-slate-900", children: c.label }), _jsx("span", { className: "block text-xs text-slate-600", children: c.detail })] })] }, c.criterion))) }));
}
export function ComparisonTable({ experiment }) {
    const evaluation = experiment.evaluation;
    if (!evaluation)
        return null;
    return (_jsx("div", { className: "overflow-x-auto rounded-xl border border-slate-200", children: _jsxs("table", { "aria-label": "Metric comparison", className: "min-w-full text-sm", children: [_jsx("thead", { className: "bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-3 py-2", children: "Metric" }), _jsx("th", { className: "px-3 py-2 text-right", children: "Baseline" }), _jsx("th", { className: "px-3 py-2 text-right", children: "Candidate" }), _jsx("th", { className: "px-3 py-2 text-right", children: "Change" })] }) }), _jsx("tbody", { className: "divide-y divide-slate-100", children: evaluation.comparisons.map((row) => (_jsxs("tr", { className: row.regression ? "bg-rose-50" : undefined, children: [_jsxs("td", { className: "px-3 py-2", children: [row.label, row.better === "none" && _jsx("span", { className: "ml-1 text-[11px] text-slate-400", children: "(informational)" })] }), _jsx("td", { className: "px-3 py-2 text-right tabular-nums", children: formatValue(row.baseline, row.unit) }), _jsx("td", { className: "px-3 py-2 text-right tabular-nums", children: formatValue(row.candidate, row.unit) }), _jsx("td", { className: "px-3 py-2 text-right tabular-nums", children: _jsxs("span", { className: "inline-flex items-center gap-1", children: [formatChange(row), row.regression && (_jsxs("span", { className: "inline-flex items-center gap-0.5 text-[11px] font-medium text-rose-700", children: [_jsx(AlertTriangle, { "aria-hidden": true, className: "h-3 w-3" }), " Regression"] })), row.improved && _jsx("span", { className: "text-[11px] font-medium text-emerald-700", children: "Better" })] }) })] }, row.metric))) })] }) }));
}
export function CostTable({ experiment }) {
    const evaluation = experiment.evaluation;
    if (!evaluation)
        return null;
    const { baseline, candidate } = evaluation.costs;
    const money = (v) => formatValue(v, "currency");
    return (_jsx("div", { className: "overflow-x-auto rounded-xl border border-slate-200", children: _jsxs("table", { "aria-label": "Cost breakdown", className: "min-w-full text-sm", children: [_jsx("thead", { className: "bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsxs("th", { className: "px-3 py-2", children: ["Cost line (", experiment.configuration.costs.currency_label, ")"] }), _jsx("th", { className: "px-3 py-2 text-right", children: "Baseline" }), _jsx("th", { className: "px-3 py-2 text-right", children: "Candidate" })] }) }), _jsxs("tbody", { className: "divide-y divide-slate-100", children: [COST_LINES.map(([line, label]) => (_jsxs("tr", { children: [_jsx("td", { className: "px-3 py-2", children: label }), _jsx("td", { className: "px-3 py-2 text-right tabular-nums", children: money(baseline.lines[line] ?? null) }), _jsx("td", { className: "px-3 py-2 text-right tabular-nums", children: money(candidate.lines[line] ?? null) })] }, line))), _jsxs("tr", { className: "font-semibold", children: [_jsx("td", { className: "px-3 py-2", children: "Operating total" }), _jsx("td", { className: "px-3 py-2 text-right tabular-nums", children: money(baseline.operating_total) }), _jsx("td", { className: "px-3 py-2 text-right tabular-nums", children: money(candidate.operating_total) })] }), _jsxs("tr", { children: [_jsx("td", { className: "px-3 py-2", children: "Cost per completed case" }), _jsx("td", { className: "px-3 py-2 text-right tabular-nums", children: money(baseline.cost_per_completed_case) }), _jsx("td", { className: "px-3 py-2 text-right tabular-nums", children: money(candidate.cost_per_completed_case) })] }), _jsxs("tr", { className: "text-slate-500", children: [_jsx("td", { className: "px-3 py-2", children: "Risk exposure of wrong decisions (not in operating cost)" }), _jsx("td", { className: "px-3 py-2 text-right tabular-nums", children: money(baseline.risk_exposure_total) }), _jsx("td", { className: "px-3 py-2 text-right tabular-nums", children: money(candidate.risk_exposure_total) })] })] })] }) }));
}
function seriesLabels(experiment) {
    return {
        baseline: `A — Baseline (run #${experiment.baseline.run_number})`,
        candidate: `${MODE_NAMES[experiment.candidate_mode]} (run #${experiment.candidate.run_number})`,
    };
}
export function ProcessingTimeChart({ experiment }) {
    const raw = Object.fromEntries(experiment.measurements.map((m) => [m.role, m.metrics]));
    const hours = (role, key) => {
        const v = raw[role]?.cycle_seconds[key];
        return v == null ? null : v / 3600;
    };
    return (_jsx(PairedBarChart, { title: "Processing time per case (simulated hours)", rows: ["avg", "p50", "p95"].map((key) => ({
            label: { avg: "Average", p50: "Median", p95: "95th percentile" }[key],
            baseline: hours("baseline", key),
            candidate: hours("candidate", key),
        })), format: (v) => `${v.toFixed(2)} h`, seriesLabels: seriesLabels(experiment), caption: "From the cases' recorded cycle times; steps take no simulated time, so this is waiting for people and documents." }));
}
export function CostChart({ experiment }) {
    const evaluation = experiment.evaluation;
    if (!evaluation)
        return null;
    const { baseline, candidate } = evaluation.costs;
    return (_jsx(PairedBarChart, { title: `Estimated operating cost by line (${experiment.configuration.costs.currency_label})`, rows: COST_LINES.map(([line, label]) => ({
            label,
            baseline: baseline.lines[line] ?? null,
            candidate: candidate.lines[line] ?? null,
        })), format: (v) => v.toLocaleString(undefined, { maximumFractionDigits: 0 }), seriesLabels: seriesLabels(experiment), caption: "Simulation estimates computed from the stated assumptions \u2014 not measured spending or verified savings." }));
}
export function QualityIndicators({ experiment }) {
    const evaluation = experiment.evaluation;
    if (!evaluation)
        return null;
    const pick = ["accuracy", "false_approval_rate", "false_rejection_rate", "escalation_rate", "error_count", "policy_violation_rate"];
    const rows = evaluation.comparisons.filter((r) => pick.includes(r.metric));
    return (_jsx("dl", { "aria-label": "Quality and compliance indicators", className: "grid grid-cols-2 gap-3 sm:grid-cols-3", children: rows.map((r) => (_jsxs("div", { className: `rounded-lg border p-3 ${r.regression ? "border-rose-300 bg-rose-50" : "border-slate-200 bg-white"}`, children: [_jsx("dt", { className: "text-xs text-slate-500", children: r.label }), _jsxs("dd", { className: "mt-0.5 text-sm text-slate-900", children: [_jsx("span", { className: "tabular-nums", children: formatValue(r.baseline, r.unit) }), _jsx("span", { className: "mx-1 text-slate-400", children: "\u2192" }), _jsx("span", { className: "font-semibold tabular-nums", children: formatValue(r.candidate, r.unit) })] }), r.regression && (_jsxs("dd", { className: "mt-0.5 inline-flex items-center gap-1 text-[11px] font-medium text-rose-700", children: [_jsx(AlertTriangle, { "aria-hidden": true, className: "h-3 w-3" }), " Regression"] }))] }, r.metric))) }));
}
