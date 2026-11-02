import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { StatusPill } from "@/components/StatusPill";
import { formatTimestamp } from "@/features/dashboard/format";
import { useCountries, useUsers } from "@/services/enterprise";
import { humanize } from "@/services/format";
import { useClassify, useSetDefinitionStatus, useStoredVersions } from "@/services/workflows";
export const STATUS_TONE = {
    draft: "neutral",
    in_review: "warn",
    active: "good",
    retired: "neutral",
};
const FILTERS = [
    ["department", "Department"],
    ["country", "Country"],
    ["product", "Product"],
    ["status", "Status"],
];
/** One select per facet, each option with how many workflows it would leave. */
export function CatalogueFilterBar({ filters, facets, onChange, }) {
    const active = FILTERS.some(([name]) => filters[name]);
    return (_jsxs("div", { className: "grid grid-cols-2 gap-2", children: [FILTERS.map(([name, label]) => {
                const chosen = filters[name] ?? "";
                const values = facets?.[name] ?? [];
                return (_jsxs("select", { "aria-label": `Filter by ${label.toLowerCase()}`, className: "rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs", value: chosen, onChange: (e) => onChange({ ...filters, [name]: e.target.value || undefined }), children: [_jsxs("option", { value: "", children: [label, ": any"] }), chosen && !values.some((f) => f.value === chosen) && _jsxs("option", { value: chosen, children: [name === "status" ? humanize(chosen) : chosen, " (0)"] }), values.map((f) => (_jsxs("option", { value: f.value, children: [name === "status" || name === "product" ? humanize(f.value) : f.value, " (", f.count, ")"] }, f.value)))] }, name));
            }), active && (_jsx("button", { type: "button", className: "col-span-2 text-left text-xs text-sky-700 hover:underline", onClick: () => onChange({ q: filters.q }), children: "Clear filters" }))] }));
}
/** Department, countries, products and owner of a workflow, with an edit button. */
export function Classification({ workflow }) {
    const { can } = useAuth();
    const [editing, setEditing] = useState(false);
    const parts = [
        workflow.department ? `Department: ${workflow.department}` : "No department",
        workflow.countries?.length ? `Countries: ${workflow.countries.join(", ")}` : null,
        workflow.products?.length ? `Products: ${workflow.products.map(humanize).join(", ")}` : null,
        workflow.owner_username ? `Owned by ${workflow.owner_username}` : null,
    ].filter(Boolean);
    return (_jsxs("div", { "aria-label": "Classification", className: "flex flex-wrap items-center gap-2 text-xs text-slate-600", children: [_jsx("span", { children: parts.join(" · ") }), workflow.tags?.map((t) => (_jsxs("span", { className: "rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600", children: ["#", t] }, t))), can("workflows:define") && (_jsx("button", { type: "button", className: "text-sky-700 hover:underline", onClick: () => setEditing(true), children: "Classify" })), editing && _jsx(ClassifyDialog, { workflow: workflow, onClose: () => setEditing(false) })] }));
}
const words = (text) => text
    .split(",")
    .map((w) => w.trim())
    .filter(Boolean);
