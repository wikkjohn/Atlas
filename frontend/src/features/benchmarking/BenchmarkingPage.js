import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Link, useSearchParams } from "react-router-dom";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { SyntheticDataBadge } from "@/components/SyntheticDataBadge";
import { CostChart, CriteriaList, formatChange, MODE_NAMES, ProcessingTimeChart, QualityIndicators, VerdictPill, } from "@/features/experiments/ExperimentResults";
import { useBenchmarks, useExperiment, useExperiments } from "@/services/experiments";
const CHANGE_COLUMNS = [
    ["labour_hours", "Labour time"],
    ["cost_per_completed_case", "Cost per case"],
    ["processing_time_hours", "Processing time"],
    ["accuracy", "Accuracy"],
];
function Leaderboard() {
    const benchmarks = useBenchmarks();
    return (_jsxs("div", { className: "space-y-2", children: [_jsx(ErrorMessage, { error: benchmarks.error }), _jsx("div", { className: "overflow-x-auto rounded-xl border border-slate-200", children: _jsxs("table", { "aria-label": "Tool benchmarks", className: "min-w-full text-sm", children: [_jsx("thead", { className: "bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-3 py-2", children: "Tool" }), _jsx("th", { className: "px-3 py-2", children: "Configuration" }), _jsx("th", { className: "px-3 py-2 text-right", children: "Experiments" }), CHANGE_COLUMNS.map(([, label]) => (_jsx("th", { className: "px-3 py-2 text-right", children: label }, label))), _jsx("th", { className: "px-3 py-2", children: "Latest verdict" })] }) }), _jsxs("tbody", { className: "divide-y divide-slate-100", children: [(benchmarks.data ?? []).map((row) => (_jsxs("tr", { children: [_jsxs("td", { className: "px-3 py-2", children: [_jsx("span", { className: "font-medium", children: row.tool_id }), " ", _jsx("span", { className: "text-xs text-slate-500", children: row.tool_version })] }), _jsx("td", { className: "px-3 py-2", children: MODE_NAMES[row.candidate_mode] }), _jsxs("td", { className: "px-3 py-2 text-right tabular-nums", children: [row.successful, "/", row.experiments, " successful"] }), CHANGE_COLUMNS.map(([key]) => (_jsx("td", { className: "px-3 py-2 text-right tabular-nums", children: formatChange({ relative_change: row.median_relative_change[key] ?? null }) }, key))), _jsx("td", { className: "px-3 py-2", children: _jsx(Link, { to: `/benchmarking?experiment=${row.latest_experiment_id}`, className: "hover:underline", children: _jsx(VerdictPill, { verdict: row.latest_verdict }) }) })] }, `${row.tool_id}-${row.tool_version}-${row.candidate_mode}`))), benchmarks.data?.length === 0 && (_jsx("tr", { children: _jsx("td", { colSpan: 8, className: "px-3 py-6 text-center text-sm text-slate-500", children: "No completed experiments yet. Run one from the Experiments screen." }) }))] })] }) }), _jsx("p", { className: "text-[11px] text-slate-500", children: "Median relative change versus each experiment's own baseline (negative is lower). Simulated estimates on synthetic data under each experiment's stated assumptions." })] }));
}
function ExperimentBenchmark({ id }) {
    const experiment = useExperiment(id);
    const e = experiment.data;
    if (experiment.error)
        return _jsx(ErrorMessage, { error: experiment.error });
    if (!e)
        return _jsx("p", { className: "text-sm text-slate-500", children: "Loading\u2026" });
    if (!e.evaluation) {
        return _jsxs("p", { className: "text-sm text-slate-500", children: ["Experiment #", e.experiment_number, " is ", e.status, "; it has no evaluation yet."] });
    }
    return (_jsxs("div", { className: "space-y-6", children: [_jsxs("div", { className: "flex flex-wrap items-center gap-2", children: [_jsxs("h2", { className: "text-lg font-semibold text-slate-900", children: ["Experiment #", e.experiment_number, ": ", e.name] }), _jsx(VerdictPill, { verdict: e.verdict }), _jsx(Link, { to: `/experiments?experiment=${e.id}`, className: "text-xs text-navy-700 hover:underline", children: "Full evaluation and report" })] }), _jsxs("div", { className: "grid gap-6 xl:grid-cols-2", children: [_jsx(ProcessingTimeChart, { experiment: e }), _jsx(CostChart, { experiment: e })] }), _jsxs("section", { "aria-label": "Quality indicators", className: "space-y-2", children: [_jsx("h3", { className: "text-sm font-semibold text-slate-900", children: "Quality and compliance" }), _jsx(QualityIndicators, { experiment: e })] }), _jsxs("section", { "aria-label": "Compliance results", className: "space-y-2", children: [_jsx("h3", { className: "text-sm font-semibold text-slate-900", children: "Criteria" }), _jsx(CriteriaList, { experiment: e })] }), _jsxs("section", { "aria-label": "Run details", className: "text-sm", children: [_jsx("h3", { className: "mb-1 text-sm font-semibold text-slate-900", children: "Run details" }), _jsxs("ul", { className: "space-y-0.5 text-xs text-slate-600", children: [_jsxs("li", { children: ["Baseline:", " ", _jsxs(Link, { className: "text-navy-700 hover:underline", to: `/simulations?run=${e.baseline.id}`, children: ["run #", e.baseline.run_number] })] }), _jsxs("li", { children: ["Candidate (", MODE_NAMES[e.candidate_mode], ", ", e.tool_id, " ", e.tool_version, "):", " ", _jsxs(Link, { className: "text-navy-700 hover:underline", to: `/simulations?run=${e.candidate.id}`, children: ["run #", e.candidate.run_number] })] }), _jsxs("li", { children: ["Evaluation ", e.evaluation.evaluation_version, ", digest", " ", _jsx("span", { className: "font-mono", children: e.evaluation.evaluation_digest.slice(0, 16) })] })] })] }), _jsxs("section", { "aria-label": "Experiment conclusion", className: "rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-800", children: [_jsx("h3", { className: "mb-1 text-sm font-semibold text-slate-900", children: "Conclusion" }), e.evaluation.conclusion] })] }));
}
export function BenchmarkingPage() {
    const [params, setParams] = useSearchParams();
    const experiments = useExperiments(0, 50);
    const completed = (experiments.data?.items ?? []).filter((x) => x.status === "completed");
    const selected = params.get("experiment") ?? completed[0]?.id ?? null;
    return (_jsxs("div", { className: "space-y-6", children: [_jsx(PageHeader, { title: "Benchmarking", description: "Baseline versus AI-supported performance: processing time, cost, quality, compliance and conclusions.", actions: _jsx(SyntheticDataBadge, {}) }), _jsx(Panel, { title: "Tools compared", subtitle: "All completed experiments, by tool version and configuration", children: _jsx(Leaderboard, {}) }), _jsxs(Panel, { title: "Baseline vs. AI", actions: completed.length > 0 ? (_jsx("div", { className: "w-72", children: _jsx(Field, { label: "Experiment", children: (p) => (_jsx("select", { ...p, className: inputClass, value: selected ?? "", onChange: (ev) => setParams({ experiment: ev.target.value }), children: completed.map((x) => (_jsxs("option", { value: x.id, children: ["#", x.experiment_number, " ", x.name] }, x.id))) })) }) })) : undefined, children: [_jsx(ErrorMessage, { error: experiments.error }), selected ? _jsx(ExperimentBenchmark, { id: selected }, selected) : _jsx("p", { className: "text-sm text-slate-500", children: "No completed experiment to show." })] })] }));
}
