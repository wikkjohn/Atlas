import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { BarChart3, Download, FlaskConical, Plus, RotateCcw } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { SyntheticDataBadge } from "@/components/SyntheticDataBadge";
import { ComparisonTable, CostTable, CriteriaList, MODE_NAMES, VerdictPill, } from "@/features/experiments/ExperimentResults";
import { useAiTools } from "@/services/aiTools";
import { downloadReport, useCreateExperiment, useExperiment, useExperiments, useReEvaluate } from "@/services/experiments";
import { humanize } from "@/services/format";
import { useScenarios } from "@/services/simulations";
import { DEFAULT_COSTS, DEFAULT_THRESHOLDS, } from "@/types/experiments";
const PAGE = 10;
const STATUS_TONE = { running: "warn", completed: "good", failed: "bad" };
const COST_FIELDS = [
    { key: "reviewer_cost_per_minute", label: "Reviewer cost per minute", step: "0.01" },
    { key: "ai_cost_per_invocation", label: "AI cost per invocation", step: "0.001" },
    { key: "infrastructure_cost_per_run", label: "Infrastructure per workload", step: "0.01" },
    { key: "infrastructure_cost_per_case", label: "Infrastructure per case", step: "0.001" },
    { key: "exception_handling_cost", label: "Cost per workflow exception", step: "0.01" },
    { key: "manual_escalation_cost", label: "Cost per manual escalation", step: "0.01" },
    { key: "oversight_sample_rate", label: "Oversight: share of automated decisions re-checked", step: "0.01" },
    { key: "oversight_minutes_per_sample", label: "Oversight: minutes per re-check", step: "0.1" },
    { key: "false_approval_cost", label: "Risk cost per false approval", step: "1" },
    { key: "false_rejection_cost", label: "Risk cost per false rejection", step: "1" },
];
const THRESHOLD_FIELDS = [
    { key: "min_improvement", label: "Minimum improvement (time, labour or cost)", step: "0.01" },
    { key: "max_accuracy_drop", label: "Maximum accuracy drop", step: "0.001" },
    { key: "max_false_approval_rate", label: "Maximum false approval rate", step: "0.01" },
    { key: "max_false_rejection_rate", label: "Maximum false rejection rate", step: "0.01" },
    { key: "max_error_rate", label: "Maximum error rate", step: "0.01" },
    { key: "max_policy_violations", label: "Maximum policy violations", step: "1" },
    { key: "regression_tolerance", label: "Regression tolerance", step: "0.01" },
];
const RATE_KEYS = new Set([
    "oversight_sample_rate",
    "min_improvement",
    "max_accuracy_drop",
    "max_false_approval_rate",
    "max_false_rejection_rate",
    "max_error_rate",
    "regression_tolerance",
]);
// --- New experiment ---------------------------------------------------------------------------
function NewExperimentDialog({ onClose, onCreated }) {
    const tools = useAiTools();
    const scenarios = useScenarios();
    const create = useCreateExperiment();
    // Scenarios that support AI modes, latest version of each.
    const aiScenarios = Object.values(Object.fromEntries([...(scenarios.data ?? [])]
        .filter((s) => s.modes.length > 1)
        .sort((a, b) => a.version - b.version)
        .map((s) => [s.scenario_id, s])));
    const [scenarioId, setScenarioId] = useState("retail-onboarding");
    const scenario = aiScenarios.find((s) => s.scenario_id === scenarioId) ?? aiScenarios[0];
    const workflowId = scenario?.workflow_id ?? "WF-0001";
    const compatible = (tools.data?.items ?? []).filter((t) => t.status === "active" && t.compatible_workflows.includes(workflowId));
    const [name, setName] = useState("KYC assistant vs. baseline");
    const [toolId, setToolId] = useState("");
    const [mode, setMode] = useState("ai_automated");
    const [applications, setApplications] = useState("100");
    const [employees, setEmployees] = useState("25");
    const [seed, setSeed] = useState("42");
    const [costs, setCosts] = useState(Object.fromEntries(COST_FIELDS.map((f) => [f.key, String(DEFAULT_COSTS[f.key])])));
    const [thresholds, setThresholds] = useState(Object.fromEntries(THRESHOLD_FIELDS.map((f) => [f.key, String(DEFAULT_THRESHOLDS[f.key])])));
    const [currency, setCurrency] = useState(DEFAULT_COSTS.currency_label);
    const [submitted, setSubmitted] = useState(false);
    // Keyed by registered record so the chosen version is the one sent.
    const selectedTool = compatible.find((t) => t.id === toolId) ?? compatible[0];
    const tool = selectedTool?.tool_id ?? "";
    const numberError = (key, raw) => {
        const v = Number(raw);
        if (raw.trim() === "" || !Number.isFinite(v) || v < 0)
            return "A number ≥ 0.";
        if (RATE_KEYS.has(key) && v > 1)
            return "A share between 0 and 1.";
        if (key === "max_policy_violations" && !Number.isInteger(v))
            return "A whole number.";
        return null;
    };
    const errors = {
        name: name.trim().length >= 3 ? null : "At least 3 characters.",
        tool: tool ? null : `Register an active tool compatible with ${workflowId} first.`,
        applications: Number(applications) >= 1 && Number(applications) <= 10000 && Number.isInteger(Number(applications)) ? null : "1 – 10,000.",
        employees: Number(employees) >= 3 && Number(employees) <= 500 && Number.isInteger(Number(employees)) ? null : "3 – 500.",
        seed: Number.isInteger(Number(seed)) && Number(seed) >= 0 && seed.trim() !== "" ? null : "A whole number ≥ 0.",
        ...Object.fromEntries(COST_FIELDS.map((f) => [f.key, numberError(f.key, costs[f.key] ?? "")])),
        ...Object.fromEntries(THRESHOLD_FIELDS.map((f) => [f.key, numberError(f.key, thresholds[f.key] ?? "")])),
    };
    const valid = Object.values(errors).every((e) => e === null);
    const show = (key) => (submitted ? errors[key] : null);
    const submit = (event) => {
        event.preventDefault();
        setSubmitted(true);
        if (!valid)
            return;
        create.mutate({
            name: name.trim(),
            scenario_id: scenario?.scenario_id ?? "retail-onboarding",
            tool_id: tool,
            tool_version: selectedTool?.tool_version ?? null,
            candidate_mode: mode,
            profile: "custom",
            applications: Number(applications),
            employees: Number(employees),
            seed: Number(seed),
            costs: {
                ...DEFAULT_COSTS,
                ...Object.fromEntries(COST_FIELDS.map((f) => [f.key, Number(costs[f.key])])),
                currency_label: currency,
            },
            thresholds: Object.fromEntries(THRESHOLD_FIELDS.map((f) => [f.key, Number(thresholds[f.key])])),
        }, { onSuccess: (e) => onCreated(e.id) });
    };
    return (_jsxs(Modal, { title: "New experiment", onClose: onClose, wide: true, children: [_jsxs("form", { id: "new-experiment", "aria-label": "New experiment", onSubmit: submit, className: "space-y-4", children: [_jsx("p", { className: "text-xs text-slate-500", children: "Runs the baseline (A) and the candidate on the same seeded cases and staff, one after the other, then evaluates them against the cost assumptions and success thresholds below. Defaults are illustrative." }), _jsxs("div", { className: "grid gap-3 sm:grid-cols-2", children: [_jsx(Field, { label: "Name", error: show("name"), children: (p) => _jsx("input", { ...p, className: inputClass, value: name, onChange: (e) => setName(e.target.value) }) }), _jsx(Field, { label: "Scenario", hint: scenario ? `${scenario.workflow_id}: ${scenario.description}` : undefined, children: (p) => (_jsx("select", { ...p, className: inputClass, value: scenario?.scenario_id ?? "", onChange: (e) => {
                                        setScenarioId(e.target.value);
                                        setToolId("");
                                    }, children: aiScenarios.map((s) => (_jsx("option", { value: s.scenario_id, children: s.name }, s.scenario_id))) })) }), _jsx(Field, { label: "AI tool", error: show("tool"), children: (p) => (_jsx("select", { ...p, className: inputClass, value: selectedTool?.id ?? "", onChange: (e) => setToolId(e.target.value), children: compatible.map((t) => (_jsxs("option", { value: t.id, children: [t.tool_name, " ", t.tool_version] }, t.id))) })) }), _jsx(Field, { label: "Candidate configuration", children: (p) => (_jsxs("select", { ...p, className: inputClass, value: mode, onChange: (e) => setMode(e.target.value), children: [_jsx("option", { value: "ai_assisted", children: MODE_NAMES.ai_assisted }), _jsx("option", { value: "ai_automated", children: MODE_NAMES.ai_automated })] })) }), _jsxs("div", { className: "grid grid-cols-3 gap-2", children: [_jsx(Field, { label: "Cases", error: show("applications"), children: (p) => _jsx("input", { ...p, type: "number", className: inputClass, value: applications, onChange: (e) => setApplications(e.target.value) }) }), _jsx(Field, { label: "Staff", error: show("employees"), children: (p) => _jsx("input", { ...p, type: "number", className: inputClass, value: employees, onChange: (e) => setEmployees(e.target.value) }) }), _jsx(Field, { label: "Seed", error: show("seed"), children: (p) => _jsx("input", { ...p, inputMode: "numeric", className: inputClass, value: seed, onChange: (e) => setSeed(e.target.value) }) })] })] }), _jsxs("fieldset", { className: "rounded-lg border border-slate-200 p-3", children: [_jsx("legend", { className: "px-1 text-xs font-semibold text-slate-700", children: "Cost assumptions" }), _jsxs("div", { className: "grid gap-3 sm:grid-cols-2", children: [_jsx(Field, { label: "Currency label", children: (p) => _jsx("input", { ...p, className: inputClass, value: currency, onChange: (e) => setCurrency(e.target.value) }) }), COST_FIELDS.map((f) => (_jsx(Field, { label: f.label, error: show(f.key), children: (p) => (_jsx("input", { ...p, type: "number", step: f.step, className: inputClass, value: costs[f.key], onChange: (e) => setCosts({ ...costs, [f.key]: e.target.value }) })) }, f.key)))] })] }), _jsxs("details", { className: "rounded-lg border border-slate-200 p-3", children: [_jsx("summary", { className: "cursor-pointer text-xs font-semibold text-slate-700", children: "Success thresholds" }), _jsx("div", { className: "mt-3 grid gap-3 sm:grid-cols-2", children: THRESHOLD_FIELDS.map((f) => (_jsx(Field, { label: f.label, error: show(f.key), children: (p) => (_jsx("input", { ...p, type: "number", step: f.step, className: inputClass, value: thresholds[f.key], onChange: (e) => setThresholds({ ...thresholds, [f.key]: e.target.value }) })) }, f.key))) })] })] }), _jsx(ErrorMessage, { error: create.error, className: "mt-3" }), _jsxs("div", { className: "mt-4 flex justify-end gap-2", children: [_jsx(Button, { variant: "secondary", onClick: onClose, children: "Cancel" }), _jsxs(Button, { type: "submit", form: "new-experiment", disabled: create.isPending, children: [_jsx(FlaskConical, { "aria-hidden": true, className: "h-4 w-4" }), " Run experiment"] })] })] }));
}
// --- Detail ---------------------------------------------------------------------------------
function ExperimentView({ id }) {
    const experiment = useExperiment(id);
    const reEvaluate = useReEvaluate(id);
    const [downloadError, setDownloadError] = useState(null);
    const e = experiment.data;
    if (experiment.error)
        return _jsx(ErrorMessage, { error: experiment.error });
    if (!e)
        return _jsx("p", { className: "text-sm text-slate-500", children: "Loading\u2026" });
    const download = (format) => {
        setDownloadError(null);
        downloadReport(e.id, e.experiment_number, format).catch(setDownloadError);
    };
    return (_jsxs("div", { className: "space-y-6", children: [_jsxs("div", { className: "flex flex-wrap items-start justify-between gap-3", children: [_jsxs("div", { children: [_jsxs("div", { className: "flex flex-wrap items-center gap-2", children: [_jsxs("h2", { className: "text-lg font-semibold text-slate-900", children: ["Experiment #", e.experiment_number, ": ", e.name] }), _jsx(StatusPill, { tone: STATUS_TONE[e.status], label: humanize(e.status) }), _jsx(VerdictPill, { verdict: e.verdict })] }), _jsxs("p", { className: "mt-1 text-xs text-slate-500", children: [e.tool_id, " ", e.tool_version, " \u00B7 ", MODE_NAMES[e.candidate_mode], " vs. A \u2014 Baseline \u00B7 ", e.scenario_id, " v", e.scenario_version, " \u00B7 configuration ", _jsx("span", { className: "font-mono", children: e.configuration_hash.slice(0, 12) })] })] }), e.evaluation && (_jsxs("div", { className: "flex flex-wrap gap-2", children: [_jsxs(Button, { size: "sm", onClick: () => download("markdown"), children: [_jsx(Download, { "aria-hidden": true, className: "h-3.5 w-3.5" }), " Report (.md)"] }), _jsxs(Button, { size: "sm", variant: "secondary", onClick: () => download("json"), children: [_jsx(Download, { "aria-hidden": true, className: "h-3.5 w-3.5" }), " Data (.json)"] }), _jsxs(Button, { size: "sm", variant: "secondary", disabled: reEvaluate.isPending, onClick: () => reEvaluate.mutate(), children: [_jsx(RotateCcw, { "aria-hidden": true, className: "h-3.5 w-3.5" }), " Re-evaluate"] }), _jsxs(Link, { to: `/benchmarking?experiment=${e.id}`, className: "inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50", children: [_jsx(BarChart3, { "aria-hidden": true, className: "h-3.5 w-3.5" }), " Benchmarking"] })] }))] }), _jsx(ErrorMessage, { error: downloadError ?? reEvaluate.error }), reEvaluate.data && (_jsx("p", { role: "status", className: "text-xs text-slate-600", children: reEvaluate.data.matches
                    ? `Re-evaluated from the stored raw measurements: identical result (digest ${reEvaluate.data.recomputed_digest.slice(0, 16)}).`
                    : "Re-evaluation produced a different result — the evaluation is not reproducible." })), _jsx("section", { "aria-label": "Runs", className: "grid gap-3 text-sm sm:grid-cols-2", children: [["A — Baseline", e.baseline], [MODE_NAMES[e.candidate_mode], e.candidate]].map(([label, run]) => (_jsxs("div", { className: "rounded-lg border border-slate-200 p-3", children: [_jsxs("div", { className: "flex items-center justify-between", children: [_jsxs(Link, { className: "font-medium text-navy-700 hover:underline", to: `/simulations?run=${run.id}`, children: [label, " \u2014 run #", run.run_number] }), _jsx(StatusPill, { tone: STATUS_TONE[run.status === "completed" ? "completed" : run.status === "failed" ? "failed" : "running"], label: humanize(run.status) })] }), run.status === "running" && _jsxs("p", { className: "mt-1 text-xs text-slate-500", children: [run.percent_complete, "% of cases finished"] }), run.failure_reason && _jsx("p", { className: "mt-1 text-xs text-rose-700", children: run.failure_reason })] }, run.id))) }), e.status === "failed" && (_jsxs("div", { role: "alert", className: "rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800", children: ["The experiment could not be evaluated: ", e.failure_reason] })), e.evaluation && (_jsxs(_Fragment, { children: [_jsxs("section", { "aria-label": "Conclusion", className: "rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-800", children: [_jsx("h3", { className: "mb-1 text-sm font-semibold text-slate-900", children: "Conclusion" }), e.evaluation.conclusion] }), _jsxs("section", { "aria-label": "Criteria", className: "space-y-2", children: [_jsx("h3", { className: "text-sm font-semibold text-slate-900", children: "Success criteria" }), _jsx(CriteriaList, { experiment: e })] }), _jsxs("section", { "aria-label": "Comparison", className: "space-y-2", children: [_jsx("h3", { className: "text-sm font-semibold text-slate-900", children: "Baseline vs. candidate" }), _jsx(ComparisonTable, { experiment: e })] }), _jsxs("section", { "aria-label": "Costs", className: "space-y-2", children: [_jsx("h3", { className: "text-sm font-semibold text-slate-900", children: "Cost model" }), _jsx(CostTable, { experiment: e }), _jsxs("details", { className: "text-xs text-slate-600", children: [_jsx("summary", { className: "cursor-pointer font-medium", children: "Assumptions used" }), _jsx("ul", { className: "mt-2 grid gap-x-6 gap-y-0.5 sm:grid-cols-2", children: Object.keys(DEFAULT_COSTS).map((k) => (_jsxs("li", { children: [humanize(k), ": ", _jsx("span", { className: "font-mono", children: String(e.configuration.costs[k]) || "—" })] }, k))) })] })] }), _jsx("section", { "aria-label": "Raw measurements", className: "text-xs text-slate-600", children: _jsxs("details", { children: [_jsx("summary", { className: "cursor-pointer text-sm font-semibold text-slate-900", children: "Raw measurements" }), _jsx("p", { className: "mt-1", children: "Read from what the runs recorded, stored apart from the derived results above." }), _jsx("div", { className: "mt-2 grid gap-2 sm:grid-cols-2", children: e.measurements.map((m) => (_jsxs("pre", { className: "max-h-72 overflow-auto rounded-lg bg-slate-50 p-2 text-[11px]", children: [m.role, ": ", JSON.stringify(m.metrics, null, 2)] }, m.role))) })] }) }), _jsxs("section", { "aria-label": "Limitations", className: "text-xs text-slate-600", children: [_jsx("h3", { className: "mb-1 text-sm font-semibold text-slate-900", children: "Limitations" }), _jsx("ul", { className: "list-disc space-y-0.5 pl-5", children: e.evaluation.limitations.map((l) => (_jsx("li", { children: l }, l))) })] })] }))] }));
}
// --- Page ------------------------------------------------------------------------------------
export function ExperimentsPage() {
    const { can } = useAuth();
    const [params, setParams] = useSearchParams();
    const [offset, setOffset] = useState(0);
    const [creating, setCreating] = useState(false);
    const experiments = useExperiments(offset, PAGE);
    const selected = params.get("experiment") ?? experiments.data?.items[0]?.id ?? null;
    return (_jsxs("div", { children: [_jsx(PageHeader, { title: "Experiments", description: "Compare an AI-supported configuration with the baseline on identical synthetic workloads, under stated cost assumptions and success criteria.", actions: _jsxs(_Fragment, { children: [_jsx(SyntheticDataBadge, {}), can("experiments:run") && (_jsxs(Button, { onClick: () => setCreating(true), children: [_jsx(Plus, { "aria-hidden": true, className: "h-4 w-4" }), " New experiment"] }))] }) }), _jsxs("div", { className: "grid gap-6 lg:grid-cols-[20rem_1fr]", children: [_jsxs(Panel, { title: "Experiment registry", children: [_jsx(ErrorMessage, { error: experiments.error }), experiments.data?.items.length === 0 && _jsx("p", { className: "text-sm text-slate-500", children: "No experiments yet." }), _jsx("ul", { "aria-label": "Experiments", className: "divide-y divide-slate-100", children: (experiments.data?.items ?? []).map((x) => (_jsx("li", { children: _jsxs("button", { type: "button", onClick: () => setParams({ experiment: x.id }), "aria-current": x.id === selected ? "true" : undefined, className: `w-full px-2 py-2 text-left text-sm hover:bg-slate-50 ${x.id === selected ? "bg-slate-50" : ""}`, children: [_jsxs("div", { className: "flex items-center justify-between gap-2", children: [_jsxs("span", { className: "font-medium text-slate-900", children: ["#", x.experiment_number, " ", x.name] }), x.verdict ? _jsx(VerdictPill, { verdict: x.verdict }) : _jsx(StatusPill, { tone: STATUS_TONE[x.status], label: humanize(x.status), compact: true })] }), _jsxs("div", { className: "text-xs text-slate-500", children: [x.tool_id, " ", x.tool_version, " \u00B7 ", MODE_NAMES[x.candidate_mode]] })] }) }, x.id))) }), experiments.data && _jsx(Pagination, { total: experiments.data.total, limit: PAGE, offset: offset, onChange: setOffset })] }), _jsx(Panel, { title: "Experiment details", children: selected ? _jsx(ExperimentView, { id: selected }, selected) : _jsx("p", { className: "text-sm text-slate-500", children: "Run an experiment to see its evaluation." }) })] }), creating && (_jsx(NewExperimentDialog, { onClose: () => setCreating(false), onCreated: (id) => {
                    setCreating(false);
                    setParams({ experiment: id });
                } }))] }));
}
