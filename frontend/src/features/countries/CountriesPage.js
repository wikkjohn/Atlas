import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Plus } from "lucide-react";
import { useState } from "react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { CountryReference } from "@/features/countries/CountryReference";
import { StatusPill } from "@/components/StatusPill";
import { REGION_LABELS } from "@/services/format";
import { useCountries, useCreateCountry, useUpdateCountry } from "@/services/enterprise";
const STATUS_TONE = {
    active: "good",
    planned: "neutral",
    suspended: "warn",
};
function AddCountryDialog({ onClose }) {
    const create = useCreateCountry();
    const [form, setForm] = useState({
        iso_country_code: "",
        country_name: "",
        region: "europe",
        default_currency: "",
        default_timezone: "",
        supported_languages: "",
        operational_status: "planned",
    });
    const set = (key) => (value) => setForm({ ...form, [key]: value });
    const onSubmit = (event) => {
        event.preventDefault();
        create.mutate({
            ...form,
            supported_languages: form.supported_languages
                .split(",")
                .map((l) => l.trim())
                .filter(Boolean),
        }, { onSuccess: onClose });
    };
    return (_jsxs(Modal, { title: "Add country", onClose: onClose, footer: _jsxs(_Fragment, { children: [_jsx(Button, { variant: "secondary", onClick: onClose, children: "Cancel" }), _jsx(Button, { type: "submit", form: "add-country", disabled: create.isPending, children: create.isPending ? "Saving…" : "Add country" })] }), children: [_jsxs("form", { id: "add-country", onSubmit: onSubmit, className: "grid grid-cols-1 gap-4 sm:grid-cols-2", children: [_jsx(Field, { label: "ISO code", hint: "ISO 3166-1 alpha-2, e.g. FR", children: (p) => (_jsx("input", { ...p, className: inputClass, maxLength: 2, required: true, value: form.iso_country_code, onChange: (e) => set("iso_country_code")(e.target.value.toUpperCase()) })) }), _jsx(Field, { label: "Country name", children: (p) => (_jsx("input", { ...p, className: inputClass, required: true, value: form.country_name, onChange: (e) => set("country_name")(e.target.value) })) }), _jsx(Field, { label: "Region", children: (p) => (_jsx("select", { ...p, className: inputClass, value: form.region, onChange: (e) => set("region")(e.target.value), children: Object.entries(REGION_LABELS).map(([value, label]) => (_jsx("option", { value: value, children: label }, value))) })) }), _jsx(Field, { label: "Currency", hint: "ISO 4217, e.g. EUR", children: (p) => (_jsx("input", { ...p, className: inputClass, maxLength: 3, required: true, value: form.default_currency, onChange: (e) => set("default_currency")(e.target.value.toUpperCase()) })) }), _jsx(Field, { label: "Time zone", hint: "IANA name, e.g. Europe/Paris", children: (p) => (_jsx("input", { ...p, className: inputClass, required: true, value: form.default_timezone, onChange: (e) => set("default_timezone")(e.target.value) })) }), _jsx(Field, { label: "Languages", hint: "Comma-separated, e.g. fr-FR, en", children: (p) => (_jsx("input", { ...p, className: inputClass, required: true, value: form.supported_languages, onChange: (e) => set("supported_languages")(e.target.value) })) }), _jsx(Field, { label: "Operational status", children: (p) => (_jsxs("select", { ...p, className: inputClass, value: form.operational_status, onChange: (e) => set("operational_status")(e.target.value), children: [_jsx("option", { value: "planned", children: "Planned" }), _jsx("option", { value: "active", children: "Active" }), _jsx("option", { value: "suspended", children: "Suspended" })] })) })] }), _jsx(ErrorMessage, { error: create.error, className: "mt-4" })] }));
}
function StatusControl({ country }) {
    const update = useUpdateCountry();
    return (_jsxs("div", { className: "flex items-center gap-2", children: [_jsxs("select", { "aria-label": `Status of ${country.country_name}`, className: "rounded-md border border-slate-200 bg-white py-0.5 pr-6 pl-2 text-xs", value: country.operational_status, disabled: update.isPending, onChange: (e) => update.mutate({ id: country.id, body: { operational_status: e.target.value } }), children: [_jsx("option", { value: "active", children: "Active" }), _jsx("option", { value: "planned", children: "Planned" }), _jsx("option", { value: "suspended", children: "Suspended" })] }), update.error && _jsx("span", { className: "text-xs text-rose-600", children: update.error.message })] }));
}
export function CountriesPage() {
    const { can } = useAuth();
    const [region, setRegion] = useState("");
    const [status, setStatus] = useState("");
    const [q, setQ] = useState("");
    const [adding, setAdding] = useState(false);
    const [open, setOpen] = useState(null);
    const countries = useCountries({ region: region || undefined, operational_status: status || undefined, q: q || undefined });
    const canManage = can("countries:manage");
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Countries", description: "Country configuration registry with reference data for the 120-country footprint: currency, calendar, regulator, identity documents and address formats. A country's status governs the organizations and staff placed in it.", actions: canManage && (_jsxs(Button, { onClick: () => setAdding(true), children: [_jsx(Plus, { "aria-hidden": true, className: "h-4 w-4" }), "Add country"] })) }), _jsxs("div", { className: "mb-4 flex items-center gap-3", children: [_jsx("label", { htmlFor: "region-filter", className: "text-xs font-medium text-slate-600", children: "Region" }), _jsxs("select", { id: "region-filter", className: "rounded-lg border border-slate-200 bg-white px-2 py-1 text-sm", value: region, onChange: (e) => setRegion(e.target.value), children: [_jsx("option", { value: "", children: "All regions" }), Object.entries(REGION_LABELS).map(([value, label]) => (_jsx("option", { value: value, children: label }, value)))] }), _jsx("label", { htmlFor: "status-filter", className: "text-xs font-medium text-slate-600", children: "Status" }), _jsxs("select", { id: "status-filter", className: "rounded-lg border border-slate-200 bg-white px-2 py-1 text-sm", value: status, onChange: (e) => setStatus(e.target.value), children: [_jsx("option", { value: "", children: "Any status" }), _jsx("option", { value: "active", children: "Active" }), _jsx("option", { value: "planned", children: "Planned" }), _jsx("option", { value: "suspended", children: "Suspended" })] }), _jsx("input", { "aria-label": "Search countries", placeholder: "Name or ISO code", className: "rounded-lg border border-slate-200 bg-white px-2 py-1 text-sm", value: q, onChange: (e) => setQ(e.target.value) }), countries.data && (_jsxs("span", { className: "text-xs text-slate-500", children: [countries.data.total, " configured \u00B7 target 120"] }))] }), _jsx(ErrorMessage, { error: countries.error }), _jsx("div", { className: "overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm", children: _jsxs("table", { className: "min-w-full text-sm", children: [_jsx("thead", { className: "bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-4 py-2.5", children: "Country" }), _jsx("th", { className: "px-4 py-2.5", children: "Region" }), _jsx("th", { className: "px-4 py-2.5", children: "Currency" }), _jsx("th", { className: "px-4 py-2.5", children: "Time zone" }), _jsx("th", { className: "px-4 py-2.5", children: "Languages" }), _jsx("th", { className: "px-4 py-2.5", children: "Status" })] }) }), _jsxs("tbody", { className: "divide-y divide-slate-100", children: [countries.isLoading && (_jsx("tr", { children: _jsx("td", { colSpan: 6, className: "px-4 py-6 text-center text-slate-500", children: "Loading\u2026" }) })), countries.data?.items.map((country) => (_jsxs("tr", { children: [_jsxs("td", { className: "px-4 py-2.5 whitespace-nowrap", children: [_jsx("span", { className: "mr-2 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-700", children: country.iso_country_code }), _jsx("button", { type: "button", className: "font-medium text-slate-900 hover:underline", onClick: () => setOpen(country), children: country.country_name })] }), _jsx("td", { className: "px-4 py-2.5 text-slate-600", children: REGION_LABELS[country.region] }), _jsx("td", { className: "px-4 py-2.5 font-mono text-xs text-slate-700", children: country.default_currency }), _jsx("td", { className: "px-4 py-2.5 text-slate-600", children: country.default_timezone }), _jsx("td", { className: "px-4 py-2.5 text-slate-600", children: country.supported_languages.join(", ") }), _jsx("td", { className: "px-4 py-2.5", children: canManage ? (_jsx(StatusControl, { country: country })) : (_jsx(StatusPill, { tone: STATUS_TONE[country.operational_status], label: country.operational_status })) })] }, country.id)))] })] }) }), adding && _jsx(AddCountryDialog, { onClose: () => setAdding(false) }), open && _jsx(CountryReference, { country: open, onClose: () => setOpen(null) })] }));
}
