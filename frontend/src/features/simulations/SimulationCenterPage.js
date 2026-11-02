import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { CheckCircle2, Dices, Play, RotateCcw, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { SyntheticDataBadge } from "@/components/SyntheticDataBadge";
import { formatMilliseconds, formatTimestamp } from "@/features/dashboard/format";
import { RunHistory } from "@/features/simulations/RunHistory";
import { useCountries } from "@/services/enterprise";
import { humanize } from "@/services/format";
import { useProfiles, useRerunSimulation, useScenarios, useSimulationCases, useSimulationRun, useSimulationRuns, useStartSimulation, } from "@/services/simulations";
import { useAiTools } from "@/services/aiTools";
import { MODE_LABELS, } from "@/types/simulations";
const RUNS_PAGE = 10;
const CASES_PAGE = 20;
const MAX_SEED = 2 ** 53 - 1;
const MAX_SHARDS = 8;
const SHARD_TONE = {
    queued: "neutral",
    running: "warn",
    completed: "good",
    failed: "bad",
};
const STATUS_TONE = {
    queued: "neutral",
    running: "warn",
    completed: "good",
    failed: "bad",
};
const percent = (value) => value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
const hours = (value) => {
    if (value === null || value === undefined)
        return "—";
    return value < 1 ? `${Math.round(value * 60)} min` : `${value.toFixed(1)} h`;
};
function randomSeed() {
    return Math.floor(Math.random() * 1_000_000_000);
}
// --- Start a run ----------------------------------------------------------------------------
function StartRunForm({ onStarted }) {
    const scenarios = useScenarios();
    const profiles = useProfiles();
    const start = useStartSimulation();
    const tools = useAiTools();
    const [scenarioKey, setScenarioKey] = useState("");
    const [mode, setMode] = useState("baseline");
    const [toolId, setToolId] = useState("");
    const [profile, setProfile] = useState("small");
    const [seed, setSeed] = useState("42");
    const [applications, setApplications] = useState("50");
    const [employees, setEmployees] = useState("10");
    const [shards, setShards] = useState("1");
    const [country, setCountry] = useState("");
    const activeCountries = useCountries({ status: "active" });
    const selected = profiles.data?.find((p) => p.profile_id === profile);
    const scenarioList = scenarios.data ?? [];
    // Default: the latest version of the first scenario.
    const chosen = scenarioList.find((s) => `${s.scenario_id}@${s.version}` === scenarioKey) ??
        [...scenarioList].sort((a, b) => b.version - a.version)[0];
    const modes = chosen?.modes ?? ["baseline"];
    const effectiveMode = modes.includes(mode) ? mode : "baseline";
    const compatibleTools = (tools.data?.items ?? []).filter((t) => t.status === "active" && chosen && t.compatible_workflows.includes(chosen.workflow_id));
    const selectedTool = compatibleTools.find((t) => t.id === toolId) ?? compatibleTools[0];
    const toolIdValue = selectedTool?.tool_id ?? "";
    const needsTool = effectiveMode !== "baseline";
    const minShards = selected?.min_shards ?? 1;
    const shardValue = Number(shards);
    const shardError = !Number.isInteger(shardValue) || shardValue < minShards || shardValue > MAX_SHARDS
        ? `A whole number from ${minShards} to ${MAX_SHARDS}.`
        : null;
    const seedValue = Number(seed);
    const seedError = seed.trim() === "" || !Number.isInteger(seedValue) || seedValue < 0 || seedValue > MAX_SEED
        ? "A whole number from 0 upwards."
        : null;
    const submit = (event) => {
        event.preventDefault();
        if (seedError || shardError || !chosen || (needsTool && !toolIdValue))
            return;
        start.mutate({
            scenario_id: chosen.scenario_id,
            scenario_version: chosen.version,
            mode: effectiveMode,
            tool_id: needsTool ? toolIdValue : null,
            tool_version: needsTool ? (selectedTool?.tool_version ?? null) : null,
            profile,
            seed: seedValue,
            applications: profile === "custom" ? Number(applications) : null,
            employees: profile === "custom" ? Number(employees) : null,
            shards: shardValue,
            country: country || null,
        }, { onSuccess: (run) => onStarted(run.id) });
    };
    return (_jsxs("form", { "aria-label": "Start a simulation", onSubmit: submit, className: "space-y-4", children: [_jsx(Field, { label: "Scenario", children: (props) => (_jsx("select", { ...props, className: inputClass, value: chosen ? `${chosen.scenario_id}@${chosen.version}` : "", onChange: (e) => setScenarioKey(e.target.value), children: scenarioList.map((s) => (_jsxs("option", { value: `${s.scenario_id}@${s.version}`, children: [s.name, " (v", s.version, ", ", s.workflow_id, " v", s.workflow_version, ")"] }, `${s.scenario_id}@${s.version}`))) })) }), modes.length > 1 && (_jsx(Field, { label: "Mode", hint: "All modes use the same cases and staff for a given seed.", children: (props) => (_jsx("select", { ...props, className: inputClass, value: effectiveMode, onChange: (e) => setMode(e.target.value), children: modes.map((m) => (_jsx("option", { value: m, children: MODE_LABELS[m] }, m))) })) })), needsTool && (_jsx(Field, { label: "AI tool", error: compatibleTools.length === 0 ? "No active tool is compatible with this workflow." : null, children: (props) => (_jsx("select", { ...props, className: inputClass, value: selectedTool?.id ?? "", onChange: (e) => setToolId(e.target.value), children: compatibleTools.map((t) => (_jsxs("option", { value: t.id, children: [t.tool_name, " ", t.tool_version] }, t.id))) })) })), _jsx(Field, { label: "Workload", hint: profile === "custom"
                    ? "Choose the number of cases and simulated staff."
                    : selected
                        ? `${selected.applications.toLocaleString()} applications · ${selected.customers.toLocaleString()} customers · ${selected.employees.toLocaleString()} staff${selected.runnable ? "" : ` — ${selected.note}`}`
                        : undefined, children: (props) => (_jsxs("select", { ...props, className: inputClass, value: profile, onChange: (e) => {
                        const next = e.target.value;
                        setProfile(next);
                        const needed = profiles.data?.find((p) => p.profile_id === next)?.min_shards ?? 1;
                        if (Number(shards) < needed)
                            setShards(String(needed));
                    }, children: [(profiles.data ?? []).map((p) => (_jsxs("option", { value: p.profile_id, disabled: !p.runnable, children: [p.name, p.runnable ? "" : " (target only — not runnable)"] }, p.profile_id))), _jsx("option", { value: "custom", children: "Custom size" })] })) }), profile === "custom" && (_jsxs("div", { className: "grid grid-cols-2 gap-3", children: [_jsx(Field, { label: "Cases", hint: "1 \u2013 10,000 applications, payments or loan requests", children: (props) => (_jsx("input", { ...props, type: "number", min: 1, max: 10000, className: inputClass, value: applications, onChange: (e) => setApplications(e.target.value) })) }), _jsx(Field, { label: "Simulated staff", hint: "3 \u2013 500", children: (props) => (_jsx("input", { ...props, type: "number", min: 3, max: 500, className: inputClass, value: employees, onChange: (e) => setEmployees(e.target.value) })) })] })), _jsx(Field, { label: "Parallel shards", hint: "Each shard runs in its own worker process with its share of the staff and its own queues. The same seed and shard count reproduce the same results.", error: shardError, children: (props) => (_jsx("input", { ...props, type: "number", min: minShards, max: MAX_SHARDS, className: inputClass, value: shards, onChange: (e) => setShards(e.target.value) })) }), _jsx(Field, { label: "Country", hint: "Only this country's customers, with staff from its subsidiary. Scenarios with country rules make their cases follow its rules.", children: (props) => (_jsxs("select", { ...props, className: inputClass, value: country, onChange: (e) => setCountry(e.target.value), children: [_jsx("option", { value: "", children: "Every active country" }), activeCountries.data?.items.map((c) => (_jsx("option", { value: c.iso_country_code, children: c.country_name }, c.id)))] })) }), _jsx(Field, { label: "Random seed", hint: "The same seed reproduces the same run.", error: seedError, children: (props) => (_jsxs("div", { className: "flex gap-2", children: [_jsx("input", { ...props, inputMode: "numeric", className: inputClass, value: seed, onChange: (e) => setSeed(e.target.value) }), _jsx(Button, { variant: "secondary", "aria-label": "Pick a random seed", onClick: () => setSeed(String(randomSeed())), children: _jsx(Dices, { "aria-hidden": true, className: "h-4 w-4" }) })] })) }), _jsxs(Button, { type: "submit", className: "w-full", disabled: start.isPending || Boolean(seedError) || Boolean(shardError) || (needsTool && !toolIdValue), children: [_jsx(Play, { "aria-hidden": true, className: "h-4 w-4" }), " Start run"] }), _jsx(ErrorMessage, { error: start.error })] }));
}
// --- Run detail -----------------------------------------------------------------------------
function Metric({ label, value, hint }) {
    return (_jsxs("div", { className: "rounded-lg border border-slate-200 bg-white p-3", children: [_jsx("dt", { className: "text-xs text-slate-500", children: label }), _jsx("dd", { className: "text-lg font-semibold text-slate-900", children: value }), hint && _jsx("dd", { className: "text-[11px] text-slate-500", children: hint })] }));
}
function Shards({ run }) {
    return (_jsx("table", { "aria-label": "Shards", className: "min-w-full text-xs", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: run.shard_progress.map((s) => (_jsxs("tr", { children: [_jsxs("td", { className: "py-1 pr-2 text-slate-700", children: ["Shard ", s.shard + 1] }), _jsx("td", { className: "py-1 pr-2", children: _jsx(StatusPill, { compact: true, tone: SHARD_TONE[s.status], label: humanize(s.status) }) }), _jsxs("td", { className: "py-1 pr-2 text-slate-600 tabular-nums", children: [s.cases_completed.toLocaleString(), " / ", s.cases_total.toLocaleString(), " cases"] }), _jsx("td", { className: "py-1 text-right text-slate-500 tabular-nums", children: s.wall_ms !== null ? formatMilliseconds(s.wall_ms) : (s.worker ?? "waiting for a worker") })] }, s.shard))) }) }));
}
function Progress({ run }) {
    const p = run.progress;
    return (_jsxs("div", { className: "space-y-2", children: [_jsx("div", { role: "progressbar", "aria-label": `Run #${run.run_number} progress`, "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": run.percent_complete, className: "h-2 overflow-hidden rounded-full bg-slate-100", children: _jsx("div", { className: "h-full bg-navy-700 transition-all", style: { width: `${run.percent_complete}%` } }) }), _jsxs("p", { className: "text-xs text-slate-600", children: [p.cases_completed ?? 0, " of ", p.cases_total ?? run.applications, " cases finished \u00B7 ", p.cases_started ?? 0, " ", "started \u00B7 ", p.events_processed ?? 0, " events \u00B7 simulated time ", formatTimestamp(p.simulated_now)] }), run.shard_progress.length > 0 && _jsx(Shards, { run: run })] }));
}
function Cases({ runId }) {
    const [offset, setOffset] = useState(0);
    const [mismatched, setMismatched] = useState(false);
    const cases = useSimulationCases(runId, { offset, limit: CASES_PAGE, mismatched }, true);
    return (_jsxs("div", { children: [_jsxs("label", { className: "mb-2 flex items-center gap-2 text-xs text-slate-600", children: [_jsx("input", { type: "checkbox", checked: mismatched, onChange: (e) => {
                            setMismatched(e.target.checked);
                            setOffset(0);
                        } }), "Only cases whose outcome differs from the ground truth"] }), _jsx(ErrorMessage, { error: cases.error }), _jsx("div", { className: "overflow-x-auto rounded-xl border border-slate-200", children: _jsxs("table", { "aria-label": "Case results", className: "min-w-full text-sm", children: [_jsx("thead", { className: "bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-3 py-2", children: "#" }), _jsx("th", { className: "px-3 py-2", children: "Case type" }), _jsx("th", { className: "px-3 py-2", children: "Expected" }), _jsx("th", { className: "px-3 py-2", children: "Outcome" }), _jsx("th", { className: "px-3 py-2", children: "Risk" }), _jsx("th", { className: "px-3 py-2", children: "AI advice" }), _jsx("th", { className: "px-3 py-2 text-right", children: "Reviews" }), _jsx("th", { className: "px-3 py-2 text-right", children: "Queue wait" }), _jsx("th", { className: "px-3 py-2 text-right", children: "Cycle time" })] }) }), _jsxs("tbody", { className: "divide-y divide-slate-100", children: [(cases.data?.items ?? []).map((c) => (_jsxs("tr", { children: [_jsx("td", { className: "px-3 py-2 font-mono text-xs text-slate-500", children: c.case_index }), _jsx("td", { className: "px-3 py-2", children: humanize(c.kind) }), _jsx("td", { className: "px-3 py-2", children: humanize(c.expected_outcome) }), _jsx("td", { className: "px-3 py-2", children: _jsxs("span", { className: "inline-flex items-center gap-1", children: [c.matches_ground_truth ? (_jsx(CheckCircle2, { "aria-label": "Matches ground truth", className: "h-3.5 w-3.5 text-emerald-600" })) : (_jsx(XCircle, { "aria-label": "Differs from ground truth", className: "h-3.5 w-3.5 text-rose-600" })), c.outcome ? humanize(c.outcome) : humanize(c.status)] }) }), _jsx("td", { className: "px-3 py-2", children: c.risk_rating ? humanize(c.risk_rating) : "—" }), _jsxs("td", { className: "px-3 py-2", children: [c.ai_recommendation
                                                    ? humanize(c.ai_recommendation)
                                                    : c.ai_status
                                                        ? humanize(c.ai_status)
                                                        : "—", c.automated && " · automated"] }), _jsx("td", { className: "px-3 py-2 text-right", children: c.manual_reviews }), _jsxs("td", { className: "px-3 py-2 text-right", children: [c.queue_wait_minutes, " min"] }), _jsx("td", { className: "px-3 py-2 text-right", children: hours(c.cycle_hours) })] }, c.case_index))), cases.data && cases.data.items.length === 0 && (_jsx("tr", { children: _jsx("td", { colSpan: 9, className: "px-3 py-6 text-center text-sm text-slate-500", children: "No cases match." }) }))] })] }) }), cases.data && (_jsx(Pagination, { total: cases.data.total, limit: CASES_PAGE, offset: offset, onChange: setOffset }))] }));
}
// How long the page polls for a queued archive or restore to finish.
const HISTORY_WAIT_MS = 10 * 60_000;
function RunDetail({ id, onSelect }) {
    const { can } = useAuth();
    // The history state when an archive or restore was queued, until it changes.
    const [waitingFrom, setWaitingFrom] = useState(null);
    const run = useSimulationRun(id, waitingFrom !== null);
    const rerun = useRerunSimulation();
    const historyState = run.data?.history_state;
    useEffect(() => {
        if (!waitingFrom)
            return;
        const timeout = Date.now() - waitingFrom.since > HISTORY_WAIT_MS;
        if (timeout || (historyState && historyState !== waitingFrom.state))
            setWaitingFrom(null);
    }, [historyState, waitingFrom, run.dataUpdatedAt]);
    if (run.error)
        return _jsx(ErrorMessage, { error: run.error });
    const r = run.data;
    if (!r)
        return _jsx("p", { className: "text-sm text-slate-500", children: "Loading\u2026" });
    const res = r.results;
    const running = r.status === "queued" || r.status === "running";
    return (_jsxs("div", { className: "space-y-5", children: [_jsxs("div", { className: "flex flex-wrap items-start justify-between gap-3", children: [_jsxs("div", { children: [_jsxs("div", { className: "flex flex-wrap items-center gap-2", children: [_jsxs("h2", { className: "text-lg font-semibold text-slate-900", children: ["Run #", r.run_number] }), _jsx(StatusPill, { tone: STATUS_TONE[r.status], label: humanize(r.status) })] }), _jsxs("p", { className: "mt-1 text-xs text-slate-500", children: [MODE_LABELS[r.mode], r.tool_id && ` with ${r.tool_id} ${r.tool_version}`, " \u00B7 ", r.scenario_id, " v", r.scenario_version, " \u00B7", " ", r.workflow_id, " v", r.workflow_version, " \u00B7 ", humanize(r.profile), " \u00B7", " ", r.applications.toLocaleString(), " applications \u00B7 ", r.employees.toLocaleString(), " staff", r.shards > 1 && ` · ${r.shards} shards`, " \u00B7 seed", " ", _jsx("span", { className: "font-mono", children: r.seed })] })] }), can("simulations:run") && !running && (_jsxs(Button, { variant: "secondary", size: "sm", disabled: rerun.isPending, onClick: () => rerun.mutate(r.id, { onSuccess: (next) => onSelect(next.id) }), children: [_jsx(RotateCcw, { "aria-hidden": true, className: "h-3.5 w-3.5" }), " Run again with this seed"] }))] }), _jsx(ErrorMessage, { error: rerun.error }), running && _jsx(Progress, { run: r }), !running && r.shard_progress.length > 0 && (_jsxs("details", { className: "text-xs text-slate-600", children: [_jsxs("summary", { className: "cursor-pointer", children: ["Ran as ", r.shards, " parallel shards"] }), _jsx(Shards, { run: r })] })), r.status === "failed" && (_jsxs("div", { role: "alert", className: "rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800", children: [_jsx("p", { className: "font-medium", children: "The run failed." }), _jsx("p", { className: "mt-1", children: r.failure_reason })] })), res && (_jsxs(_Fragment, { children: [_jsxs("dl", { className: "grid grid-cols-2 gap-3 text-sm sm:grid-cols-4", children: [_jsx(Metric, { label: "Cases completed", value: `${res.completed} / ${res.cases}` }), _jsx(Metric, { label: "Approved", value: res.outcomes.approved ?? 0 }), _jsx(Metric, { label: "Rejected", value: res.outcomes.rejected ?? 0 }), _jsx(Metric, { label: "Decision accuracy", value: percent(res.ground_truth.accuracy), hint: `${res.ground_truth.false_approvals} false approvals · ${res.ground_truth.false_rejections} false rejections` }), _jsx(Metric, { label: "Straight-through", value: percent(res.straight_through_rate), hint: "No manual review" }), _jsx(Metric, { label: "Manual reviews", value: res.manual_reviews, hint: `${hours(res.review_labor_hours)} of reviewer time` }), _jsx(Metric, { label: "Cycle time", value: hours(res.cycle_time_hours.p50), hint: `median · p95 ${hours(res.cycle_time_hours.p95)}` }), _jsx(Metric, { label: "Review queue wait", value: hours(res.review_queue_wait_hours.avg), hint: `average · p95 ${hours(res.review_queue_wait_hours.p95)} · ${res.overdue_tasks} overdue` })] }), res.ai && res.ai.mode !== "off" && (_jsxs("section", { "aria-label": "AI tool behaviour", className: "rounded-lg border border-slate-200 p-3 text-xs text-slate-600", children: [_jsx("h3", { className: "mb-1 text-sm font-semibold text-slate-900", children: "AI tool behaviour" }), _jsxs("p", { children: [res.ai.invocations, " invocations \u00B7 ", res.ai.failed_invocations, " failed or blocked (", Object.entries(res.ai.invocation_statuses)
                                        .map(([s, n]) => `${humanize(s)} ${n}`)
                                        .join(", ") || "none", ")"] }), _jsxs("p", { children: ["Recommendations:", " ", Object.entries(res.ai.recommendations)
                                        .map(([k, n]) => `${humanize(k)} ${n}`)
                                        .join(" · ") || "none", " ", "\u00B7 accuracy of approve/reject recommendations ", percent(res.ai.recommendation_accuracy)] }), _jsxs("p", { children: ["Approved by the policy engine without a person: ", res.ai.automated_approvals] })] })), _jsx("div", { className: "overflow-x-auto rounded-xl border border-slate-200", children: _jsxs("table", { "aria-label": "Outcomes by case type", className: "min-w-full text-sm", children: [_jsx("thead", { className: "bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-3 py-2", children: "Case type" }), _jsx("th", { className: "px-3 py-2 text-right", children: "Cases" }), _jsx("th", { className: "px-3 py-2 text-right", children: "Approved" }), _jsx("th", { className: "px-3 py-2 text-right", children: "Rejected" })] }) }), _jsx("tbody", { className: "divide-y divide-slate-100", children: Object.entries(res.by_kind).map(([kind, row]) => (_jsxs("tr", { children: [_jsx("td", { className: "px-3 py-2", children: humanize(kind) }), _jsx("td", { className: "px-3 py-2 text-right", children: row.cases }), _jsx("td", { className: "px-3 py-2 text-right", children: row.approved }), _jsx("td", { className: "px-3 py-2 text-right", children: row.rejected })] }, kind))) })] }) }), _jsxs("section", { "aria-label": "Execution and reproducibility", className: "grid gap-3 text-xs text-slate-600 sm:grid-cols-2", children: [_jsxs("div", { className: "rounded-lg border border-slate-200 p-3", children: [_jsx("h3", { className: "mb-1 text-sm font-semibold text-slate-900", children: "Execution" }), _jsxs("p", { children: [res.execution.events_processed.toLocaleString(), " simulated events \u00B7", " ", res.execution.workflow_steps_completed.toLocaleString(), " workflow steps"] }), _jsxs("p", { children: ["Wall time ", formatMilliseconds(res.execution.wall_ms), " \u00B7 ", res.execution.cases_per_second ?? "—", " cases/s"] }), _jsxs("p", { children: ["Simulated ", formatTimestamp(r.simulated_start), " \u2192 ", formatTimestamp(r.simulated_end), " (", hours(res.simulated_hours), ")"] })] }), _jsxs("div", { className: "rounded-lg border border-slate-200 p-3", children: [_jsx("h3", { className: "mb-1 text-sm font-semibold text-slate-900", children: "Reproducibility" }), _jsxs("p", { children: ["Software ", r.software_version, " \u00B7 config ", _jsx("span", { className: "font-mono", children: r.config_hash.slice(0, 12) })] }), _jsxs("p", { children: ["Result digest ", _jsx("span", { className: "font-mono", children: r.result_digest?.slice(0, 16) })] }), r.reproductions.length === 0 ? (_jsx("p", { className: "mt-1", children: "No other run with this scenario, seed, configuration and software yet." })) : (_jsx("ul", { className: "mt-1 space-y-0.5", children: r.reproductions.map((p) => (_jsxs("li", { className: "flex items-center gap-1", children: [p.matches ? (_jsx(CheckCircle2, { "aria-hidden": true, className: "h-3.5 w-3.5 text-emerald-600" })) : (_jsx(XCircle, { "aria-hidden": true, className: "h-3.5 w-3.5 text-rose-600" })), "Run #", p.run_number, ": ", p.matches ? "identical results" : "results differ"] }, p.id))) }))] })] }), _jsx(RunHistory, { run: r, waiting: waitingFrom !== null, onQueued: () => setWaitingFrom({ state: r.history_state, since: Date.now() }) }), _jsx(Cases, { runId: r.id })] }))] }));
}
// --- Page -----------------------------------------------------------------------------------
export function SimulationCenterPage() {
    const { can } = useAuth();
    const [params, setParams] = useSearchParams();
    const selected = params.get("run");
    const [offset, setOffset] = useState(0);
    const runs = useSimulationRuns(offset, RUNS_PAGE);
    const select = (id) => setParams({ run: id });
    return (_jsxs("div", { children: [_jsx(PageHeader, { title: "Simulation Center", description: "Run seeded, reproducible workloads of synthetic customers and staff through the real workflow engine on simulated time.", actions: _jsx(SyntheticDataBadge, {}) }), _jsxs("div", { className: "grid gap-6 lg:grid-cols-[20rem_1fr]", children: [_jsxs("div", { className: "space-y-6", children: [can("simulations:run") ? (_jsx(Panel, { title: "New run", subtitle: "One run executes at a time.", children: _jsx(StartRunForm, { onStarted: select }) })) : (_jsx(Panel, { title: "New run", children: _jsx("p", { className: "text-sm text-slate-500", children: "Your role can review runs but not start them." }) })), _jsxs(Panel, { title: "Runs", children: [_jsx(ErrorMessage, { error: runs.error }), runs.data && runs.data.items.length === 0 && (_jsx("p", { className: "text-sm text-slate-500", children: "No simulation has been run yet." })), _jsx("ul", { "aria-label": "Simulation runs", className: "divide-y divide-slate-100", children: (runs.data?.items ?? []).map((run) => (_jsx("li", { children: _jsxs("button", { type: "button", onClick: () => select(run.id), "aria-current": run.id === selected ? "true" : undefined, className: `w-full px-2 py-2 text-left text-sm hover:bg-slate-50 ${run.id === selected ? "bg-slate-50" : ""}`, children: [_jsxs("div", { className: "flex items-center justify-between gap-2", children: [_jsxs("span", { className: "font-medium text-slate-900", children: ["Run #", run.run_number] }), _jsx(StatusPill, { tone: STATUS_TONE[run.status], label: humanize(run.status) })] }), _jsxs("div", { className: "text-xs text-slate-500", children: [MODE_LABELS[run.mode], " \u00B7 ", run.applications.toLocaleString(), " apps \u00B7 seed ", run.seed, run.status === "running" && ` · ${run.percent_complete}%`] })] }) }, run.id))) }), runs.data && (_jsx(Pagination, { total: runs.data.total, limit: RUNS_PAGE, offset: offset, onChange: setOffset }))] })] }), _jsx(Panel, { title: "Run details", children: selected ? (_jsx(RunDetail, { id: selected, onSelect: select })) : (_jsx("p", { className: "text-sm text-slate-500", children: "Select a run, or start one, to see its progress and outcomes." })) })] })] }));
}
