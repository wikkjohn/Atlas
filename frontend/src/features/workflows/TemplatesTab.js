import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Wand2 } from "lucide-react";
import { useState } from "react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { formatTimestamp } from "@/features/dashboard/format";
import { useGenerateVariants, useTemplates, useTemplateVariants } from "@/services/workflows";
function describe(property) {
    if (Array.isArray(property.enum))
        return property.enum.join(" | ");
    const range = property.minimum !== undefined || property.maximum !== undefined
        ? ` ${property.minimum ?? ""}–${property.maximum ?? ""}`
        : "";
    return `${String(property.type ?? "any")}${range}`;
}
function GenerationTable({ result }) {
    return (_jsxs("div", { className: "space-y-2", children: [_jsxs("p", { role: "status", className: "text-sm text-slate-700", children: [result.dry_run ? "Preview (nothing stored): " : result.stored ? "Stored: " : "Nothing stored: ", result.created, " new, ", result.updated, " updated, ", result.unchanged, " unchanged, ", result.invalid, " invalid"] }), _jsx("div", { className: "max-h-64 overflow-auto rounded-lg border border-slate-200", children: _jsxs("table", { "aria-label": "Generated variants", className: "min-w-full text-xs", children: [_jsx("thead", { className: "bg-slate-50 text-left text-slate-500", children: _jsxs("tr", { children: [_jsx("th", { className: "px-3 py-1.5", children: "Workflow" }), _jsx("th", { className: "px-3 py-1.5", children: "Parameters" }), _jsx("th", { className: "px-3 py-1.5", children: "Result" })] }) }), _jsx("tbody", { className: "divide-y divide-slate-100", children: result.results.map((r) => (_jsxs("tr", { children: [_jsxs("td", { className: "px-3 py-1.5 font-mono", children: [r.workflow_id ?? "—", r.version ? ` v${r.version}` : ""] }), _jsx("td", { className: "px-3 py-1.5 font-mono text-slate-600", children: r.variant_key }), _jsxs("td", { className: `px-3 py-1.5 ${r.status === "invalid" ? "text-rose-700" : "text-slate-700"}`, children: [r.status, r.errors.map((e) => (_jsxs("div", { children: [e.location, ": ", e.message] }, e.location + e.code)))] })] }, r.variant_key))) })] }) })] }));
}
/** Preview, then generate: one workflow per parameter set, all stored or none. */
function GenerateDialog({ template, onClose }) {
    const generate = useGenerateVariants(template.template_id);
    const [text, setText] = useState(() => JSON.stringify({ fixed: template.example }, null, 2));
    const [parseError, setParseError] = useState(null);
    const [result, setResult] = useState(null);
    const run = (dryRun) => {
        let spec;
        try {
            spec = JSON.parse(text);
            setParseError(null);
        }
        catch (cause) {
            setParseError(`Not valid JSON: ${cause.message}`);
            return;
        }
        generate.mutate({ ...spec, dry_run: dryRun }, { onSuccess: setResult });
    };
    return (_jsx(Modal, { wide: true, title: `Generate variants of ${template.template_id}`, onClose: onClose, footer: _jsxs(_Fragment, { children: [_jsx(Button, { variant: "secondary", onClick: onClose, children: "Close" }), _jsx(Button, { variant: "secondary", disabled: generate.isPending, onClick: () => run(true), children: "Preview" }), _jsx(Button, { disabled: generate.isPending, onClick: () => run(false), children: "Generate" })] }), children: _jsxs("div", { className: "space-y-3", children: [_jsxs("p", { className: "text-sm text-slate-600", children: ["Parameter sets are the combinations of ", _jsx("span", { className: "font-mono", children: "grid" }), " plus any explicit", " ", _jsx("span", { className: "font-mono", children: "variants" }), ", each over ", _jsx("span", { className: "font-mono", children: "fixed" }), ". Each gets a stable workflow id from ", template.id_range[0], "\u2013", template.id_range[1], "; regenerating publishes new versions only where the result changed. If any variant is invalid, nothing is stored."] }), _jsx(Field, { label: "Parameter sets (JSON)", children: (p) => (_jsx("textarea", { ...p, className: `${inputClass} h-40 font-mono text-xs`, spellCheck: false, value: text, onChange: (e) => {
                            setText(e.target.value);
                            setResult(null);
                        } })) }), parseError && (_jsx("p", { role: "alert", className: "text-sm text-rose-700", children: parseError })), _jsx(ErrorMessage, { error: generate.error }), result && _jsx(GenerationTable, { result: result })] }) }));
}
export function TemplatesTab({ onOpenWorkflow }) {
    const { can } = useAuth();
    const templates = useTemplates();
    const latest = new Map();
    for (const t of templates.data ?? [])
        latest.set(t.template_id, t); // sorted by version
    const list = [...latest.values()];
    const [selected, setSelected] = useState(null);
    const current = list.find((t) => t.template_id === selected) ?? list[0] ?? null;
    const variants = useTemplateVariants(current?.template_id ?? null);
    const [generating, setGenerating] = useState(false);
    if (templates.error)
        return _jsx(ErrorMessage, { error: templates.error });
    if (templates.data && list.length === 0)
        return _jsx("p", { className: "text-sm text-slate-500", children: "No templates imported yet." });
    return (_jsxs("div", { className: "grid grid-cols-1 gap-6 lg:grid-cols-[300px_1fr]", children: [_jsx("ul", { "aria-label": "Templates", className: "space-y-2", children: list.map((t) => (_jsx("li", { children: _jsxs("button", { type: "button", onClick: () => setSelected(t.template_id), className: `w-full rounded-lg border p-3 text-left ${current?.template_id === t.template_id ? "border-navy-700 bg-navy-900/5" : "border-slate-200 bg-white hover:bg-slate-50"}`, children: [_jsx("div", { className: "font-mono text-[11px] text-slate-500", children: t.template_id }), _jsx("div", { className: "text-sm font-medium text-slate-900", children: t.name }), _jsxs("div", { className: "text-xs text-slate-500", children: ["v", t.version, " \u00B7 ", t.variants, " workflows \u00B7 ids ", t.id_range[0], "\u2013", t.id_range[1]] })] }) }, t.template_id))) }), current && (_jsxs("div", { className: "space-y-4", children: [_jsxs("div", { className: "flex flex-wrap items-start justify-between gap-3", children: [_jsxs("div", { children: [_jsxs("h2", { className: "text-lg font-semibold text-slate-900", children: [current.name, " ", _jsxs("span", { className: "text-xs font-normal text-slate-500", children: ["v", current.version] })] }), _jsx("p", { className: "mt-1 text-sm text-slate-600", children: current.description }), _jsxs("p", { className: "mt-1 text-xs text-slate-500", children: ["Imported ", formatTimestamp(current.imported_at), " by ", current.imported_by_username ?? "—"] })] }), can("workflows:define") && current.status === "active" && (_jsxs(Button, { onClick: () => setGenerating(true), children: [_jsx(Wand2, { "aria-hidden": true, className: "h-4 w-4" }), " Generate variants"] }))] }), _jsxs("table", { "aria-label": "Template parameters", className: "min-w-full rounded-xl border border-slate-200 bg-white text-sm", children: [_jsx("thead", { className: "bg-slate-50 text-left text-xs text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-4 py-2", children: "Parameter" }), _jsx("th", { className: "px-4 py-2", children: "Values" }), _jsx("th", { className: "px-4 py-2", children: "Example" })] }) }), _jsx("tbody", { className: "divide-y divide-slate-100", children: Object.entries(current.parameters.properties ?? {}).map(([name, property]) => (_jsxs("tr", { children: [_jsx("td", { className: "px-4 py-2 font-mono text-xs", children: name }), _jsx("td", { className: "px-4 py-2 text-xs text-slate-600", children: describe(property) }), _jsx("td", { className: "px-4 py-2 font-mono text-xs", children: JSON.stringify(current.example[name]) })] }, name))) })] }), _jsxs("div", { children: [_jsxs("h3", { className: "mb-2 text-sm font-semibold text-slate-900", children: ["Generated workflows (", variants.data?.length ?? 0, ")"] }), _jsx("div", { className: "max-h-96 overflow-auto rounded-xl border border-slate-200 bg-white", children: _jsxs("table", { "aria-label": "Template variants", className: "min-w-full text-xs", children: [_jsx("thead", { className: "sticky top-0 bg-slate-50 text-left text-slate-500", children: _jsxs("tr", { children: [_jsx("th", { className: "px-3 py-1.5", children: "Workflow" }), _jsx("th", { className: "px-3 py-1.5", children: "Parameters" }), _jsx("th", { className: "px-3 py-1.5", children: "From template" })] }) }), _jsx("tbody", { className: "divide-y divide-slate-100", children: variants.data?.map((v) => (_jsxs("tr", { className: "cursor-pointer hover:bg-slate-50", onClick: () => onOpenWorkflow(v.workflow_id), children: [_jsxs("td", { className: "px-3 py-1.5 font-mono", children: [v.workflow_id, " v", v.definition_version] }), _jsx("td", { className: "px-3 py-1.5 font-mono text-slate-600", children: v.variant_key }), _jsxs("td", { className: "px-3 py-1.5 text-slate-600", children: ["v", v.template_version] })] }, v.workflow_id))) })] }) })] }), generating && _jsx(GenerateDialog, { template: current, onClose: () => setGenerating(false) })] }))] }));
}
