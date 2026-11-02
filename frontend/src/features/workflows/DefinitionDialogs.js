import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { ApiError, newIdempotencyKey } from "@/services/api";
import { humanize } from "@/services/format";
import { exportDefinition, useImportDefinition, useLibraryHandlers, useStartExecution, useValidateDefinition, } from "@/services/workflows";
const EFFECT_LABEL = {
    none: "No side effects",
    reads: "Reads records",
    writes: "Writes records",
    moves_money: "Moves money",
    advisory: "AI advice",
};
const EFFECT_STYLE = {
    none: "bg-slate-100 text-slate-600",
    reads: "bg-slate-100 text-slate-700",
    writes: "bg-amber-50 text-amber-800",
    moves_money: "bg-rose-50 text-rose-800",
    advisory: "bg-violet-50 text-violet-800",
};
export function EffectBadge({ effect }) {
    if (effect === "none")
        return null;
    return _jsx("span", { className: `rounded px-1.5 py-0.5 text-[10px] font-medium ${EFFECT_STYLE[effect]}`, children: EFFECT_LABEL[effect] });
}
/** Which steps change records or move money, grouped by effect. */
function EffectsSummary({ effects }) {
    const order = ["moves_money", "writes", "advisory", "reads"];
    const groups = order
        .map((effect) => [effect, Object.keys(effects).filter((step) => effects[step] === effect)])
        .filter(([, list]) => list.length > 0);
    if (groups.length === 0)
        return null;
    return (_jsx("ul", { "aria-label": "Effects", className: "space-y-1 text-xs text-slate-700", children: groups.map(([effect, list]) => (_jsxs("li", { className: "flex flex-wrap items-center gap-1.5", children: [_jsx(EffectBadge, { effect: effect }), " ", _jsx("span", { className: "font-mono", children: list.join(", ") })] }, effect))) }));
}
function Problems({ title, items, tone }) {
    if (items.length === 0)
        return null;
    const color = tone === "bad" ? "border-rose-200 bg-rose-50 text-rose-900" : "border-amber-200 bg-amber-50 text-amber-900";
    return (_jsxs("div", { className: `rounded-lg border p-3 text-sm ${color}`, children: [_jsxs("p", { className: "font-medium", children: [title, " (", items.length, ")"] }), _jsx("ul", { "aria-label": title, className: "mt-1 space-y-1 text-xs", children: items.map((p) => (_jsxs("li", { children: [_jsx("span", { className: "font-mono", children: p.location }), " \u2014 ", p.message, " ", _jsxs("span", { className: "font-mono opacity-70", children: ["[", p.code, "]"] })] }, `${p.location}:${p.code}:${p.message}`))) })] }));
}
/** The problems an import refusal (422 definition_invalid) carries, as a report. */
function refusalReport(error) {
    if (!(error instanceof ApiError) || error.code !== "definition_invalid")
        return null;
    const details = error.details;
    return { valid: false, workflow_id: null, version: null, content_hash: null, existing: null, ...details };
}
/** Paste (or start from an existing workflow's export), validate, then import. */
export function ImportDefinitionDialog({ startFrom, onClose, onImported, }) {
    const [text, setText] = useState("");
    const [parseError, setParseError] = useState(null);
    const [report, setReport] = useState(null);
    const validate = useValidateDefinition();
    const importer = useImportDefinition();
    const handlers = useLibraryHandlers();
    const parsed = () => {
        try {
            setParseError(null);
            return JSON.parse(text);
        }
        catch (cause) {
            setParseError(`Not valid JSON: ${cause.message}`);
            return undefined;
        }
    };
    const onValidate = () => {
        const definition = parsed();
        if (definition !== undefined)
            validate.mutate(definition, { onSuccess: setReport });
    };
    const onImport = () => {
        const definition = parsed();
        if (definition === undefined)
            return;
        importer.mutate(definition, {
            onSuccess: (result) => onImported(result.definition.workflow_id),
            onError: (error) => setReport(refusalReport(error)),
        });
    };
    const loadFrom = async (workflowId) => {
        const document = await exportDefinition(workflowId);
        setText(JSON.stringify({ ...document, version: Number(document.version) + 1 }, null, 2));
        setReport(null);
    };
    return (_jsx(Modal, { wide: true, title: "Import a workflow definition", onClose: onClose, footer: _jsxs(_Fragment, { children: [_jsx(Button, { variant: "secondary", onClick: onClose, children: "Cancel" }), _jsx(Button, { variant: "secondary", disabled: !text || validate.isPending, onClick: onValidate, children: validate.isPending ? "Validating…" : "Validate" }), _jsx(Button, { disabled: !text || importer.isPending, onClick: onImport, children: importer.isPending ? "Importing…" : "Import" })] }), children: _jsxs("div", { className: "space-y-3", children: [_jsx("p", { className: "text-sm text-slate-600", children: "A definition is JSON: its steps, routes, approval policies and an input schema. Service tasks use handlers from the library. Every problem is listed before anything is stored; versions are immutable once imported. An imported version is a draft until it is submitted, tested and approved by a colleague." }), startFrom && (_jsxs(Button, { size: "sm", variant: "secondary", onClick: () => void loadFrom(startFrom), children: ["Start from ", startFrom, " (as its next version)"] })), _jsx(Field, { label: "Definition (JSON)", children: (p) => (_jsx("textarea", { ...p, className: `${inputClass} h-72 font-mono text-xs`, spellCheck: false, value: text, onChange: (e) => {
                            setText(e.target.value);
                            setReport(null);
                        } })) }), parseError && (_jsx("p", { role: "alert", className: "text-sm text-rose-700", children: parseError })), report?.valid && (_jsxs("p", { className: "flex items-center gap-1.5 text-sm text-emerald-800", children: [_jsx(CheckCircle2, { "aria-hidden": true, className: "h-4 w-4" }), report.workflow_id, " v", report.version, " is valid", report.existing === "identical" ? " and already stored unchanged." : " and can be imported as a draft."] })), report?.valid && report.effects && _jsx(EffectsSummary, { effects: report.effects }), report && _jsx(Problems, { title: "Errors", items: report.errors, tone: "bad" }), report && _jsx(Problems, { title: "Warnings", items: report.warnings, tone: "warn" }), _jsx(ErrorMessage, { error: validate.error ?? (refusalReport(importer.error) ? null : importer.error) }), handlers.data && (_jsxs("details", { className: "text-xs text-slate-600", children: [_jsxs("summary", { className: "cursor-pointer font-medium text-slate-700", children: ["Handler library (", handlers.data.length, ")"] }), _jsx("ul", { className: "mt-2 space-y-1", children: handlers.data.map((h) => (_jsxs("li", { children: [_jsx("span", { className: "font-mono", children: h.name }), " ", _jsx(EffectBadge, { effect: h.effect }), h.requires_approval && _jsx("span", { className: "text-rose-700", children: " (approval required)" }), " \u2014 ", h.summary, " Params:", " ", _jsx("span", { className: "font-mono", children: Object.keys(h.params_schema.properties ?? {}).join(", ") })] }, h.name))) })] }))] }) }));
}
function initialValue(property) {
    return property.type === "boolean" ? false : "";
}
function cast(property, value) {
    if (property.type === "boolean")
        return value;
    if (property.type === "integer" || property.type === "number")
        return value === "" ? undefined : Number(value);
    if (property.enum && typeof property.enum[0] === "number")
        return Number(value);
    return value === "" ? undefined : value;
}
/** A start form generated from a stored definition's input schema. */
export function StartFromSchemaDialog({ workflowId, name, schema, onClose, onStarted, }) {
    const start = useStartExecution(workflowId);
    const [key] = useState(newIdempotencyKey);
    const properties = Object.entries(schema.properties ?? {});
    const required = new Set(schema.required ?? []);
    const [values, setValues] = useState(() => Object.fromEntries(properties.map(([k, p]) => [k, initialValue(p)])));
    const unsupported = properties.filter(([, p]) => !p.type && !p.enum).map(([k]) => k);
    const onSubmit = (event) => {
        event.preventDefault();
        const input = {};
        for (const [k, p] of properties) {
            const v = cast(p, values[k]);
            if (v !== undefined)
                input[k] = v;
        }
        start.mutate({ idempotencyKey: key, input }, { onSuccess: (execution) => onStarted(execution.id) });
    };
    return (_jsxs(Modal, { wide: true, title: `Start ${name} (${workflowId})`, onClose: onClose, footer: _jsxs(_Fragment, { children: [_jsx(Button, { variant: "secondary", onClick: onClose, children: "Cancel" }), _jsx(Button, { type: "submit", form: "schema-start", disabled: start.isPending, children: start.isPending ? "Starting…" : "Start case" })] }), children: [_jsx("form", { id: "schema-start", onSubmit: onSubmit, className: "grid grid-cols-1 gap-4 sm:grid-cols-2", children: properties.map(([k, p]) => {
                    const label = humanize(k);
                    const set = (v) => setValues({ ...values, [k]: v });
                    if (p.type === "boolean") {
                        return (_jsxs("label", { className: "flex items-center gap-2 text-sm", children: [_jsx("input", { type: "checkbox", checked: values[k] === true, onChange: (e) => set(e.target.checked) }), label] }, k));
                    }
                    return (_jsx(Field, { label: label, hint: p.description, children: (fieldProps) => p.enum ? (_jsxs("select", { ...fieldProps, className: inputClass, required: required.has(k), value: String(values[k]), onChange: (e) => set(e.target.value), children: [_jsx("option", { value: "", children: "Select\u2026" }), p.enum.map((option) => (_jsx("option", { value: String(option), children: humanize(String(option)) }, String(option))))] })) : (_jsx("input", { ...fieldProps, className: inputClass, type: p.type === "integer" || p.type === "number" ? "number" : p.format === "date" ? "date" : "text", required: required.has(k), pattern: p.pattern, minLength: p.minLength, maxLength: p.maxLength, min: p.minimum, max: p.maximum, step: p.type === "number" ? "any" : undefined, value: String(values[k]), onChange: (e) => set(e.target.value) })) }, k));
                }) }), unsupported.length > 0 && (_jsxs("p", { className: "mt-3 flex items-center gap-1.5 text-xs text-amber-800", children: [_jsx(AlertTriangle, { "aria-hidden": true, className: "h-3.5 w-3.5" }), " Fields this form cannot edit: ", unsupported.join(", ")] })), _jsx(ErrorMessage, { error: start.error, className: "mt-4" })] }));
}
