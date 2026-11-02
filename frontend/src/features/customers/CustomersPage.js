import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Search, UserPlus } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "@/app/auth";
import { ACCOUNT_TYPE_LABELS, AccountStatusBadge, KycBadge, RequestStatusBadge, RiskBadge, } from "@/components/BankingBadges";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { useAccountRequests, useAccounts, useCreateCustomer, useCustomer, useCustomers, useEligibility, useReviewCustomer, useSubmitAccountRequest, } from "@/services/banking";
import { useCountries } from "@/services/enterprise";
import { formatMoney, humanize } from "@/services/format";
const PAGE_SIZE = 25;
// Mirrors KYC_TRANSITIONS in backend/app/modules/customers/models.py.
const KYC_NEXT = {
    not_started: ["pending"],
    pending: ["verified", "rejected"],
    verified: ["pending"],
    rejected: ["pending"],
};
const KYC_ACTION = {
    pending: "Start review",
    verified: "Verify",
    rejected: "Reject KYC",
    not_started: "",
};
const ACCOUNT_TYPES = {
    individual: ["current", "savings"],
    business: ["business_current"],
};
function OnboardDialog({ onClose }) {
    const create = useCreateCustomer();
    const countries = useCountries({ operational_status: "active" });
    const [form, setForm] = useState({
        customer_type: "individual",
        name: "",
        date_of_birth_or_incorporation: "",
        country_id: "",
    });
    const set = (key) => (value) => setForm({ ...form, [key]: value });
    const business = form.customer_type === "business";
    return (_jsxs(Modal, { title: "Onboard customer", onClose: onClose, footer: _jsxs(_Fragment, { children: [_jsx(Button, { variant: "secondary", onClick: onClose, children: "Cancel" }), _jsx(Button, { type: "submit", form: "onboard", disabled: create.isPending, children: create.isPending ? "Saving…" : "Onboard" })] }), children: [_jsxs("form", { id: "onboard", className: "grid grid-cols-1 gap-4 sm:grid-cols-2", onSubmit: (e) => {
                    e.preventDefault();
                    create.mutate(form, { onSuccess: onClose });
                }, children: [_jsx(Field, { label: "Customer type", children: (p) => (_jsxs("select", { ...p, className: inputClass, value: form.customer_type, onChange: (e) => set("customer_type")(e.target.value), children: [_jsx("option", { value: "individual", children: "Individual" }), _jsx("option", { value: "business", children: "Business" })] })) }), _jsx(Field, { label: "Country", hint: "Only active countries can onboard customers.", children: (p) => (_jsxs("select", { ...p, className: inputClass, required: true, value: form.country_id, onChange: (e) => set("country_id")(e.target.value), children: [_jsx("option", { value: "", children: "Select\u2026" }), countries.data?.items.map((c) => (_jsx("option", { value: c.id, children: c.country_name }, c.id)))] })) }), _jsx(Field, { label: business ? "Registered name" : "Full name", children: (p) => (_jsx("input", { ...p, className: inputClass, required: true, minLength: 2, value: form.name, onChange: (e) => set("name")(e.target.value) })) }), _jsx(Field, { label: business ? "Date of incorporation" : "Date of birth", children: (p) => (_jsx("input", { ...p, type: "date", className: inputClass, required: true, value: form.date_of_birth_or_incorporation, onChange: (e) => set("date_of_birth_or_incorporation")(e.target.value) })) })] }), _jsx("p", { className: "mt-3 text-xs text-slate-500", children: "All customers are synthetic. New customers start with KYC not started and no risk rating." }), _jsx(ErrorMessage, { error: create.error, className: "mt-4" })] }));
}
function ReviewPanel({ customer }) {
    const review = useReviewCustomer(customer.id);
    const [risk, setRisk] = useState(customer.risk_rating === "unrated" ? "low" : customer.risk_rating);
    const [note, setNote] = useState("");
    const decide = (kyc_status) => review.mutate({
        kyc_status,
        // A rating is required to verify; also sent when only the rating changes.
        risk_rating: kyc_status === "verified" || kyc_status === null ? risk : undefined,
        note: note || null,
    });
    return (_jsxs("section", { "aria-label": "KYC review", className: "space-y-3 rounded-lg border border-slate-200 p-4", children: [_jsx("h4", { className: "text-xs font-semibold tracking-wide text-slate-500 uppercase", children: "KYC review" }), _jsxs("div", { className: "grid grid-cols-1 gap-3 sm:grid-cols-2", children: [_jsx(Field, { label: "Risk rating", children: (p) => (_jsxs("select", { ...p, className: inputClass, value: risk, onChange: (e) => setRisk(e.target.value), children: [_jsx("option", { value: "low", children: "Low" }), _jsx("option", { value: "medium", children: "Medium" }), _jsx("option", { value: "high", children: "High" })] })) }), _jsx(Field, { label: "Note", children: (p) => _jsx("input", { ...p, className: inputClass, value: note, onChange: (e) => setNote(e.target.value) }) })] }), _jsxs("div", { className: "flex flex-wrap gap-2", children: [KYC_NEXT[customer.kyc_status].map((next) => (_jsx(Button, { size: "sm", variant: next === "rejected" ? "danger" : "primary", disabled: review.isPending, onClick: () => decide(next), children: KYC_ACTION[next] }, next))), _jsx(Button, { size: "sm", variant: "secondary", disabled: review.isPending, onClick: () => decide(null), children: "Save risk rating" })] }), _jsx(ErrorMessage, { error: review.error })] }));
}
function RequestAccountPanel({ customer }) {
    const options = ACCOUNT_TYPES[customer.customer_type];
    const [accountType, setAccountType] = useState(options[0]);
    const eligibility = useEligibility(customer.id, accountType);
    const submit = useSubmitAccountRequest();
    return (_jsxs("section", { "aria-label": "Request an account", className: "space-y-3 rounded-lg border border-slate-200 p-4", children: [_jsx("h4", { className: "text-xs font-semibold tracking-wide text-slate-500 uppercase", children: "Request an account" }), _jsxs("div", { className: "flex flex-wrap items-end gap-3", children: [_jsx(Field, { label: "Account type", children: (p) => (_jsx("select", { ...p, className: inputClass, value: accountType, onChange: (e) => setAccountType(e.target.value), children: options.map((t) => (_jsxs("option", { value: t, children: [ACCOUNT_TYPE_LABELS[t], " (", customer.currency, ")"] }, t))) })) }), _jsx(Button, { disabled: !eligibility.data?.eligible || submit.isPending, onClick: () => submit.mutate({ customer_id: customer.id, account_type: accountType }), children: "Submit for approval" })] }), eligibility.data && !eligibility.data.eligible && (_jsx("ul", { "aria-label": "Eligibility issues", className: "list-disc space-y-0.5 pl-5 text-xs text-amber-800", children: eligibility.data.reasons.map((r) => (_jsx("li", { children: r }, r))) })), submit.isSuccess && (_jsx("p", { role: "status", className: "text-xs text-emerald-700", children: "Request submitted. Another authorized employee must approve it." })), _jsx(ErrorMessage, { error: submit.error })] }));
}
function CustomerProfile({ id, onClose }) {
    const { can } = useAuth();
    const customer = useCustomer(id);
    const accounts = useAccounts({ customer_id: id, limit: 50 });
    const requests = useAccountRequests({ customer_id: id, limit: 50 });
    const c = customer.data;
    return (_jsxs(Modal, { wide: true, title: "Customer profile", onClose: onClose, children: [_jsx(ErrorMessage, { error: customer.error }), c && (_jsxs("div", { className: "space-y-5", children: [_jsxs("div", { className: "flex flex-wrap items-start justify-between gap-3", children: [_jsxs("div", { children: [_jsx("h3", { className: "text-lg font-semibold text-slate-900", children: c.name }), _jsxs("p", { className: "font-mono text-xs text-slate-500", children: [c.customer_number, " \u00B7 ", humanize(c.customer_type), " \u00B7 ", c.country_code, " \u00B7", " ", c.customer_type === "business" ? "incorporated" : "born", " ", c.date_of_birth_or_incorporation] })] }), _jsxs("div", { className: "flex gap-2", children: [_jsx(KycBadge, { status: c.kyc_status }), _jsx(RiskBadge, { rating: c.risk_rating })] })] }), _jsxs("section", { "aria-label": "Accounts", children: [_jsx("h4", { className: "mb-1.5 text-xs font-semibold tracking-wide text-slate-500 uppercase", children: "Accounts" }), accounts.data?.items.length === 0 && _jsx("p", { className: "text-sm text-slate-500", children: "No accounts." }), _jsx("ul", { className: "divide-y divide-slate-100 text-sm", children: accounts.data?.items.map((a) => (_jsxs("li", { className: "flex items-center justify-between gap-3 py-1.5", children: [_jsx(Link, { to: `/accounts?account=${a.id}`, className: "font-mono text-navy-700 hover:underline", children: a.account_number }), _jsx("span", { className: "text-slate-600", children: ACCOUNT_TYPE_LABELS[a.account_type] }), _jsx(AccountStatusBadge, { status: a.status }), _jsx("span", { className: "font-medium text-slate-900", children: formatMoney(a.balance, a.currency) })] }, a.id))) })] }), requests.data && requests.data.items.length > 0 && (_jsxs("section", { "aria-label": "Account requests", children: [_jsx("h4", { className: "mb-1.5 text-xs font-semibold tracking-wide text-slate-500 uppercase", children: "Account requests" }), _jsx("ul", { className: "divide-y divide-slate-100 text-sm", children: requests.data.items.map((r) => (_jsxs("li", { className: "flex items-center justify-between gap-3 py-1.5", children: [_jsx("span", { children: ACCOUNT_TYPE_LABELS[r.account_type] }), _jsxs("span", { className: "text-xs text-slate-500", children: ["by ", r.requested_by_username] }), _jsx(RequestStatusBadge, { status: r.status })] }, r.id))) })] })), can("customers:review") && _jsx(ReviewPanel, { customer: c }, c.updated_at), can("accounts:request") && _jsx(RequestAccountPanel, { customer: c })] }))] }));
}
export function CustomersPage() {
    const { can } = useAuth();
    const [params, setParams] = useSearchParams();
    const [search, setSearch] = useState(params.get("q") ?? "");
    const [onboarding, setOnboarding] = useState(false);
    const profileId = params.get("customer");
    const offset = Number(params.get("offset") ?? 0);
    const filters = {
        q: params.get("q") ?? undefined,
        kyc_status: params.get("kyc_status") ?? undefined,
        risk_rating: params.get("risk_rating") ?? undefined,
        customer_type: params.get("customer_type") ?? undefined,
    };
    const customers = useCustomers({ ...filters, limit: PAGE_SIZE, offset });
    const update = (changes) => {
        const next = new URLSearchParams(params);
        for (const [key, value] of Object.entries(changes)) {
            if (value)
                next.set(key, value);
            else
                next.delete(key);
        }
        if (!("offset" in changes) && !("customer" in changes))
            next.delete("offset");
        setParams(next);
    };
    const filter = (label, key, options) => (_jsxs("select", { "aria-label": label, className: "rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm", value: params.get(key) ?? "", onChange: (e) => update({ [key]: e.target.value || null }), children: [_jsxs("option", { value: "", children: [label, ": any"] }), options.map(([value, text]) => (_jsx("option", { value: value, children: text }, value)))] }));
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Customers", description: "Synthetic individual and business customers. KYC and risk decisions are made by compliance reviewers.", actions: can("customers:manage") && (_jsxs(Button, { onClick: () => setOnboarding(true), children: [_jsx(UserPlus, { "aria-hidden": true, className: "h-4 w-4" }), "Onboard customer"] })) }), _jsxs("div", { className: "mb-4 flex flex-wrap items-center gap-3", children: [_jsxs("form", { role: "search", className: "relative", onSubmit: (e) => {
                            e.preventDefault();
                            update({ q: search.trim() || null });
                        }, children: [_jsx(Search, { "aria-hidden": true, className: "pointer-events-none absolute top-2 left-2.5 h-4 w-4 text-slate-400" }), _jsx("input", { "aria-label": "Search customers", placeholder: "Name or customer number", className: "w-64 rounded-lg border border-slate-200 bg-white py-1.5 pr-3 pl-8 text-sm", value: search, onChange: (e) => setSearch(e.target.value) })] }), filter("KYC", "kyc_status", [
                        ["not_started", "Not started"],
                        ["pending", "Pending"],
                        ["verified", "Verified"],
                        ["rejected", "Rejected"],
                    ]), filter("Risk", "risk_rating", [
                        ["unrated", "Unrated"],
                        ["low", "Low"],
                        ["medium", "Medium"],
                        ["high", "High"],
                    ]), filter("Type", "customer_type", [
                        ["individual", "Individual"],
                        ["business", "Business"],
                    ])] }), _jsx(ErrorMessage, { error: customers.error, className: "mb-4" }), _jsx("div", { className: "overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm", children: _jsxs("table", { className: "min-w-full text-sm", children: [_jsx("thead", { className: "bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-4 py-2.5", children: "Customer" }), _jsx("th", { className: "px-4 py-2.5", children: "Type" }), _jsx("th", { className: "px-4 py-2.5", children: "Country" }), _jsx("th", { className: "px-4 py-2.5", children: "KYC" }), _jsx("th", { className: "px-4 py-2.5", children: "Risk" })] }) }), _jsxs("tbody", { className: "divide-y divide-slate-100", children: [customers.data?.items.length === 0 && (_jsx("tr", { children: _jsx("td", { colSpan: 5, className: "px-4 py-6 text-center text-slate-500", children: "No customers match." }) })), customers.data?.items.map((c) => (_jsxs("tr", { className: "cursor-pointer hover:bg-slate-50", onClick: () => update({ customer: c.id }), children: [_jsxs("td", { className: "px-4 py-2.5", children: [_jsx("button", { type: "button", className: "text-left font-medium text-slate-900 hover:underline", children: c.name }), _jsx("div", { className: "font-mono text-[11px] text-slate-500", children: c.customer_number })] }), _jsx("td", { className: "px-4 py-2.5 text-slate-600", children: humanize(c.customer_type) }), _jsx("td", { className: "px-4 py-2.5 font-mono text-xs text-slate-600", children: c.country_code }), _jsx("td", { className: "px-4 py-2.5", children: _jsx(KycBadge, { status: c.kyc_status }) }), _jsx("td", { className: "px-4 py-2.5", children: _jsx(RiskBadge, { rating: c.risk_rating }) })] }, c.id)))] })] }) }), customers.data && (_jsx("div", { className: "mt-3", children: _jsx(Pagination, { total: customers.data.total, limit: PAGE_SIZE, offset: offset, onChange: (next) => update({ offset: next ? String(next) : null }) }) })), onboarding && _jsx(OnboardDialog, { onClose: () => setOnboarding(false) }), profileId && _jsx(CustomerProfile, { id: profileId, onClose: () => update({ customer: null }) }, profileId)] }));
}
