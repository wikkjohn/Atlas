import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { AlertTriangle, CheckCircle2, Download, Play, Search, Upload, XCircle } from "lucide-react";
import { Fragment, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { StatusPill } from "@/components/StatusPill";
import { formatMilliseconds as formatDuration, formatTimestamp } from "@/features/dashboard/format";
import { EffectBadge, ImportDefinitionDialog, StartFromSchemaDialog } from "@/features/workflows/DefinitionDialogs";
import { CatalogueFilterBar, Classification, VersionsPanel } from "@/features/workflows/CatalogueParts";
import { DefinitionEditor } from "@/features/workflows/DefinitionEditor";
import { StartLoanDialog, StartPaymentDialog } from "@/features/workflows/StartDialogs";
import { TemplatesTab } from "@/features/workflows/TemplatesTab";
import { TestsPanel } from "@/features/workflows/TestsPanel";
import { WorkflowGraph } from "@/features/workflows/WorkflowGraph";
import { newIdempotencyKey } from "@/services/api";
import { useCountries } from "@/services/enterprise";
import { humanize } from "@/services/format";
import { CATALOGUE_LIMIT, exportDefinition, useCatalogue, syntheticDocumentNumber, useCompleteTask, useExecution, useExecutionHistory, useExecutions, useLibraryHandlers, useWorkflowGraph, useSignal, useStartExecution, useTasks, useWorkflowDefinition, useWorkflowMetrics, } from "@/services/workflows";
const PAGE_SIZE = 25;
const EXECUTION_TONE = {
    running: "warn",
    waiting: "warn",
    completed: "good",
    failed: "bad",
    cancelled: "neutral",
};
const NEGATIVE_OUTCOMES = new Set(["rejected", "declined", "failed", "cancelled", "written_off"]);
const RUN_TONE = {
    pending: "warn",
    waiting: "warn",
    completed: "good",
    failed: "bad",
    cancelled: "neutral",
};
function TypeTag({ type }) {
    return (_jsx("span", { className: "rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600", children: type }));
}
// --- Catalogue ------------------------------------------------------------------------------
function SourceBadges({ workflow }) {
    return (_jsxs(_Fragment, { children: [workflow.source === "stored" && !workflow.template_id && (_jsx("span", { className: "rounded bg-sky-50 px-1.5 py-0.5 text-[10px] font-medium text-sky-800", children: "Stored" })), workflow.template_id && (_jsx("span", { className: "rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] font-medium text-indigo-800", children: workflow.template_id })), workflow.status === "retired" && (_jsx("span", { className: "rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600", children: "Retired" })), workflow.status === "draft" && (_jsx("span", { className: "rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600", children: "Draft" })), (workflow.status === "in_review" || workflow.in_review) && (_jsx("span", { className: "rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-800", children: "In review" }))] }));
}
function download(name, data) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    link.click();
    URL.revokeObjectURL(url);
}
function DefinitionActions({ workflowId, version, latest, source, generated, }) {
    const { can } = useAuth();
    const [editing, setEditing] = useState(false);
    const [exportError, setExportError] = useState(null);
    const onExport = () => exportDefinition(workflowId, version).then((document) => download(`${workflowId}-v${version}.json`, document), setExportError);
    return (_jsxs("div", { className: "flex flex-col items-end gap-1.5", children: [_jsxs("div", { className: "flex gap-1.5", children: [_jsxs(Button, { size: "sm", variant: "secondary", onClick: () => void onExport(), children: [_jsx(Download, { "aria-hidden": true, className: "h-3.5 w-3.5" }), " Export JSON"] }), source === "stored" && !generated && can("workflows:define") && (_jsxs(Button, { size: "sm", variant: "secondary", onClick: () => setEditing(true), children: ["Edit as v", latest + 1] }))] }), _jsx(ErrorMessage, { error: exportError }), editing && _jsx(DefinitionEditor, { workflowId: workflowId, fromVersion: latest, onClose: () => setEditing(false), onSaved: () => setEditing(false) })] }));
}
function DefinitionView({ id }) {
    const [version, setVersion] = useState(undefined);
    const definition = useWorkflowDefinition(id, version);
    const metrics = useWorkflowMetrics(id);
    const [view, setView] = useState("steps");
    const graph = useWorkflowGraph(id, definition.data?.version, view === "diagram");
    const handlers = useLibraryHandlers(definition.data?.source === "stored");
    const effectOf = (handler) => handlers.data?.find((h) => h.name === handler)?.effect;
    const d = definition.data;
    const m = metrics.data;
    if (definition.error)
        return _jsx(ErrorMessage, { error: definition.error });
    if (!d)
        return _jsx("p", { className: "text-sm text-slate-500", children: "Loading\u2026" });
    const metricFor = (stepId) => m?.steps.find((s) => s.step_id === stepId);
    return (_jsxs("div", { className: "space-y-5", children: [_jsxs("div", { className: "flex flex-wrap items-start justify-between gap-3", children: [_jsxs("div", { children: [_jsxs("div", { className: "flex flex-wrap items-center gap-2", children: [_jsx("span", { className: "font-mono text-sm text-slate-500", children: d.workflow_id }), _jsx("h2", { className: "text-lg font-semibold text-slate-900", children: d.name }), _jsxs("span", { className: "text-xs text-slate-500", children: ["v", d.version] }), _jsx(SourceBadges, { workflow: d })] }), _jsx("p", { className: "mt-1 text-sm text-slate-600", children: d.description }), _jsxs("p", { className: "mt-1 text-xs text-slate-500", children: ["Owner: ", d.business_owner, " \u00B7 Trigger: ", d.trigger_type, " \u00B7", " ", d.origin
                                        ? `Generated from ${d.origin.template_id} v${d.origin.template_version}`
                                        : d.source === "stored"
                                            ? "Stored definition (imported as data)"
                                            : "Registered in code"] })] }), _jsx(DefinitionActions, { workflowId: d.workflow_id, version: d.version, latest: Math.max(d.version, ...d.versions), source: d.source, generated: Boolean(d.origin) })] }), _jsx(Classification, { workflow: d }), m && (_jsx("dl", { className: "grid grid-cols-2 gap-3 text-sm sm:grid-cols-4", children: [
                    ["Executions", Object.values(m.executions).reduce((a, b) => a + b, 0)],
                    ["Approved", m.outcomes.approved ?? 0],
                    ["Rejected", m.outcomes.rejected ?? 0],
                    ["Avg duration", formatDuration(m.avg_execution_ms)],
                ].map(([label, value]) => (_jsxs("div", { className: "rounded-lg border border-slate-200 bg-white p-3", children: [_jsx("dt", { className: "text-xs text-slate-500", children: label }), _jsx("dd", { className: "text-lg font-semibold text-slate-900", children: value })] }, label))) })), d.source === "stored" && _jsx(VersionsPanel, { workflowId: d.workflow_id, shown: d.version, onShow: setVersion }), d.source === "stored" && _jsx(TestsPanel, { workflowId: d.workflow_id, version: d.version }), _jsx("div", { role: "tablist", "aria-label": "Definition views", className: "flex gap-1", children: ["steps", "diagram"].map((v) => (_jsx("button", { role: "tab", type: "button", "aria-selected": view === v, onClick: () => setView(v), className: `rounded-md px-2.5 py-1 text-xs font-medium ${view === v ? "bg-navy-900 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`, children: v === "steps" ? "Steps" : "Diagram" }, v))) }), view === "diagram" && (_jsxs(_Fragment, { children: [_jsx(ErrorMessage, { error: graph.error }), graph.data ? _jsx(WorkflowGraph, { graph: graph.data }) : _jsx("p", { className: "text-sm text-slate-500", children: "Loading\u2026" })] })), _jsx("div", { className: `overflow-x-auto rounded-xl border border-slate-200 bg-white ${view === "diagram" ? "hidden" : ""}`, children: _jsxs("table", { "aria-label": "Process steps", className: "min-w-full text-sm", children: [_jsx("thead", { className: "bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-4 py-2", children: "Step" }), _jsx("th", { className: "px-4 py-2", children: "Routes to" }), _jsx("th", { className: "px-4 py-2", children: "Policy" }), _jsx("th", { className: "px-4 py-2 text-right", children: "Runs" }), _jsx("th", { className: "px-4 py-2 text-right", children: "p95" }), _jsx("th", { className: "px-4 py-2 text-right", children: "Failed" })] }) }), _jsx("tbody", { className: "divide-y divide-slate-100", children: d.steps.map((step) => {
                                const metric = metricFor(step.id);
                                const routes = [
                                    ...(step.transitions ?? []).map((t) => t.to),
                                    ...(step.next ? [step.next] : []),
                                    ...(step.branches ?? []),
                                ];
                                const policy = step.approval
                                    ? `Needs ${step.approval.permissions.join(" + ")}; not ${step.approval.distinct_from.join(", ")}`
                                    : step.signal
                                        ? `Waits for “${step.signal}”`
                                        : step.handler
                                            ? `Handler ${step.handler}${step.retry ? ` · retry ×${step.retry.max_attempts}` : ""}`
                                            : "";
                                const bottleneck = m?.bottleneck_step === step.id;
                                return (_jsxs("tr", { className: bottleneck ? "bg-amber-50" : undefined, children: [_jsxs("td", { className: "px-4 py-2", children: [_jsxs("div", { className: "flex items-center gap-2", children: [_jsx(TypeTag, { type: step.type }), _jsx("span", { className: "font-medium text-slate-900", children: step.name }), d.source === "stored" && effectOf(step.handler) && _jsx(EffectBadge, { effect: effectOf(step.handler) }), bottleneck && (_jsxs("span", { className: "inline-flex items-center gap-1 text-[11px] font-medium text-amber-700", children: [_jsx(AlertTriangle, { "aria-hidden": true, className: "h-3 w-3" }), " Bottleneck"] }))] }), _jsx("div", { className: "font-mono text-[11px] text-slate-400", children: step.id })] }), _jsx("td", { className: "px-4 py-2 font-mono text-[11px] text-slate-600", children: routes.join(", ") || "—" }), _jsxs("td", { className: "px-4 py-2 text-xs text-slate-600", children: [policy, step.timeout && (_jsxs("div", { className: "text-slate-400", children: ["Timeout ", formatDuration(step.timeout.after_seconds * 1000), " \u2192 ", step.timeout.action] }))] }), _jsx("td", { className: "px-4 py-2 text-right text-slate-700", children: metric?.runs ?? 0 }), _jsx("td", { className: "px-4 py-2 text-right whitespace-nowrap text-slate-700", children: formatDuration(metric?.p95_ms) }), _jsx("td", { className: `px-4 py-2 text-right ${metric?.failed ? "font-medium text-rose-700" : "text-slate-500"}`, children: metric?.failed ?? 0 })] }, step.id));
                            }) })] }) })] }));
}
function StartApplicationDialog({ onClose, onStarted }) {
    const start = useStartExecution("WF-0001");
    const countries = useCountries({ operational_status: "active" });
    const [key] = useState(newIdempotencyKey);
    const [form, setForm] = useState({
        applicant_name: "",
        date_of_birth: "",
        country_code: "",
        account_type: "current",
        politically_exposed: false,
        expected_monthly_deposits: "0",
        passport: true,
        proof_of_address: true,
    });
    const set = (k, v) => setForm({ ...form, [k]: v });
    const onSubmit = (event) => {
        event.preventDefault();
        const documents = [
            ...(form.passport
                ? [
                    {
                        document_type: "passport",
                        document_number: syntheticDocumentNumber("passport"),
                        name_on_document: form.applicant_name,
                        date_of_birth: form.date_of_birth,
                        expiry_date: `${new Date().getFullYear() + 5}-01-01`,
                    },
                ]
                : []),
            ...(form.proof_of_address
                ? [
                    {
                        document_type: "proof_of_address",
                        document_number: syntheticDocumentNumber("proof_of_address"),
                        name_on_document: form.applicant_name,
                    },
                ]
                : []),
        ];
        start.mutate({
            idempotencyKey: key,
            input: {
                applicant_name: form.applicant_name,
                date_of_birth: form.date_of_birth,
                country_code: form.country_code,
                account_type: form.account_type,
                politically_exposed: form.politically_exposed,
                expected_monthly_deposits: Number(form.expected_monthly_deposits) || 0,
                documents,
            },
        }, { onSuccess: (execution) => onStarted(execution.id) });
    };
    return (_jsxs(Modal, { wide: true, title: "New retail account application (WF-0001)", onClose: onClose, footer: _jsxs(_Fragment, { children: [_jsx(Button, { variant: "secondary", onClick: onClose, children: "Cancel" }), _jsx(Button, { type: "submit", form: "wf0001-start", disabled: start.isPending, children: start.isPending ? "Submitting…" : "Submit application" })] }), children: [_jsxs("form", { id: "wf0001-start", onSubmit: onSubmit, className: "grid grid-cols-1 gap-4 sm:grid-cols-2", children: [_jsx(Field, { label: "Applicant name", children: (p) => _jsx("input", { ...p, className: inputClass, required: true, value: form.applicant_name, onChange: (e) => set("applicant_name", e.target.value) }) }), _jsx(Field, { label: "Date of birth", children: (p) => _jsx("input", { ...p, type: "date", className: inputClass, required: true, value: form.date_of_birth, onChange: (e) => set("date_of_birth", e.target.value) }) }), _jsx(Field, { label: "Country", children: (p) => (_jsxs("select", { ...p, className: inputClass, required: true, value: form.country_code, onChange: (e) => set("country_code", e.target.value), children: [_jsx("option", { value: "", children: "Select\u2026" }), countries.data?.items.map((c) => (_jsx("option", { value: c.iso_country_code, children: c.country_name }, c.id)))] })) }), _jsx(Field, { label: "Account type", children: (p) => (_jsxs("select", { ...p, className: inputClass, value: form.account_type, onChange: (e) => set("account_type", e.target.value), children: [_jsx("option", { value: "current", children: "Current" }), _jsx("option", { value: "savings", children: "Savings" })] })) }), _jsx(Field, { label: "Expected monthly deposits", hint: "Whole units of the local currency.", children: (p) => (_jsx("input", { ...p, type: "number", min: 0, className: inputClass, value: form.expected_monthly_deposits, onChange: (e) => set("expected_monthly_deposits", e.target.value) })) }), _jsxs("fieldset", { className: "space-y-1.5 text-sm", children: [_jsx("legend", { className: "text-xs font-medium text-slate-700", children: "Declarations and documents" }), [
                                ["politically_exposed", "Politically exposed person"],
                                ["passport", "Passport (synthetic)"],
                                ["proof_of_address", "Proof of address (synthetic)"],
                            ].map(([k, label]) => (_jsxs("label", { className: "flex items-center gap-2", children: [_jsx("input", { type: "checkbox", checked: form[k], onChange: (e) => set(k, e.target.checked) }), label] }, k)))] })] }), _jsx("p", { className: "mt-3 text-xs text-slate-500", children: "Synthetic document numbers are generated with valid check digits. Leave a document out to see the workflow wait for it." }), _jsx(ErrorMessage, { error: start.error, className: "mt-4" })] }));
}
const START_LABELS = {
    "WF-0001": "Start an application",
    "WF-0002": "Start a payment",
    "WF-0003": "Start a loan application",
};
const START_DIALOGS = {
    "WF-0001": StartApplicationDialog,
    "WF-0002": StartPaymentDialog,
    "WF-0003": StartLoanDialog,
};
function CatalogueTab({ onStarted, initial }) {
    const { can } = useAuth();
    const [filters, setFilters] = useState({ q: initial ?? undefined });
    const catalogue = useCatalogue(filters);
    const found = catalogue.data?.items;
    const [selected, setSelected] = useState(initial);
    const [starting, setStarting] = useState(false);
    const [importing, setImporting] = useState(false);
    const current = selected ?? found?.[0]?.workflow_id ?? null;
    const summary = found?.find((w) => w.workflow_id === current);
    const storedStartable = summary?.source === "stored" && summary.status === "active";
    const definition = useWorkflowDefinition(storedStartable ? current : null);
    return (_jsxs("div", { className: "grid grid-cols-1 gap-6 lg:grid-cols-[300px_1fr]", children: [_jsxs("div", { className: "space-y-3", children: [_jsxs("div", { className: "relative", children: [_jsx(Search, { "aria-hidden": true, className: "pointer-events-none absolute top-2 left-2.5 h-4 w-4 text-slate-400" }), _jsx("input", { "aria-label": "Search workflows", placeholder: "Search workflows", className: "w-full rounded-lg border border-slate-200 bg-white py-1.5 pr-3 pl-8 text-sm", value: filters.q ?? "", onChange: (e) => setFilters({ ...filters, q: e.target.value || undefined }) })] }), _jsx(CatalogueFilterBar, { filters: filters, facets: catalogue.data?.facets, onChange: setFilters }), _jsx(ErrorMessage, { error: catalogue.error }), catalogue.data && (_jsxs("p", { role: "status", className: "text-xs text-slate-500", children: [catalogue.data.total, " workflow", catalogue.data.total === 1 ? "" : "s"] })), _jsxs("ul", { "aria-label": "Workflows", className: "space-y-2", children: [found?.map((w) => (_jsx("li", { children: _jsxs("button", { type: "button", onClick: () => setSelected(w.workflow_id), className: `w-full rounded-lg border p-3 text-left ${current === w.workflow_id ? "border-navy-700 bg-navy-900/5" : "border-slate-200 bg-white hover:bg-slate-50"}`, children: [_jsxs("div", { className: "flex items-center gap-1.5 font-mono text-[11px] text-slate-500", children: [w.workflow_id, " ", _jsx(SourceBadges, { workflow: w })] }), _jsx("div", { className: "text-sm font-medium text-slate-900", children: w.name }), _jsxs("div", { className: "text-xs text-slate-500", children: ["v", w.version, " \u00B7 ", w.step_count, " steps", w.department && ` · ${w.department}`, w.countries?.length ? ` · ${w.countries.length > 3 ? `${w.countries.length} countries` : w.countries.join(", ")}` : ""] })] }) }, w.workflow_id))), found?.length === 0 && _jsx("li", { className: "text-sm text-slate-500", children: "No workflows match." })] }), catalogue.data && catalogue.data.total > catalogue.data.items.length && (_jsxs("p", { className: "text-xs text-slate-500", children: ["Showing the first ", CATALOGUE_LIMIT, "; search or filter to find the others."] })), current && (START_LABELS[current] || storedStartable) && can("workflows:start") && (_jsxs(Button, { className: "w-full", onClick: () => setStarting(true), children: [_jsx(Play, { "aria-hidden": true, className: "h-4 w-4" }), " ", START_LABELS[current] ?? "Start a case"] })), can("workflows:define") && (_jsxs(Button, { className: "w-full", variant: "secondary", onClick: () => setImporting(true), children: [_jsx(Upload, { "aria-hidden": true, className: "h-4 w-4" }), " Import definition"] }))] }), importing && (_jsx(ImportDefinitionDialog, { startFrom: summary?.source === "stored" ? summary.workflow_id : null, onClose: () => setImporting(false), onImported: (workflowId) => {
                    setImporting(false);
                    setSelected(workflowId);
                } })), starting && storedStartable && current && definition.data && (_jsx(StartFromSchemaDialog, { workflowId: current, name: definition.data.name, schema: definition.data.input_schema, onClose: () => setStarting(false), onStarted: (id) => {
                    setStarting(false);
                    onStarted(id);
                } })), _jsx("div", { children: current && _jsx(DefinitionView, { id: current }, current) }), starting && current && (() => {
                const Dialog = START_DIALOGS[current];
                return Dialog ? (_jsx(Dialog, { onClose: () => setStarting(false), onStarted: (id) => {
                        setStarting(false);
                        onStarted(id);
                    } })) : null;
            })()] }));
}
// --- Executions ------------------------------------------------------------------------------
function DocumentsSignal({ execution }) {
    const signal = useSignal(execution.id);
    const name = String(execution.context.input?.applicant_name ?? "");
    return (_jsxs("div", { className: "rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm", children: [_jsx("p", { className: "text-amber-900", children: "This case is waiting for documents." }), _jsx(Button, { size: "sm", className: "mt-2", disabled: signal.isPending, onClick: () => signal.mutate({
                    signal: "documents_submitted",
                    payload: {
                        documents: [
                            { document_type: "proof_of_address", document_number: syntheticDocumentNumber("proof_of_address"), name_on_document: name },
                            {
                                document_type: "passport",
                                document_number: syntheticDocumentNumber("passport"),
                                name_on_document: name,
                                date_of_birth: execution.context.input?.date_of_birth,
                                expiry_date: `${new Date().getFullYear() + 5}-01-01`,
                            },
                        ],
                    },
                }), children: "Submit synthetic documents" }), _jsx(ErrorMessage, { error: signal.error, className: "mt-2" })] }));
}
function ExecutionView({ id, onClose }) {
    const { can } = useAuth();
    const execution = useExecution(id);
    const history = useExecutionHistory(id);
    const [showContext, setShowContext] = useState(false);
    const e = execution.data;
    return (_jsxs(Modal, { wide: true, title: "Workflow execution", onClose: onClose, children: [_jsx(ErrorMessage, { error: execution.error }), e && (_jsxs("div", { className: "space-y-4", children: [_jsxs("div", { className: "flex flex-wrap items-start justify-between gap-3", children: [_jsxs("div", { children: [_jsxs("h3", { className: "text-base font-semibold text-slate-900", children: [e.workflow_id, " \u00B7 ", e.subject ?? "—"] }), _jsxs("p", { className: "font-mono text-[11px] text-slate-500", children: [e.id, " \u00B7 started ", formatTimestamp(e.started_at), " by ", e.initiated_by_username] })] }), _jsxs("div", { className: "flex items-center gap-2", children: [_jsx(StatusPill, { tone: EXECUTION_TONE[e.status], label: humanize(e.status) }), e.outcome && _jsx(StatusPill, { tone: NEGATIVE_OUTCOMES.has(e.outcome) ? "bad" : "good", label: humanize(e.outcome) })] })] }), e.error && (_jsxs("div", { role: "alert", className: "rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800", children: ["Failed at ", _jsx("strong", { children: String(e.error.step ?? "?") }), ": ", String(e.error.message ?? e.error.code ?? "")] })), e.current_steps.includes("await_documents") && can("workflows:start") && _jsx(DocumentsSignal, { execution: e }), _jsxs("table", { "aria-label": "Step runs", className: "min-w-full text-sm", children: [_jsx("thead", { className: "text-left text-xs text-slate-500", children: _jsxs("tr", { children: [_jsx("th", { className: "py-1", children: "#" }), _jsx("th", { className: "py-1", children: "Step" }), _jsx("th", { className: "py-1", children: "Status" }), _jsx("th", { className: "py-1", children: "By" }), _jsx("th", { className: "py-1 text-right", children: "Duration" })] }) }), _jsx("tbody", { className: "divide-y divide-slate-100", children: e.steps.map((s) => (_jsxs(Fragment, { children: [_jsxs("tr", { children: [_jsx("td", { className: "py-1.5 font-mono text-[11px] text-slate-400", children: s.sequence }), _jsxs("td", { className: "py-1.5", children: [_jsx("span", { className: "font-medium text-slate-800", children: s.step_name }), " ", _jsx(TypeTag, { type: s.step_type }), s.branch && _jsxs("span", { className: "ml-1 text-[11px] text-slate-400", children: ["branch ", s.branch] }), s.attempt > 1 && _jsxs("span", { className: "ml-1 text-[11px] text-amber-700", children: ["attempt ", s.attempt] })] }), _jsx("td", { className: "py-1.5", children: _jsx(StatusPill, { tone: RUN_TONE[s.status], label: s.escalated_at ? "overdue" : s.status }) }), _jsx("td", { className: "py-1.5 text-xs text-slate-600", children: s.actor_username ?? (s.step_type === "approval" || s.step_type === "human_task" ? "—" : "system") }), _jsx("td", { className: "py-1.5 text-right text-xs whitespace-nowrap text-slate-600", children: formatDuration(s.duration_ms) })] }), s.error && (_jsxs("tr", { children: [_jsx("td", {}), _jsxs("td", { colSpan: 4, className: "pb-2 text-xs text-rose-700", children: [s.error.code, ": ", s.error.message] })] }))] }, s.id))) })] }), _jsx("div", { className: "flex gap-2", children: _jsxs(Button, { size: "sm", variant: "secondary", onClick: () => setShowContext(!showContext), children: [showContext ? "Hide" : "Show", " context"] }) }), showContext && (_jsx("pre", { "aria-label": "Execution context", className: "max-h-72 overflow-auto rounded-lg bg-navy-950 p-3 font-mono text-[11px] text-slate-100", children: JSON.stringify(e.context, null, 2) })), _jsxs("section", { "aria-label": "History", children: [_jsx("h4", { className: "mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase", children: "History" }), _jsx("ol", { className: "max-h-48 space-y-0.5 overflow-auto font-mono text-[11px] text-slate-600", children: history.data?.map((ev) => (_jsxs("li", { children: [formatTimestamp(ev.occurred_at), " \u00B7 ", ev.event_type, "step" in ev.data && ev.data.step ? ` · ${String(ev.data.step)}` : ""] }, ev.id))) })] })] }))] }));
}
function ExecutionsTab({ onOpen }) {
    const [status, setStatus] = useState("");
    const [offset, setOffset] = useState(0);
    const executions = useExecutions({ status: status || undefined, limit: PAGE_SIZE, offset });
    return (_jsxs(_Fragment, { children: [_jsx("div", { className: "mb-4", children: _jsxs("select", { "aria-label": "Execution status", className: "rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm", value: status, onChange: (e) => {
                        setStatus(e.target.value);
                        setOffset(0);
                    }, children: [_jsx("option", { value: "", children: "Any status" }), ["running", "waiting", "completed", "failed", "cancelled"].map((s) => (_jsx("option", { value: s, children: humanize(s) }, s)))] }) }), _jsx(ErrorMessage, { error: executions.error, className: "mb-4" }), _jsx("div", { className: "overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm", children: _jsxs("table", { className: "min-w-full text-sm", children: [_jsx("thead", { className: "bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-4 py-2.5", children: "Case" }), _jsx("th", { className: "px-4 py-2.5", children: "Status" }), _jsx("th", { className: "px-4 py-2.5", children: "Current step" }), _jsx("th", { className: "px-4 py-2.5", children: "Started" }), _jsx("th", { className: "px-4 py-2.5 text-right", children: "Duration" })] }) }), _jsxs("tbody", { className: "divide-y divide-slate-100", children: [executions.data?.items.length === 0 && (_jsx("tr", { children: _jsx("td", { colSpan: 5, className: "px-4 py-6 text-center text-slate-500", children: "No executions yet." }) })), executions.data?.items.map((x) => (_jsxs("tr", { className: "cursor-pointer hover:bg-slate-50", onClick: () => onOpen(x.id), children: [_jsxs("td", { className: "px-4 py-2.5", children: [_jsx("button", { type: "button", className: "text-left font-medium text-slate-900 hover:underline", children: x.subject ?? x.id.slice(0, 8) }), _jsx("div", { className: "font-mono text-[11px] text-slate-500", children: x.workflow_id })] }), _jsx("td", { className: "px-4 py-2.5", children: _jsx(StatusPill, { tone: EXECUTION_TONE[x.status], label: x.outcome ? `${x.status} · ${x.outcome}` : x.status }) }), _jsx("td", { className: "px-4 py-2.5 font-mono text-xs text-slate-600", children: x.current_steps.join(", ") || "—" }), _jsxs("td", { className: "px-4 py-2.5 text-xs text-slate-600", children: [formatTimestamp(x.started_at), _jsxs("div", { className: "text-slate-400", children: ["by ", x.initiated_by_username] })] }), _jsx("td", { className: "px-4 py-2.5 text-right text-xs text-slate-600", children: formatDuration(x.duration_ms) })] }, x.id)))] })] }) }), executions.data && (_jsx("div", { className: "mt-3", children: _jsx(Pagination, { total: executions.data.total, limit: PAGE_SIZE, offset: offset, onChange: setOffset }) }))] }));
}
// --- Tasks ------------------------------------------------------------------------------------
function TaskRow({ task, onOpen }) {
    const complete = useCompleteTask();
    const [note, setNote] = useState("");
    return (_jsxs("li", { className: "rounded-xl border border-slate-200 bg-white p-4 shadow-sm", children: [_jsxs("div", { className: "flex flex-wrap items-start justify-between gap-3", children: [_jsxs("div", { children: [_jsx("p", { className: "text-sm font-semibold text-slate-900", children: task.step_name }), _jsxs("p", { className: "text-sm text-slate-700", children: [task.subject ?? "—", " \u00B7 risk ", task.risk_rating ?? "—", task.flags.length > 0 && _jsxs("span", { className: "text-rose-700", children: [" \u00B7 flags: ", task.flags.join(", ")] })] }), _jsxs("p", { className: "text-xs text-slate-500", children: ["Started by ", task.initiated_by_username, " \u00B7 opened ", formatTimestamp(task.opened_at), task.due_at && ` · due ${formatTimestamp(task.due_at)}`, task.overdue && _jsx("span", { className: "font-medium text-rose-700", children: " \u00B7 overdue" })] }), _jsx("button", { type: "button", className: "mt-1 text-xs text-navy-700 hover:underline", onClick: () => onOpen(task.execution_id), children: "Open case" })] }), task.can_act ? (_jsxs("div", { className: "flex flex-col items-end gap-2", children: [_jsx("input", { "aria-label": `Note for ${task.subject ?? task.workflow_id}`, placeholder: "Decision note", className: "w-56 rounded-lg border border-slate-200 px-2 py-1 text-sm", value: note, onChange: (e) => setNote(e.target.value) }), _jsxs("div", { className: "flex gap-1.5", children: [_jsxs(Button, { size: "sm", disabled: complete.isPending, onClick: () => complete.mutate({ runId: task.run_id, decision: "approve", note }), children: [_jsx(CheckCircle2, { "aria-hidden": true, className: "h-3.5 w-3.5" }), " Approve"] }), _jsxs(Button, { size: "sm", variant: "secondary", disabled: complete.isPending, onClick: () => complete.mutate({ runId: task.run_id, decision: "reject", note }), children: [_jsx(XCircle, { "aria-hidden": true, className: "h-3.5 w-3.5" }), " Reject"] })] })] })) : (_jsx("p", { className: "max-w-xs text-right text-xs text-slate-500", children: task.blocked_reason }))] }), _jsx(ErrorMessage, { error: complete.error, className: "mt-2" })] }));
}
function TasksTab({ onOpen }) {
    const [onlyMine, setOnlyMine] = useState(true);
    const tasks = useTasks(onlyMine);
    return (_jsxs(_Fragment, { children: [_jsxs("label", { className: "mb-4 flex items-center gap-2 text-sm text-slate-700", children: [_jsx("input", { type: "checkbox", checked: onlyMine, onChange: (e) => setOnlyMine(e.target.checked) }), "Only tasks I can act on"] }), _jsx(ErrorMessage, { error: tasks.error, className: "mb-4" }), tasks.data?.items.length === 0 && _jsx("p", { className: "text-sm text-slate-500", children: "No open tasks." }), _jsx("ul", { "aria-label": "Tasks", className: "space-y-3", children: tasks.data?.items.map((t) => (_jsx(TaskRow, { task: t, onOpen: onOpen }, t.run_id))) })] }));
}
export function WorkflowExplorerPage() {
    const [params, setParams] = useSearchParams();
    const tab = params.get("tab") ?? "catalogue";
    const openId = params.get("execution");
    const set = (changes) => {
        const next = new URLSearchParams(params);
        for (const [k, v] of Object.entries(changes)) {
            if (v)
                next.set(k, v);
            else
                next.delete(k);
        }
        setParams(next);
    };
    const tabs = [
        { id: "catalogue", label: "Catalogue" },
        { id: "templates", label: "Templates" },
        { id: "executions", label: "Executions" },
        { id: "tasks", label: "Task inbox" },
    ];
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Workflow Explorer", description: "Executable business workflows: definitions, live executions, approvals and bottlenecks. Every case is persisted and auditable." }), _jsx("div", { role: "tablist", "aria-label": "Workflow views", className: "mb-5 flex gap-1 border-b border-slate-200", children: tabs.map((t) => (_jsx("button", { role: "tab", type: "button", "aria-selected": tab === t.id, onClick: () => set({ tab: t.id === "catalogue" ? null : t.id, workflow: null }), className: `-mb-px border-b-2 px-3 py-2 text-sm font-medium ${tab === t.id ? "border-navy-900 text-navy-900" : "border-transparent text-slate-500 hover:text-slate-800"}`, children: t.label }, t.id))) }), tab === "catalogue" && (_jsx(CatalogueTab, { initial: params.get("workflow"), onStarted: (id) => set({ tab: "executions", execution: id }) }, params.get("workflow") ?? "catalogue")), tab === "templates" && _jsx(TemplatesTab, { onOpenWorkflow: (workflowId) => set({ tab: null, workflow: workflowId }) }), tab === "executions" && _jsx(ExecutionsTab, { onOpen: (id) => set({ execution: id }) }), tab === "tasks" && _jsx(TasksTab, { onOpen: (id) => set({ execution: id }) }), openId && _jsx(ExecutionView, { id: openId, onClose: () => set({ execution: null }) }, openId)] }));
}
