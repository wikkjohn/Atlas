import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Building2, ChevronDown, ChevronRight, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { SubsidiariesPanel } from "@/features/organizations/SubsidiariesPanel";
import { CHILD_TYPE, ORG_TYPE_LABELS, REGION_LABELS } from "@/services/format";
import { useAncestors, useCountries, useCreateOrganization, useEmployees, useOrganization, useOrganizations, useUpdateOrganization, } from "@/services/enterprise";
function TypeBadge({ type }) {
    return (_jsx("span", { className: "rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-slate-600 uppercase", children: ORG_TYPE_LABELS[type] }));
}
function TreeNode({ organization, depth, selectedId, onSelect, initiallyOpen = false }) {
    const [open, setOpen] = useState(initiallyOpen);
    const hasChildren = organization.child_count > 0;
    const children = useOrganizations({ parent_id: organization.id }, open && hasChildren);
    const selected = organization.id === selectedId;
    return (_jsxs("li", { children: [_jsxs("div", { className: `flex items-center gap-1 rounded-md py-1 pr-2 ${selected ? "bg-navy-900/5 ring-1 ring-navy-700/20" : "hover:bg-slate-50"}`, style: { paddingLeft: `${depth * 16 + 4}px` }, children: [_jsx("button", { type: "button", "aria-label": open ? `Collapse ${organization.name}` : `Expand ${organization.name}`, "aria-expanded": hasChildren ? open : undefined, disabled: !hasChildren, onClick: () => setOpen(!open), className: "flex h-5 w-5 shrink-0 items-center justify-center rounded text-slate-400 hover:text-slate-700 disabled:invisible", children: open ? _jsx(ChevronDown, { className: "h-4 w-4" }) : _jsx(ChevronRight, { className: "h-4 w-4" }) }), _jsxs("button", { type: "button", onClick: () => onSelect(organization.id), className: "flex min-w-0 flex-1 items-center gap-2 text-left text-sm", children: [_jsx("span", { className: `truncate ${selected ? "font-semibold text-navy-900" : "text-slate-800"} ${organization.status === "inactive" ? "text-slate-400 line-through" : ""}`, children: organization.name }), organization.country_code && (_jsx("span", { className: "font-mono text-[10px] text-slate-400", children: organization.country_code }))] })] }), open && hasChildren && (_jsxs("ul", { children: [children.isLoading && (_jsx("li", { className: "py-1 text-xs text-slate-400", style: { paddingLeft: `${depth * 16 + 32}px` }, children: "Loading\u2026" })), children.data?.items.map((child) => (_jsx(TreeNode, { organization: child, depth: depth + 1, selectedId: selectedId, onSelect: onSelect }, child.id)))] }))] }));
}
function AddUnitDialog({ parent, onClose }) {
    const childType = parent ? (CHILD_TYPE[parent.organization_type] ?? "team") : "global_bank";
    const create = useCreateOrganization();
    const [name, setName] = useState("");
    const [region, setRegion] = useState("europe");
    const needsCountry = childType === "country_subsidiary";
    const countries = useCountries(needsCountry ? { region: parent?.region ?? undefined, operational_status: "active" } : {});
    const [countryId, setCountryId] = useState("");
    const onSubmit = (event) => {
        event.preventDefault();
        create.mutate({
            name,
            organization_type: childType,
            parent_organization_id: parent?.id ?? null,
            region: childType === "regional_headquarters" ? region : undefined,
            country_id: needsCountry ? countryId || null : undefined,
        }, { onSuccess: onClose });
    };
    return (_jsxs(Modal, { title: `Add ${ORG_TYPE_LABELS[childType].toLowerCase()}`, onClose: onClose, footer: _jsxs(_Fragment, { children: [_jsx(Button, { variant: "secondary", onClick: onClose, children: "Cancel" }), _jsx(Button, { type: "submit", form: "add-unit", disabled: create.isPending, children: create.isPending ? "Creating…" : "Create" })] }), children: [_jsxs("form", { id: "add-unit", onSubmit: onSubmit, className: "space-y-4", children: [parent && (_jsxs("p", { className: "text-sm text-slate-600", children: ["Inside ", _jsx("span", { className: "font-medium text-slate-900", children: parent.name }), parent.country_name && ` · ${parent.country_name}`] })), _jsx(Field, { label: "Name", children: (p) => (_jsx("input", { ...p, className: inputClass, required: true, minLength: 2, value: name, onChange: (e) => setName(e.target.value) })) }), childType === "regional_headquarters" && (_jsx(Field, { label: "Region", children: (p) => (_jsx("select", { ...p, className: inputClass, value: region, onChange: (e) => setRegion(e.target.value), children: Object.entries(REGION_LABELS).map(([value, label]) => (_jsx("option", { value: value, children: label }, value))) })) })), needsCountry && (_jsx(Field, { label: "Country", hint: "Only active countries in this region can host a subsidiary.", children: (p) => (_jsxs("select", { ...p, className: inputClass, required: true, value: countryId, onChange: (e) => setCountryId(e.target.value), children: [_jsx("option", { value: "", children: "Select a country\u2026" }), countries.data?.items.map((c) => (_jsxs("option", { value: c.id, children: [c.country_name, " (", c.default_currency, ")"] }, c.id)))] })) }))] }), _jsx(ErrorMessage, { error: create.error, className: "mt-4" })] }));
}
function RenameDialog({ organization, onClose }) {
    const update = useUpdateOrganization();
    const [name, setName] = useState(organization.name);
    return (_jsxs(Modal, { title: "Rename organization", onClose: onClose, footer: _jsxs(_Fragment, { children: [_jsx(Button, { variant: "secondary", onClick: onClose, children: "Cancel" }), _jsx(Button, { type: "submit", form: "rename-unit", disabled: update.isPending, children: "Save" })] }), children: [_jsx("form", { id: "rename-unit", onSubmit: (e) => {
                    e.preventDefault();
                    update.mutate({ id: organization.id, body: { name } }, { onSuccess: onClose });
                }, children: _jsx(Field, { label: "Name", children: (p) => (_jsx("input", { ...p, className: inputClass, required: true, minLength: 2, value: name, onChange: (e) => setName(e.target.value) })) }) }), _jsx(ErrorMessage, { error: update.error, className: "mt-4" })] }));
}
function OrganizationDetail({ id }) {
    const { can } = useAuth();
    const organization = useOrganization(id);
    const ancestors = useAncestors(id);
    const update = useUpdateOrganization();
    const [dialog, setDialog] = useState(null);
    const org = organization.data;
    const staffed = org?.organization_type === "department" || org?.organization_type === "team";
    const staff = useEmployees({ organization_id: id, limit: 25 }, Boolean(staffed));
    const canManage = can("organizations:manage");
    if (organization.error)
        return _jsx(ErrorMessage, { error: organization.error });
    if (!org)
        return _jsx("p", { className: "text-sm text-slate-500", children: "Loading\u2026" });
    const childType = CHILD_TYPE[org.organization_type];
    const facts = [
        ["Type", ORG_TYPE_LABELS[org.organization_type]],
        ["Region", org.region ? REGION_LABELS[org.region] : "All regions"],
        ["Country", org.country_name ?? "—"],
        ["Currency", org.currency ?? "—"],
        ["Sub-units", String(org.child_count)],
        ["Staff (direct)", String(org.employee_count)],
        ["Built", org.generated_from ? `Generated (${org.generated_from})` : "By hand"],
    ];
    return (_jsxs("div", { className: "space-y-6", children: [_jsxs("div", { children: [ancestors.data && ancestors.data.length > 0 && (_jsx("p", { className: "mb-1 text-xs text-slate-500", children: ancestors.data.map((a) => a.name).join(" › ") })), _jsxs("div", { className: "flex flex-wrap items-center gap-2", children: [_jsx("h2", { className: "text-lg font-semibold text-slate-900", children: org.name }), _jsx(TypeBadge, { type: org.organization_type }), _jsx(StatusPill, { tone: org.status === "active" ? "good" : "neutral", label: org.status })] })] }), _jsx("dl", { className: "grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3", children: facts.map(([term, value]) => (_jsxs("div", { children: [_jsx("dt", { className: "text-xs font-medium tracking-wide text-slate-500 uppercase", children: term }), _jsx("dd", { className: "mt-0.5 text-slate-900", children: value })] }, term))) }), canManage && (_jsxs("div", { className: "flex flex-wrap gap-2", children: [childType && org.status === "active" && (_jsxs(Button, { size: "sm", onClick: () => setDialog("add"), children: [_jsx(Plus, { "aria-hidden": true, className: "h-3.5 w-3.5" }), "Add ", ORG_TYPE_LABELS[childType].toLowerCase()] })), _jsx(Button, { size: "sm", variant: "secondary", onClick: () => setDialog("rename"), children: "Rename" }), org.organization_type !== "global_bank" && (_jsx(Button, { size: "sm", variant: "secondary", disabled: update.isPending, onClick: () => update.mutate({
                            id: org.id,
                            body: { status: org.status === "active" ? "inactive" : "active" },
                        }), children: org.status === "active" ? "Deactivate" : "Reactivate" }))] })), _jsx(ErrorMessage, { error: update.error }), staffed && (_jsxs("div", { children: [_jsxs("div", { className: "mb-2 flex items-center justify-between", children: [_jsx("h3", { className: "text-sm font-semibold text-slate-900", children: "Staff" }), _jsx(Link, { to: `/employees?organization_id=${org.id}`, className: "text-xs font-medium text-navy-700 hover:underline", children: "Open in Employees" })] }), staff.data && staff.data.items.length === 0 && (_jsx("p", { className: "text-sm text-slate-500", children: "No staff assigned." })), _jsx("ul", { className: "divide-y divide-slate-100 text-sm", children: staff.data?.items.map((e) => (_jsxs("li", { className: "flex justify-between gap-4 py-1.5", children: [_jsx("span", { className: "text-slate-900", children: e.full_name }), _jsx("span", { className: "truncate text-slate-500", children: e.job_title })] }, e.id))) })] })), dialog === "add" && _jsx(AddUnitDialog, { parent: org, onClose: () => setDialog(null) }), dialog === "rename" && _jsx(RenameDialog, { organization: org, onClose: () => setDialog(null) })] }));
}
export function OrganizationPage() {
    const { can } = useAuth();
    const roots = useOrganizations({ root_only: true });
    const [selectedId, setSelectedId] = useState(null);
    const [creatingRoot, setCreatingRoot] = useState(false);
    const root = roots.data?.items[0];
    useEffect(() => {
        if (!selectedId && root)
            setSelectedId(root.id);
    }, [root, selectedId]);
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Organization", description: "Global bank \u2192 regional headquarters \u2192 country subsidiary \u2192 business division \u2192 department \u2192 team." }), _jsx(ErrorMessage, { error: roots.error }), roots.data && roots.data.total === 0 && (_jsx(Panel, { title: "No organization yet", children: _jsxs("div", { className: "flex flex-col items-start gap-3 text-sm text-slate-600", children: [_jsxs("p", { children: ["The hierarchy is empty. Run ", _jsx("code", { className: "font-mono", children: "make seed" }), " to create the demo bank, or start one here."] }), can("organizations:manage") && (_jsxs(Button, { onClick: () => setCreatingRoot(true), children: [_jsx(Building2, { "aria-hidden": true, className: "h-4 w-4" }), "Create the global bank"] }))] }) })), root && (_jsxs("div", { className: "grid grid-cols-1 gap-6 lg:grid-cols-[minmax(280px,380px)_1fr]", children: [_jsx(Panel, { title: "Hierarchy", subtitle: "Expand a unit to load its children", children: _jsx("ul", { "aria-label": "Organization hierarchy", className: "-mx-2 -my-2", children: _jsx(TreeNode, { organization: root, depth: 0, selectedId: selectedId, onSelect: setSelectedId, initiallyOpen: true }) }) }), _jsx(Panel, { title: "Details", children: selectedId ? (_jsx(OrganizationDetail, { id: selectedId }, selectedId)) : (_jsx("p", { className: "text-sm text-slate-500", children: "Select a unit." })) })] })), root && (_jsx("div", { className: "mt-6", children: _jsx(SubsidiariesPanel, {}) })), creatingRoot && _jsx(AddUnitDialog, { parent: null, onClose: () => setCreatingRoot(false) })] }));
}
