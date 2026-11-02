import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Check, Plus, Search } from "lucide-react";
import { useState } from "react";
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
import { formatTimestamp } from "@/features/dashboard/format";
import { HealthTiles, PlatformDetails } from "@/features/dashboard/PlatformHealth";
import { JobsPanel } from "@/features/settings/JobsPanel";
import { ObservabilityPanel } from "@/features/settings/ObservabilityPanel";
import { SimulationHistoryPanel } from "@/features/settings/SimulationHistoryPanel";
import { useCreateUser, useRoles, useUpdateUser, useUsers } from "@/services/enterprise";
import { useHealth, useSystemInfo, useSystemStatus } from "@/services/queries";
const PAGE = 20;
const SERVICE_ROLES = new Set(["automated_policy", "system_scheduler"]);
const USERNAME = /^[a-z0-9][a-z0-9._-]{2,63}$/;
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
// --- Users ------------------------------------------------------------------------------------
function CreateUserDialog({ roles, onClose }) {
    const create = useCreateUser();
    const people = roles.filter((r) => !SERVICE_ROLES.has(r.code));
    const [form, setForm] = useState({
        username: "",
        email: "",
        display_name: "",
        password: "",
        role: "banking_employee",
    });
    const [submitted, setSubmitted] = useState(false);
    const errors = {
        username: USERNAME.test(form.username.trim().toLowerCase())
            ? null
            : "3–64 characters: lower-case letters, digits, dots, hyphens, underscores.",
        email: EMAIL.test(form.email.trim()) ? null : "A valid email address.",
        display_name: form.display_name.trim() ? null : "Required.",
        password: form.password.length >= 12 ? null : "At least 12 characters.",
    };
    const valid = Object.values(errors).every((e) => e === null);
    const show = (key) => (submitted ? errors[key] : null);
    const set = (key) => (value) => setForm({ ...form, [key]: value });
    const submit = (event) => {
        event.preventDefault();
        setSubmitted(true);
        if (!valid)
            return;
        create.mutate({ ...form, username: form.username.trim().toLowerCase(), email: form.email.trim() }, { onSuccess: onClose });
    };
    return (_jsxs(Modal, { title: "Create a user", onClose: onClose, children: [_jsxs("form", { id: "create-user", "aria-label": "Create a user", onSubmit: submit, className: "space-y-3", children: [_jsx(Field, { label: "Username", error: show("username"), children: (p) => _jsx("input", { ...p, autoComplete: "off", className: inputClass, value: form.username, onChange: (e) => set("username")(e.target.value) }) }), _jsx(Field, { label: "Email", error: show("email"), children: (p) => _jsx("input", { ...p, type: "email", className: inputClass, value: form.email, onChange: (e) => set("email")(e.target.value) }) }), _jsx(Field, { label: "Display name", error: show("display_name"), children: (p) => _jsx("input", { ...p, className: inputClass, value: form.display_name, onChange: (e) => set("display_name")(e.target.value) }) }), _jsx(Field, { label: "Initial password", hint: "At least 12 characters; share it securely.", error: show("password"), children: (p) => (_jsx("input", { ...p, type: "password", autoComplete: "new-password", className: inputClass, value: form.password, onChange: (e) => set("password")(e.target.value) })) }), _jsx(Field, { label: "Role", children: (p) => (_jsx("select", { ...p, className: inputClass, value: form.role, onChange: (e) => set("role")(e.target.value), children: people.map((r) => (_jsx("option", { value: r.code, children: r.name }, r.code))) })) })] }), _jsx(ErrorMessage, { error: create.error, className: "mt-3" }), _jsxs("div", { className: "mt-4 flex justify-end gap-2", children: [_jsx(Button, { variant: "secondary", onClick: onClose, children: "Cancel" }), _jsx(Button, { type: "submit", form: "create-user", disabled: create.isPending, children: "Create user" })] })] }));
}
function UsersPanel({ roles }) {
    const { user: me, can } = useAuth();
    const manage = can("users:manage");
    const [kind, setKind] = useState("people");
    const [q, setQ] = useState("");
    const [offset, setOffset] = useState(0);
    const [creating, setCreating] = useState(false);
    const users = useUsers({ kind, q: q || null, limit: PAGE, offset });
    const update = useUpdateUser();
    const people = roles.filter((r) => !SERVICE_ROLES.has(r.code));
    return (_jsxs(Panel, { title: "Users", subtitle: "Sign-ins and system principals. Roles grant permissions; the backend enforces them.", actions: manage ? (_jsxs(Button, { size: "sm", onClick: () => setCreating(true), children: [_jsx(Plus, { "aria-hidden": true, className: "h-3.5 w-3.5" }), " Create user"] })) : undefined, children: [_jsxs("div", { className: "mb-3 flex flex-wrap items-center gap-3", children: [_jsx("div", { role: "tablist", "aria-label": "User kind", className: "inline-flex rounded-lg border border-slate-200 p-0.5 text-xs", children: ["people", "service"].map((k) => (_jsx("button", { role: "tab", type: "button", "aria-selected": kind === k, onClick: () => {
                                setKind(k);
                                setOffset(0);
                            }, className: `rounded-md px-2.5 py-1 font-medium ${kind === k ? "bg-navy-900 text-white" : "text-slate-600 hover:bg-slate-50"}`, children: k === "people" ? "People" : "Service accounts" }, k))) }), _jsxs("div", { className: "relative", children: [_jsx(Search, { "aria-hidden": true, className: "pointer-events-none absolute top-2 left-2.5 h-4 w-4 text-slate-400" }), _jsx("input", { "aria-label": "Search users", placeholder: "Search users", className: `${inputClass} pl-8`, value: q, onChange: (e) => {
                                    setQ(e.target.value);
                                    setOffset(0);
                                } })] })] }), _jsx(ErrorMessage, { error: users.error ?? update.error, className: "mb-3" }), kind === "service" && (_jsx("p", { className: "mb-3 text-xs text-slate-500", children: "Service accounts act inside the platform \u2014 simulated staff and the policy engine \u2014 and can never sign in. They keep their role; deactivating the policy engine switches automated approvals off." })), _jsx("div", { className: "overflow-x-auto rounded-xl border border-slate-200", children: _jsxs("table", { "aria-label": "Users", className: "min-w-full text-sm", children: [_jsx("thead", { className: "bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-3 py-2", children: "User" }), _jsx("th", { className: "px-3 py-2", children: "Role" }), _jsx("th", { className: "px-3 py-2", children: "Status" }), _jsx("th", { className: "px-3 py-2", children: "Last sign-in" })] }) }), _jsxs("tbody", { className: "divide-y divide-slate-100", children: [(users.data?.items ?? []).map((u) => {
                                    const self = u.id === me?.id;
                                    return (_jsxs("tr", { children: [_jsxs("td", { className: "px-3 py-2", children: [_jsx("div", { className: "font-medium text-slate-900", children: u.display_name }), _jsxs("div", { className: "text-xs text-slate-500", children: [u.username, " \u00B7 ", u.email] })] }), _jsx("td", { className: "px-3 py-2", children: manage && !u.is_service_account && !self ? (_jsx("select", { "aria-label": `Role of ${u.username}`, className: `${inputClass} py-1 text-xs`, value: u.role, disabled: update.isPending, onChange: (e) => update.mutate({ id: u.id, role: e.target.value }), children: people.map((r) => (_jsx("option", { value: r.code, children: r.name }, r.code))) })) : (_jsx("span", { className: "text-slate-700", children: u.role_name })) }), _jsx("td", { className: "px-3 py-2", children: _jsxs("div", { className: "flex items-center gap-2", children: [_jsx(StatusPill, { tone: u.is_active ? "good" : "neutral", label: u.is_active ? "Active" : "Inactive" }), manage && !self && (_jsx(Button, { size: "sm", variant: "ghost", disabled: update.isPending, "aria-label": `${u.is_active ? "Deactivate" : "Activate"} ${u.username}`, onClick: () => update.mutate({ id: u.id, is_active: !u.is_active }), children: u.is_active ? "Deactivate" : "Activate" }))] }) }), _jsx("td", { className: "px-3 py-2 text-xs text-slate-600", children: u.is_service_account ? "Cannot sign in" : formatTimestamp(u.last_login_at) })] }, u.id));
                                }), users.data?.items.length === 0 && (_jsx("tr", { children: _jsx("td", { colSpan: 4, className: "px-3 py-6 text-center text-sm text-slate-500", children: "No users match." }) }))] })] }) }), users.data && _jsx(Pagination, { total: users.data.total, limit: PAGE, offset: offset, onChange: setOffset }), creating && _jsx(CreateUserDialog, { roles: roles, onClose: () => setCreating(false) })] }));
}
// --- Roles ------------------------------------------------------------------------------------
function RolesMatrix({ roles }) {
    const permissions = [...new Set(roles.flatMap((r) => r.permissions))].sort();
    return (_jsx(Panel, { title: "Roles and permissions", subtitle: "Defined in code and enforced on every request", children: _jsx("div", { className: "-mx-5 -my-5 overflow-x-auto", children: _jsxs("table", { "aria-label": "Role permissions", className: "min-w-full text-xs", children: [_jsx("thead", { className: "bg-slate-50 text-left font-medium text-slate-500", children: _jsxs("tr", { children: [_jsx("th", { className: "sticky left-0 bg-slate-50 px-3 py-2", children: "Permission" }), roles.map((r) => (_jsx("th", { scope: "col", className: "px-2 py-2 text-center whitespace-nowrap", children: r.name }, r.code)))] }) }), _jsx("tbody", { className: "divide-y divide-slate-100", children: permissions.map((p) => (_jsxs("tr", { children: [_jsx("th", { scope: "row", className: "sticky left-0 bg-white px-3 py-1.5 text-left font-mono font-normal text-slate-700", children: p }), roles.map((r) => (_jsx("td", { className: "px-2 py-1.5 text-center", children: r.permissions.includes(p) ? (_jsx(Check, { "aria-label": `${r.name}: ${p}`, className: "mx-auto h-3.5 w-3.5 text-emerald-600" })) : (_jsx("span", { "aria-hidden": true, className: "text-slate-300", children: "\u00B7" })) }, r.code)))] }, p))) })] }) }) }));
}
// --- Page ------------------------------------------------------------------------------------
export function SettingsPage() {
    const { can } = useAuth();
    const health = useHealth();
    const status = useSystemStatus();
    const info = useSystemInfo();
    const roles = useRoles();
    return (_jsxs("div", { className: "space-y-6", children: [_jsx(PageHeader, { title: "System Settings", description: "Platform health, build and database details, observability, background jobs, simulation history, users, roles and permissions.", actions: _jsx(SyntheticDataBadge, {}) }), _jsx(HealthTiles, { health: health, status: status, info: info }), _jsx(PlatformDetails, { status: status, info: info }), _jsx(ErrorMessage, { error: roles.error }), can("observability:read") && _jsx(ObservabilityPanel, {}), can("jobs:read") && _jsx(JobsPanel, {}), can("simulations:manage") && _jsx(SimulationHistoryPanel, {}), can("users:read") && roles.data && _jsx(UsersPanel, { roles: roles.data }), roles.data && _jsx(RolesMatrix, { roles: roles.data })] }));
}