function ClassifyDialog({ workflow, onClose }) {
    const { user, can } = useAuth();
    const classify = useClassify(workflow.workflow_id);
    const countries = useCountries({});
    const users = useUsers({ limit: 100 }, can("users:read"));
    const [department, setDepartment] = useState(workflow.department ?? "");
    const [chosen, setChosen] = useState(workflow.countries ?? []);
    const [products, setProducts] = useState((workflow.products ?? []).join(", "));
    const [tags, setTags] = useState((workflow.tags ?? []).join(", "));
    const [owner, setOwner] = useState(workflow.owner_id ?? "");
    const owners = users.data?.items ?? (user ? [user] : []);
    const onSubmit = (event) => {
        event.preventDefault();
        classify.mutate({ department: department.trim() || null, countries: chosen, products: words(products), tags: words(tags), owner_id: owner || null }, { onSuccess: onClose });
    };
    return (_jsxs(Modal, { title: `Classify ${workflow.workflow_id}`, onClose: onClose, footer: _jsxs(_Fragment, { children: [_jsx(Button, { variant: "secondary", onClick: onClose, children: "Cancel" }), _jsx(Button, { type: "submit", form: "classify", disabled: classify.isPending, children: classify.isPending ? "Saving…" : "Save classification" })] }), children: [_jsxs("form", { id: "classify", onSubmit: onSubmit, className: "space-y-3", children: [_jsx(Field, { label: "Department", children: (p) => _jsx("input", { ...p, className: inputClass, value: department, onChange: (e) => setDepartment(e.target.value) }) }), _jsxs("fieldset", { className: "text-sm", children: [_jsx("legend", { className: "text-xs font-medium text-slate-700", children: "Countries" }), _jsx("div", { className: "mt-1 flex flex-wrap gap-3", children: countries.data?.items.map((c) => (_jsxs("label", { className: "flex items-center gap-1.5", children: [_jsx("input", { type: "checkbox", checked: chosen.includes(c.iso_country_code), onChange: (e) => setChosen(e.target.checked ? [...chosen, c.iso_country_code] : chosen.filter((x) => x !== c.iso_country_code)) }), c.iso_country_code] }, c.id))) })] }), _jsx(Field, { label: "Products", hint: "Comma-separated, e.g. current, savings", children: (p) => _jsx("input", { ...p, className: inputClass, value: products, onChange: (e) => setProducts(e.target.value) }) }), _jsx(Field, { label: "Tags", hint: "Comma-separated", children: (p) => _jsx("input", { ...p, className: inputClass, value: tags, onChange: (e) => setTags(e.target.value) }) }), _jsx(Field, { label: "Owner", children: (p) => (_jsxs("select", { ...p, className: inputClass, value: owner, onChange: (e) => setOwner(e.target.value), children: [_jsx("option", { value: "", children: "No owner" }), workflow.owner_id && !owners.some((u) => u.id === workflow.owner_id) && (_jsx("option", { value: workflow.owner_id, children: workflow.owner_username ?? "Current owner" })), owners.map((u) => (_jsx("option", { value: u.id, children: u.username }, u.id)))] })) })] }), _jsx(ErrorMessage, { error: classify.error, className: "mt-3" })] }));
}
const ACTION_LABEL = {
    submit: "Submit for review",
    approve: "Approve",
    return: "Return to draft",
    retire: "Retire",
    reactivate: "Reactivate",
};
function actionsFor(status) {
    switch (status) {
        case "draft":
            return ["submit"];
        case "in_review":
            return ["approve", "return"];
        case "active":
            return ["retire"];
        case "retired":
            return ["reactivate"];
    }
}
function VersionRow({ v, selected, onSelect }) {
    const { can } = useAuth();
    const act = useSetDefinitionStatus();
    const [note, setNote] = useState("");
    const reviewing = v.status === "in_review";
    return (_jsxs("li", { className: `space-y-1.5 rounded-lg border p-3 text-sm ${selected ? "border-navy-700 bg-navy-900/5" : "border-slate-200"}`, children: [_jsxs("div", { className: "flex flex-wrap items-center gap-2", children: [_jsxs("button", { type: "button", className: "font-medium text-slate-900 hover:underline", onClick: onSelect, children: ["v", v.version] }), _jsx(StatusPill, { compact: true, tone: STATUS_TONE[v.status], label: humanize(v.status) }), _jsxs("span", { className: "text-xs text-slate-500", children: ["imported by ", v.imported_by_username ?? "system", " ", formatTimestamp(v.imported_at), v.submitted_by_username && ` · submitted by ${v.submitted_by_username}`, v.reviewed_by_username && ` · ${v.status === "draft" ? "returned" : "approved"} by ${v.reviewed_by_username}`] })] }), v.review_note && _jsxs("p", { className: "text-xs text-slate-600", children: ["\u201C", v.review_note, "\u201D"] }), can("workflows:define") && (_jsxs("div", { className: "flex flex-wrap items-center gap-1.5", children: [reviewing && (_jsx("input", { "aria-label": `Review note for v${v.version}`, placeholder: "Review note (required to return)", className: "min-w-48 flex-1 rounded-md border border-slate-200 px-2 py-1 text-xs", value: note, onChange: (e) => setNote(e.target.value) })), actionsFor(v.status).map((action) => (_jsxs(Button, { size: "sm", variant: action === "approve" || action === "submit" ? "primary" : "secondary", disabled: act.isPending || (action === "return" && !note.trim()), onClick: () => act.mutate({ workflowId: v.workflow_id, version: v.version, action, note }), children: [ACTION_LABEL[action], " v", v.version] }, action)))] })), _jsx(ErrorMessage, { error: act.error })] }));
}
/** Every stored version of a workflow with its review state and the actions it allows:
 * draft → submit → approve (someone else; tests must pass) or return → retire/reactivate. */
export function VersionsPanel({ workflowId, shown, onShow, }) {
    const versions = useStoredVersions(workflowId);
    return (_jsxs("section", { "aria-label": "Versions", className: "space-y-2", children: [_jsx("h3", { className: "text-sm font-semibold text-slate-900", children: "Versions and review" }), _jsx(ErrorMessage, { error: versions.error }), _jsx("ul", { className: "space-y-2", children: versions.data
                    ?.slice()
                    .reverse()
                    .map((v) => _jsx(VersionRow, { v: v, selected: v.version === shown, onSelect: () => onShow(v.version) }, v.version)) }), _jsx("p", { className: "text-xs text-slate-500", children: "Imported versions start as drafts. Approval needs someone other than the author and a passing generated test run of that version." })] }));
}
