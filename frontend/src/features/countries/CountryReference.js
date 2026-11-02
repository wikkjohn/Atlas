import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Modal } from "@/components/Modal";
import { CountryRulesSection } from "@/features/countries/CountryRulesSection";
import { useCheckCountryValue, useCountryCalendar, useCountrySamples, useCurrencies } from "@/services/enterprise";
const WEEKDAYS = ["", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
function Term({ label, children }) {
    return (_jsxs("div", { children: [_jsx("dt", { className: "text-xs text-slate-500", children: label }), _jsx("dd", { className: "text-sm text-slate-900", children: children })] }));
}
function CalendarSection({ country }) {
    const [year, setYear] = useState(2026);
    const calendar = useCountryCalendar(country.id, year);
    return (_jsxs("section", { "aria-label": "Holiday calendar", className: "space-y-2", children: [_jsxs("div", { className: "flex items-center gap-2", children: [_jsx("h3", { className: "text-sm font-semibold text-slate-900", children: "Public holidays" }), _jsx("select", { "aria-label": "Year", className: "rounded-md border border-slate-200 px-1.5 py-0.5 text-xs", value: year, onChange: (e) => setYear(Number(e.target.value)), children: [2025, 2026, 2027, 2028].map((y) => (_jsx("option", { children: y }, y))) }), calendar.data && _jsxs("span", { role: "status", className: "text-xs text-slate-500", children: [calendar.data.business_days, " business days"] })] }), _jsx(ErrorMessage, { error: calendar.error }), calendar.data && calendar.data.holidays.length === 0 && _jsx("p", { className: "text-xs text-slate-500", children: "No holidays computed from rules." }), _jsx("ul", { className: "grid grid-cols-1 gap-x-4 text-xs sm:grid-cols-2", children: calendar.data?.holidays.map((h) => (_jsxs("li", { className: "flex gap-2", children: [_jsx("span", { className: "font-mono text-slate-500", children: h.date }), _jsxs("span", { className: "text-slate-800", children: [h.name, h.observed !== h.date && _jsxs("span", { className: "text-slate-500", children: [" (observed ", h.observed, ")"] })] })] }, h.date + h.name))) })] }));
}
function CheckSection({ country }) {
    const check = useCheckCountryValue(country.id);
    const [kind, setKind] = useState("postal_code");
    const [value, setValue] = useState("");
    const onSubmit = (event) => {
        event.preventDefault();
        check.mutate({ kind, value });
    };
    return (_jsxs("section", { "aria-label": "Check a value", className: "space-y-2", children: [_jsx("h3", { className: "text-sm font-semibold text-slate-900", children: "Check a value" }), _jsxs("form", { onSubmit: onSubmit, className: "flex flex-wrap items-center gap-2", children: [_jsxs("select", { "aria-label": "Kind", className: "rounded-md border border-slate-200 px-2 py-1 text-xs", value: kind, onChange: (e) => setKind(e.target.value), children: [_jsx("option", { value: "postal_code", children: "Postal code" }), _jsx("option", { value: "national_id", children: "National ID" }), _jsx("option", { value: "passport", children: "Passport" })] }), _jsx("input", { "aria-label": "Value", className: "rounded-md border border-slate-200 px-2 py-1 text-xs", value: value, onChange: (e) => setValue(e.target.value), required: true }), _jsx(Button, { size: "sm", variant: "secondary", type: "submit", disabled: check.isPending, children: "Check" }), check.data && (_jsx("span", { role: "status", className: `text-xs ${check.data.valid ? "text-emerald-700" : "text-rose-700"}`, children: check.data.valid
                            ? `${check.data.value} matches the format`
                            : check.data.masks.length
                                ? `${check.data.value} does not match ${check.data.masks.join(" or ")}`
                                : "No format is defined for this country" }))] }), _jsx(ErrorMessage, { error: check.error })] }));
}
function SamplesSection({ country }) {
    const [seed, setSeed] = useState(0);
    const samples = useCountrySamples(country.id, seed);
    return (_jsxs("section", { "aria-label": "Synthetic samples", className: "space-y-2", children: [_jsxs("div", { className: "flex items-center gap-2", children: [_jsx("h3", { className: "text-sm font-semibold text-slate-900", children: "Synthetic samples" }), _jsx(Button, { size: "sm", variant: "secondary", onClick: () => setSeed(seed + 1), children: "New samples" })] }), _jsx(ErrorMessage, { error: samples.error }), _jsx("ul", { className: "grid grid-cols-1 gap-2 text-xs sm:grid-cols-3", children: samples.data?.map((s, i) => (_jsxs("li", { className: "rounded-md border border-slate-200 p-2", children: [s.national_id && _jsxs("div", { className: "font-mono", children: ["ID ", s.national_id] }), _jsxs("div", { className: "font-mono", children: ["Passport ", s.passport] }), _jsx("div", { className: "mt-1 text-slate-600", children: s.address_lines.map((line) => (_jsx("div", { children: line }, line))) })] }, i))) })] }));
}
/** A country's reference data: identifiers, money, calendar, documents and addresses. */
export function CountryReference({ country, onClose }) {
    const currencies = useCurrencies();
    const currency = currencies.data?.find((c) => c.code === country.default_currency);
    const address = country.address_format;
    return (_jsx(Modal, { wide: true, title: `${country.country_name} (${country.iso_country_code})`, onClose: onClose, children: _jsxs("div", { className: "space-y-5", children: [_jsxs("dl", { className: "grid grid-cols-2 gap-3 sm:grid-cols-4", children: [_jsxs(Term, { label: "ISO codes", children: [country.iso_country_code, " / ", country.iso_alpha3 ?? "—"] }), _jsxs(Term, { label: "Currency", children: [country.default_currency, currency && ` · ${currency.name}, ${currency.minor_units} decimal${currency.minor_units === 1 ? "" : "s"}`] }), _jsx(Term, { label: "Calling code", children: country.calling_code ?? "—" }), _jsx(Term, { label: "Time zone", children: country.default_timezone }), _jsx(Term, { label: "Weekend", children: (country.weekend_days ?? []).map((d) => WEEKDAYS[d]).join(" and ") || "—" }), _jsx(Term, { label: "Languages", children: country.supported_languages.join(", ") }), _jsx(Term, { label: "Banking supervisor", children: country.regulator ? `${country.regulator.name} (${country.regulator.abbreviation})` : "—" }), _jsx(Term, { label: "Reference data", children: country.reference_version ?? "not loaded" })] }), _jsxs("section", { "aria-label": "Identity documents", className: "space-y-1", children: [_jsx("h3", { className: "text-sm font-semibold text-slate-900", children: "Identity documents" }), _jsx("table", { className: "text-xs", children: _jsx("tbody", { children: (country.identity_documents ?? []).map((d) => (_jsxs("tr", { children: [_jsx("td", { className: "pr-4 text-slate-800", children: d.name }), _jsx("td", { className: "pr-4 font-mono text-slate-600", children: d.mask }), _jsxs("td", { className: "font-mono text-slate-500", children: ["e.g. ", d.example] })] }, d.type))) }) })] }), address && (_jsxs("section", { "aria-label": "Address format", className: "space-y-1", children: [_jsx("h3", { className: "text-sm font-semibold text-slate-900", children: "Address format" }), _jsx("p", { className: "font-mono text-xs text-slate-600", children: address.lines.join(" ⏎ ") }), _jsxs("p", { className: "text-xs text-slate-600", children: [address.postal_code_masks.length
                                    ? `Postal codes: ${address.postal_code_masks.join(", ")} (e.g. ${address.postal_code_example})`
                                    : "No postal codes in use.", address.requires_region && " A state or province is part of the address."] })] })), _jsx(CountryRulesSection, { country: country }), _jsx(CalendarSection, { country: country }), _jsx(CheckSection, { country: country }), _jsx(SamplesSection, { country: country }), (country.reference_notes ?? []).length > 0 && (_jsx("ul", { "aria-label": "Notes", className: "list-disc pl-5 text-xs text-slate-500", children: country.reference_notes.map((n) => (_jsx("li", { children: n }, n))) })), _jsx("p", { className: "text-xs text-slate-400", children: "Compiled for the simulation: masks approximate real formats (9 a digit, A a letter, X either); regulators and holidays are not authoritative." })] }) }));
}
