import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Search, UserPlus } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { StatusPill } from "@/components/StatusPill";
import { formatMoney, humanize, toMinorUnits, currencyDigits } from "@/services/format";
import { useCreateEmployee, useDirectReports, useEmployee, useEmployees, useOrganization, useOrganizations, useReportingChain, useRoles, useUpdateEmployee, } from "@/services/enterprise";
const PAGE_SIZE = 25;
const STATUS_TONE = {
    active: "good",
    on_leave: "warn",
    terminated: "neutral",
};
function Compensation({ employee }) {
    if (employee.annual_compensation === null || !employee.compensation_currency) {
        return _jsx("span", { className: "text-xs text-slate-400", children: "Restricted" });
    }
    return _jsx(_Fragment, { children: formatMoney(employee.annual_compensation, employee.compensation_currency) });
}
/** Departments and teams, the only units staff can be assigned to. */
function useStaffableUnits() {
    const departments = useOrganizations({ organization_type: "department", status: "active" });
    const teams = useOrganizations({ organization_type: "team", status: "active" });
    const units = useMemo(() => [...(departments.data?.items ?? []), ...(teams.data?.items ?? [])].sort((a, b) => `${a.country_code}${a.name}`.localeCompare(`${b.country_code}${b.name}`)), [departments.data, teams.data]);
    return { units, loading: departments.isLoading || teams.isLoading };
}
function unitLabel(unit) {
    return `${unit.country_code ?? "—"} · ${unit.name} (${unit.organization_type === "team" ? "team" : "department"})`;
}
function HireDialog({ onClose }) {
    const create = useCreateEmployee();
    const roles = useRoles();
    const { units } = useStaffableUnits();
    const [form, setForm] = useState({
        first_name: "",
        last_name: "",
        job_title: "",
        organization_id: "",
        manager_id: "",
        role: "banking_employee",
        salary: "",
    });
    const unit = units.find((u) => u.id === form.organization_id);
    const departmentId = unit?.organization_type === "team" ? unit.parent_organization_id : unit?.id;
    const colleagues = useEmployees({ department_id: departmentId ?? undefined, employment_status: "active", limit: 200 }, Boolean(departmentId));
    const currency = unit?.currency ?? null;
    const set = (key) => (value) => setForm({ ...form, [key]: value });
    const onSubmit = (event) => {
        event.preventDefault();
        if (!currency)
            return;
        create.mutate({
            first_name: form.first_name,
            last_name: form.last_name,
            job_title: form.job_title,
            organization_id: form.organization_id,
            manager_id: form.manager_id || null,
            role: form.role,
            annual_compensation: toMinorUnits(Number(form.salary), currency),
        }, { onSuccess: onClose });
    };
    return (_jsxs(Modal, { wide: true, title: "Hire employee", onClose: onClose, footer: _jsxs(_Fragment, { children: [_jsx(Button, { variant: "secondary", onClick: onClose, children: "Cancel" }), _jsx(Button, { type: "submit", form: "hire-employee", disabled: create.isPending, children: create.isPending ? "Saving…" : "Hire" })] }), children: [_jsxs("form", { id: "hire-employee", onSubmit: onSubmit, className: "grid grid-cols-1 gap-4 sm:grid-cols-2", children: [_jsx(Field, { label: "First name", children: (p) => (_jsx("input", { ...p, className: inputClass, required: true, value: form.first_name, onChange: (e) => set("first_name")(e.target.value) })) }), _jsx(Field, { label: "Last name", children: (p) => (_jsx("input", { ...p, className: inputClass, required: true, value: form.last_name, onChange: (e) => set("last_name")(e.target.value) })) }), _jsx(Field, { label: "Job title", children: (p) => (_jsx("input", { ...p, className: inputClass, required: true, minLength: 2, value: form.job_title, onChange: (e) => set("job_title")(e.target.value) })) }), _jsx(Field, { label: "Unit", hint: "Staff join a department or a team.", children: (p) => (_jsxs("select", { ...p, className: inputClass, required: true, value: form.organization_id, onChange: (e) => setForm({ ...form, organization_id: e.target.value, manager_id: "" }), children: [_jsx("option", { value: "", children: "Select a unit\u2026" }), units.map((u) => (_jsx("option", { value: u.id, children: unitLabel(u) }, u.id)))] })) }), _jsx(Field, { label: "Manager", hint: "Optional; anyone active in the same department.", children: (p) => (_jsxs("select", { ...p, className: inputClass, disabled: !departmentId, value: form.manager_id, onChange: (e) => set("manager_id")(e.target.value), children: [_jsx("option", { value: "", children: "No manager" }), colleagues.data?.items.map((c) => (_jsxs("option", { value: c.id, children: [c.full_name, " \u2014 ", c.job_title] }, c.id)))] })) }), _jsx(Field, { label: "Platform role", children: (p) => (_jsx("select", { ...p, className: inputClass, value: form.role, onChange: (e) => set("role")(e.target.value), children: roles.data?.map((r) => (_jsx("option", { value: r.code, children: r.name }, r.code))) })) }), _jsx(Field, { label: `Annual compensation${currency ? ` (${currency})` : ""}`, hint: currency ? "Whole units; recorded in the country's currency." : "Select a unit first.", children: (p) => (_jsx("input", { ...p, className: inputClass, type: "number", min: 0, step: 1, required: true, disabled: !currency, value: form.salary, onChange: (e) => set("salary")(e.target.value) })) })] }), _jsx("p", { className: "mt-3 text-xs text-slate-500", children: "A synthetic email address in atlasbank.example and an employee number are assigned automatically." }), _jsx(ErrorMessage, { error: create.error, className: "mt-4" })] }));
}
function EditForm({ employee, onDone }) {
    const update = useUpdateEmployee();
    const { can } = useAuth();
    const colleagues = useEmployees({ department_id: employee.department_id, employment_status: "active", limit: 200 });
    const currency = employee.compensation_currency;
    const [form, setForm] = useState({
        job_title: employee.job_title,
        employment_status: employee.employment_status,
        manager_id: employee.manager?.id ?? "",
        salary: employee.annual_compensation !== null && currency
            ? String(employee.annual_compensation / 10 ** currencyDigits(currency))
            : "",
    });
    const onSubmit = (event) => {
        event.preventDefault();
        const body = {
            job_title: form.job_title,
            employment_status: form.employment_status,
            manager_id: form.manager_id || null,
        };
        if (can("employees:read_compensation") && currency && form.salary !== "") {
            body.annual_compensation = toMinorUnits(Number(form.salary), currency);
        }
        update.mutate({ id: employee.id, body }, { onSuccess: onDone });
    };
    return (_jsxs("form", { onSubmit: onSubmit, "aria-label": "Edit employee", className: "space-y-4 rounded-lg border border-slate-200 p-4", children: [_jsxs("div", { className: "grid grid-cols-1 gap-4 sm:grid-cols-2", children: [_jsx(Field, { label: "Job title", children: (p) => (_jsx("input", { ...p, className: inputClass, required: true, value: form.job_title, onChange: (e) => setForm({ ...form, job_title: e.target.value }) })) }), _jsx(Field, { label: "Employment status", children: (p) => (_jsxs("select", { ...p, className: inputClass, value: form.employment_status, onChange: (e) => setForm({ ...form, employment_status: e.target.value }), children: [_jsx("option", { value: "active", children: "Active" }), _jsx("option", { value: "on_leave", children: "On leave" }), _jsx("option", { value: "terminated", children: "Terminated" })] })) }), _jsx(Field, { label: "Manager", children: (p) => (_jsxs("select", { ...p, className: inputClass, value: form.manager_id, onChange: (e) => setForm({ ...form, manager_id: e.target.value }), children: [_jsx("option", { value: "", children: "No manager" }), colleagues.data?.items
                                    .filter((c) => c.id !== employee.id)
                                    .map((c) => (_jsxs("option", { value: c.id, children: [c.full_name, " \u2014 ", c.job_title] }, c.id)))] })) }), currency && (_jsx(Field, { label: `Annual compensation (${currency})`, children: (p) => (_jsx("input", { ...p, className: inputClass, type: "number", min: 0, value: form.salary, onChange: (e) => setForm({ ...form, salary: e.target.value }) })) }))] }), _jsx(ErrorMessage, { error: update.error }), _jsxs("div", { className: "flex justify-end gap-2", children: [_jsx(Button, { variant: "secondary", onClick: onDone, children: "Cancel" }), _jsx(Button, { type: "submit", disabled: update.isPending, children: "Save changes" })] })] }));
}
function EmployeeProfile({ id, onClose, onOpen }) {
    const { can } = useAuth();
    const employee = useEmployee(id);
    const chain = useReportingChain(id);
    const reports = useDirectReports(id);
    const [editing, setEditing] = useState(false);
    const e = employee.data;
    return (_jsxs(Modal, { wide: true, title: "Employee profile", onClose: onClose, children: [_jsx(ErrorMessage, { error: employee.error }), e && (_jsxs("div", { className: "space-y-5", children: [_jsxs("div", { className: "flex flex-wrap items-start justify-between gap-3", children: [_jsxs("div", { children: [_jsx("h3", { className: "text-lg font-semibold text-slate-900", children: e.full_name }), _jsxs("p", { className: "text-sm text-slate-600", children: [e.job_title, " \u00B7 ", e.organization_name] }), _jsxs("p", { className: "mt-0.5 font-mono text-xs text-slate-500", children: [e.employee_number, " \u00B7 ", e.email] })] }), _jsx(StatusPill, { tone: STATUS_TONE[e.employment_status], label: humanize(e.employment_status) })] }), _jsx("dl", { className: "grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4", children: [
                            ["Department", e.department_name],
                            ["Country", e.country_code],
                            ["Platform role", humanize(e.role)],
                            ["Compensation", _jsx(Compensation, { employee: e })],
                        ].map(([term, value]) => (_jsxs("div", { children: [_jsx("dt", { className: "text-xs font-medium tracking-wide text-slate-500 uppercase", children: term }), _jsx("dd", { className: "mt-0.5 text-slate-900", children: value })] }, term))) }), _jsxs("div", { className: "grid grid-cols-1 gap-5 sm:grid-cols-2", children: [_jsxs("section", { "aria-label": "Reporting chain", children: [_jsx("h4", { className: "mb-1.5 text-xs font-semibold tracking-wide text-slate-500 uppercase", children: "Reports to" }), chain.data?.length === 0 && _jsx("p", { className: "text-sm text-slate-500", children: "Top of reporting line." }), _jsx("ol", { className: "space-y-1 text-sm", children: chain.data?.map((m) => (_jsxs("li", { children: [_jsx("button", { type: "button", className: "text-navy-700 hover:underline", onClick: () => onOpen(m.id), children: m.full_name }), _jsxs("span", { className: "text-slate-500", children: [" \u00B7 ", m.job_title] })] }, m.id))) })] }), _jsxs("section", { "aria-label": "Direct reports", children: [_jsxs("h4", { className: "mb-1.5 text-xs font-semibold tracking-wide text-slate-500 uppercase", children: ["Direct reports ", reports.data && `(${reports.data.length})`] }), reports.data?.length === 0 && _jsx("p", { className: "text-sm text-slate-500", children: "None." }), _jsx("ul", { className: "space-y-1 text-sm", children: reports.data?.map((r) => (_jsxs("li", { children: [_jsx("button", { type: "button", className: "text-navy-700 hover:underline", onClick: () => onOpen(r.id), children: r.full_name }), _jsxs("span", { className: "text-slate-500", children: [" \u00B7 ", r.job_title] })] }, r.id))) })] })] }), can("employees:manage") &&
                        (editing ? (_jsx(EditForm, { employee: e, onDone: () => setEditing(false) })) : (_jsx(Button, { variant: "secondary", onClick: () => setEditing(true), children: "Edit employee" })))] }))] }));
}
export function EmployeesPage() {
    const { can } = useAuth();
    const [params, setParams] = useSearchParams();
    const [search, setSearch] = useState(params.get("q") ?? "");
    const [hiring, setHiring] = useState(false);
    const [profileId, setProfileId] = useState(null);
    const organizationId = params.get("organization_id");
    const status = params.get("employment_status") ?? "";
    const offset = Number(params.get("offset") ?? 0);
    const filterUnit = useOrganization(organizationId);
    const employees = useEmployees({
        q: params.get("q") ?? undefined,
        organization_id: organizationId ?? undefined,
        employment_status: status || undefined,
        limit: PAGE_SIZE,
        offset,
    });
    const update = (changes) => {
        const next = new URLSearchParams(params);
        for (const [key, value] of Object.entries(changes)) {
            if (value)
                next.set(key, value);
            else
                next.delete(key);
        }
        if (!("offset" in changes))
            next.delete("offset");
        setParams(next);
    };
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Employees", description: "Synthetic workforce registry. Compensation is recorded in each country's currency and visible only to permitted roles.", actions: can("employees:manage") && (_jsxs(Button, { onClick: () => setHiring(true), children: [_jsx(UserPlus, { "aria-hidden": true, className: "h-4 w-4" }), "Hire employee"] })) }), _jsxs("div", { className: "mb-4 flex flex-wrap items-center gap-3", children: [_jsxs("form", { role: "search", onSubmit: (e) => {
                            e.preventDefault();
                            update({ q: search.trim() || null });
                        }, className: "relative", children: [_jsx(Search, { "aria-hidden": true, className: "pointer-events-none absolute top-2 left-2.5 h-4 w-4 text-slate-400" }), _jsx("input", { "aria-label": "Search employees", placeholder: "Name, email, number or title", className: "w-72 rounded-lg border border-slate-200 bg-white py-1.5 pr-3 pl-8 text-sm", value: search, onChange: (e) => setSearch(e.target.value) })] }), _jsxs("select", { "aria-label": "Employment status", className: "rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm", value: status, onChange: (e) => update({ employment_status: e.target.value || null }), children: [_jsx("option", { value: "", children: "Any status" }), _jsx("option", { value: "active", children: "Active" }), _jsx("option", { value: "on_leave", children: "On leave" }), _jsx("option", { value: "terminated", children: "Terminated" })] }), organizationId && (_jsxs("span", { className: "inline-flex items-center gap-2 rounded-full bg-navy-900/5 px-3 py-1 text-xs text-navy-900", children: ["Unit: ", filterUnit.data?.name ?? "…", _jsx("button", { type: "button", "aria-label": "Clear unit filter", className: "font-bold", onClick: () => update({ organization_id: null }), children: "\u00D7" })] }))] }), _jsx(ErrorMessage, { error: employees.error, className: "mb-4" }), _jsx("div", { className: "overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm", children: _jsxs("table", { className: "min-w-full text-sm", children: [_jsx("thead", { className: "bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-4 py-2.5", children: "Employee" }), _jsx("th", { className: "px-4 py-2.5", children: "Job title" }), _jsx("th", { className: "px-4 py-2.5", children: "Unit" }), _jsx("th", { className: "px-4 py-2.5", children: "Country" }), _jsx("th", { className: "px-4 py-2.5", children: "Status" }), _jsx("th", { className: "px-4 py-2.5 text-right", children: "Compensation" })] }) }), _jsxs("tbody", { className: "divide-y divide-slate-100", children: [employees.isLoading && (_jsx("tr", { children: _jsx("td", { colSpan: 6, className: "px-4 py-6 text-center text-slate-500", children: "Loading\u2026" }) })), employees.data?.items.length === 0 && (_jsx("tr", { children: _jsx("td", { colSpan: 6, className: "px-4 py-6 text-center text-slate-500", children: "No employees match." }) })), employees.data?.items.map((e) => (_jsxs("tr", { className: "cursor-pointer hover:bg-slate-50", onClick: () => setProfileId(e.id), children: [_jsxs("td", { className: "px-4 py-2.5", children: [_jsx("button", { type: "button", className: "text-left font-medium text-slate-900 hover:underline", onClick: () => setProfileId(e.id), children: e.full_name }), _jsx("div", { className: "font-mono text-[11px] text-slate-500", children: e.employee_number })] }), _jsx("td", { className: "px-4 py-2.5 text-slate-700", children: e.job_title }), _jsx("td", { className: "px-4 py-2.5 text-slate-600", children: e.organization_name }), _jsx("td", { className: "px-4 py-2.5 font-mono text-xs text-slate-600", children: e.country_code }), _jsx("td", { className: "px-4 py-2.5", children: _jsx(StatusPill, { tone: STATUS_TONE[e.employment_status], label: humanize(e.employment_status) }) }), _jsx("td", { className: "px-4 py-2.5 text-right whitespace-nowrap text-slate-900", children: _jsx(Compensation, { employee: e }) })] }, e.id)))] })] }) }), employees.data && (_jsx("div", { className: "mt-3", children: _jsx(Pagination, { total: employees.data.total, limit: PAGE_SIZE, offset: offset, onChange: (next) => update({ offset: next ? String(next) : null }) }) })), hiring && _jsx(HireDialog, { onClose: () => setHiring(false) }), profileId && (_jsx(EmployeeProfile, { id: profileId, onClose: () => setProfileId(null), onOpen: setProfileId }, profileId))] }));
}
