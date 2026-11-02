import { createElement as _createElement } from "react";
import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { WorkflowGraph } from "@/features/workflows/WorkflowGraph";
import { exportDefinition, previewDefinition, useImportDefinition, useLibraryHandlers } from "@/services/workflows";
const PREVIEW_DELAY_MS = 500;
const STEP_TYPES = ["service_task", "ai_task", "approval", "human_task", "decision", "wait", "completion", "failure"];
/** Problems located at a step ("steps.<id>…") grouped by step id. */
function problemsByStep(preview) {
    const found = {};
    for (const e of preview?.report.errors ?? []) {
        const match = /^steps\.([a-z][a-z0-9_]*)/.exec(e.location);
        if (match)
            (found[match[1]] ??= []).push(e.message);
    }
    return found;
}
/** Edit a stored workflow as its next version: a step form and the JSON, with the draft
 * validated and drawn as you type. Saving imports it through the usual validation, as a
 * draft that then goes through review. */
export function DefinitionEditor({ workflowId, fromVersion, onClose, onSaved, }) {
    const [text, setText] = useState("");
    const [loadError, setLoadError] = useState(null);
    const [parseError, setParseError] = useState(null);
    const [preview, setPreview] = useState(null);
    const [previewError, setPreviewError] = useState(null);
    const [selected, setSelected] = useState(null);
    const handlers = useLibraryHandlers();
    const save = useImportDefinition();
    const latest = useRef(0);
    useEffect(() => {
        exportDefinition(workflowId, fromVersion).then((document) => setText(JSON.stringify({ ...document, version: Number(document.version) + 1 }, null, 2)), setLoadError);
    }, [workflowId, fromVersion]);
    const draft = useMemo(() => {
        try {
            const parsed = JSON.parse(text);
            return Array.isArray(parsed.steps) ? parsed : null;
        }
        catch {
            return null;
        }
    }, [text]);
    // Validate and lay out the draft shortly after the last change.
    useEffect(() => {
        if (!text)
            return;
        let parsed;
        try {
            parsed = JSON.parse(text);
            setParseError(null);
        }
        catch (cause) {
            setParseError(`Not valid JSON: ${cause.message}`);
            return;
        }
        const call = ++latest.current;
        const timer = setTimeout(() => {
            previewDefinition(parsed).then((result) => {
                if (call === latest.current) {
                    setPreview(result);
                    setPreviewError(null);
                }
            }, (error) => call === latest.current && setPreviewError(error));
        }, PREVIEW_DELAY_MS);
        return () => clearTimeout(timer);
    }, [text]);
    const update = (change) => {
        if (!draft)
            return;
        const next = structuredClone(draft);
        change(next);
        setText(JSON.stringify(next, null, 2));
    };
    const step = draft?.steps.find((s) => s.id === selected) ?? null;
    const stepIds = draft?.steps.map((s) => s.id) ?? [];
    const errors = problemsByStep(preview);
    const general = (preview?.report.errors ?? []).filter((e) => !e.location.startsWith("steps."));
    const setField = (name, value) => update((d) => {
        const target = d.steps.find((s) => s.id === selected);
        if (!target)
            return;
        if (value === "" || value === undefined)
            delete target[name];
        else
            target[name] = value;
    });
    const addStep = () => update((d) => {
        let n = d.steps.length + 1;
        while (d.steps.some((s) => s.id === `new_step_${n}`))
            n += 1;
        const id = `new_step_${n}`;
        d.steps.push({ id, type: "service_task", name: "New step", handler: "core.set_values", params: { values: { note: "set me" } } });
        setSelected(id);
    });
    const removeStep = () => update((d) => {
        d.steps = d.steps.filter((s) => s.id !== selected);
        setSelected(null);
    });
    const onSave = () => {
        if (!draft)
            return;
        save.mutate(draft, { onSuccess: (result) => onSaved(result.definition.workflow_id) });
    };
    return (_jsxs(Modal, { wide: true, title: `Edit ${workflowId}${draft ? ` as v${draft.version}` : ""}`, onClose: onClose, footer: _jsxs(_Fragment, { children: [_jsx(Button, { variant: "secondary", onClick: onClose, children: "Cancel" }), _jsx(Button, { disabled: !draft || !preview?.report.valid || save.isPending, onClick: onSave, children: save.isPending ? "Saving…" : draft ? `Save as v${draft.version}` : "Save" })] }), children: [_jsx(ErrorMessage, { error: loadError }), _jsxs("div", { className: "grid grid-cols-1 gap-4 xl:grid-cols-[minmax(320px,2fr)_3fr]", children: [_jsxs("div", { className: "space-y-3", children: [step ? (_jsxs("fieldset", { "aria-label": `Step ${step.id}`, className: "space-y-2 rounded-lg border border-slate-200 p-3", children: [_jsx("legend", { className: "px-1 font-mono text-xs text-slate-500", children: step.id }), _jsx(Field, { label: "Name", children: (p) => _jsx("input", { ...p, className: inputClass, value: String(step.name ?? ""), onChange: (e) => setField("name", e.target.value) }) }), _jsx(Field, { label: "Type", children: (p) => (_jsx("select", { ...p, className: inputClass, value: step.type, onChange: (e) => setField("type", e.target.value), children: STEP_TYPES.map((t) => (_jsx("option", { value: t, children: t }, t))) })) }), (step.type === "service_task" || step.type === "ai_task") && (_jsx(Field, { label: "Handler", children: (p) => (_jsxs("select", { ...p, className: inputClass, value: String(step.handler ?? ""), onChange: (e) => setField("handler", e.target.value), children: [_jsx("option", { value: "", children: "Select\u2026" }), handlers.data
                                                    ?.filter((h) => h.step_type === step.type)
                                                    .map((h) => (_jsx("option", { value: h.name, children: h.name }, h.name)))] })) })), _jsx(Field, { label: "Next step", children: (p) => (_jsxs("select", { ...p, className: inputClass, value: String(step.next ?? ""), onChange: (e) => setField("next", e.target.value), children: [_jsx("option", { value: "", children: "(none)" }), stepIds
                                                    .filter((id) => id !== step.id)
                                                    .map((id) => (_jsx("option", { value: id, children: id }, id)))] })) }), step.params !== undefined && (_jsx(Field, { label: "Params (JSON)", children: (p) => (_createElement("textarea", { ...p, key: step.id, className: `${inputClass} h-24 font-mono text-xs`, defaultValue: JSON.stringify(step.params, null, 2), onBlur: (e) => {
                                                try {
                                                    setField("params", JSON.parse(e.target.value));
                                                }
                                                catch {
                                                    setParseError("Params are not valid JSON.");
                                                }
                                            } })) })), errors[step.id] && (_jsx("ul", { "aria-label": "Step problems", className: "list-disc pl-5 text-xs text-rose-700", children: errors[step.id].map((m) => (_jsx("li", { children: m }, m))) })), _jsxs(Button, { size: "sm", variant: "secondary", onClick: removeStep, children: [_jsx(Trash2, { "aria-hidden": true, className: "h-3.5 w-3.5" }), " Remove step"] })] })) : (_jsx("p", { className: "text-sm text-slate-500", children: "Select a step in the diagram to edit it, or edit the JSON below." })), _jsxs(Button, { size: "sm", variant: "secondary", disabled: !draft, onClick: addStep, children: [_jsx(Plus, { "aria-hidden": true, className: "h-3.5 w-3.5" }), " Add a step"] }), _jsx(Field, { label: "Definition (JSON)", children: (p) => (_jsx("textarea", { ...p, className: `${inputClass} h-72 font-mono text-xs`, spellCheck: false, value: text, onChange: (e) => setText(e.target.value) })) }), parseError && (_jsx("p", { role: "alert", className: "text-sm text-rose-700", children: parseError }))] }), _jsxs("div", { className: "space-y-3", children: [_jsx("p", { role: "status", className: `text-sm ${preview?.report.valid ? "text-emerald-800" : "text-rose-800"}`, children: preview
                                    ? preview.report.valid
                                        ? `Valid: v${preview.report.version} can be saved as a draft for review.`
                                        : `${preview.report.errors.length} problem(s) to fix before saving.`
                                    : "Checking…" }), general.length > 0 && (_jsx("ul", { "aria-label": "Definition problems", className: "list-disc pl-5 text-xs text-rose-700", children: general.map((e) => (_jsxs("li", { children: [_jsx("span", { className: "font-mono", children: e.location }), ": ", e.message] }, e.location + e.code))) })), _jsx(ErrorMessage, { error: previewError ?? save.error }), preview?.graph && _jsx(WorkflowGraph, { graph: preview.graph, errors: errors, selected: selected, onSelect: setSelected })] })] })] }));
}
