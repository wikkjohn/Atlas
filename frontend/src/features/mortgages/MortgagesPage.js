import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { formatExactMoney, humanize, toMinorUnits } from "@/services/format";
import { useMortgageProducts, useMortgageSummary, useOfferAction, useOffers, useProperties, useQuote, useRegisterProperty, useRequestOffer, useValueProperty, } from "@/services/mortgages";
const OFFER_TONE = {
    pending: "warn",
    offered: "good",
    accepted: "good",
    completed: "neutral",
    declined: "bad",
    withdrawn: "neutral",
};
const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const percent = (bps) => `${(bps / 100).toFixed(2)} %`;
function Field({ label, children }) {
    return (_jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: [label, children] }));
}
function RegisterForm() {
    const register = useRegisterProperty();
    const [customer, setCustomer] = useState("");
    const [type, setType] = useState("house");
    const [price, setPrice] = useState("");
    const onSubmit = (event) => {
        event.preventDefault();
        register.mutate({ customer_number: customer.trim(), property_type: type, purchase_price_major: Number(price) }, { onSuccess: () => setPrice("") });
    };
    return (_jsxs("form", { "aria-label": "Register a property", onSubmit: onSubmit, className: "mb-3 flex flex-wrap items-end gap-2 text-xs", children: [_jsx(Field, { label: "Customer", children: _jsx("input", { "aria-label": "Customer", required: true, placeholder: "CUS-0000001", className: `w-32 ${INPUT}`, value: customer, onChange: (e) => setCustomer(e.target.value) }) }), _jsx(Field, { label: "Type", children: _jsxs("select", { "aria-label": "Property type", className: INPUT, value: type, onChange: (e) => setType(e.target.value), children: [_jsx("option", { value: "house", children: "House" }), _jsx("option", { value: "flat", children: "Flat" })] }) }), _jsx(Field, { label: "Purchase price", children: _jsx("input", { "aria-label": "Purchase price", required: true, inputMode: "decimal", className: `w-32 ${INPUT}`, value: price, onChange: (e) => setPrice(e.target.value) }) }), _jsx(Button, { size: "sm", type: "submit", disabled: register.isPending, children: "Register" }), _jsx(ErrorMessage, { error: register.error })] }));
}
function SurveyForm({ properties }) {
    const value = useValueProperty();
    const [id, setId] = useState("");
    const [amount, setAmount] = useState("");
    const selected = properties.find((p) => p.id === id) ?? properties[0];
    const onSubmit = (event) => {
        event.preventDefault();
        if (!selected)
            return;
        value.mutate({ id: selected.id, method: "surveyor", value: toMinorUnits(Number(amount), selected.currency) }, { onSuccess: () => setAmount("") });
    };
    return (_jsxs("form", { "aria-label": "Surveyor valuation", onSubmit: onSubmit, className: "mt-3 flex flex-wrap items-end gap-2 text-xs", children: [_jsx(Field, { label: "Property", children: _jsx("select", { "aria-label": "Surveyed property", className: INPUT, value: selected?.id ?? "", onChange: (e) => setId(e.target.value), children: properties.map((p) => (_jsxs("option", { value: p.id, children: [p.property_number, " (", p.currency, ")"] }, p.id))) }) }), _jsx(Field, { label: "Surveyed value", children: _jsx("input", { "aria-label": "Surveyed value", required: true, inputMode: "decimal", className: `w-32 ${INPUT}`, value: amount, onChange: (e) => setAmount(e.target.value) }) }), _jsx(Button, { size: "sm", type: "submit", disabled: value.isPending || !selected, children: "Record survey" }), _jsx(ErrorMessage, { error: value.error })] }));
}
function PropertiesPanel() {
    const { can } = useAuth();
    const properties = useProperties();
    const value = useValueProperty();
    const items = properties.data?.items ?? [];
    return (_jsxs(Panel, { title: "Properties and valuations", subtitle: "The automated (desktop) model supports loans up to 75 % loan-to-value; above that a surveyor values the property. Offers need a valuation from the last 180 days.", children: [can("accounts:transact") && _jsx(RegisterForm, {}), _jsx(ErrorMessage, { error: properties.error ?? value.error }), _jsx("table", { "aria-label": "Properties", className: "min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [items.map((p) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: p.property_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [p.customer_name, " \u00B7 ", humanize(p.property_type), " \u00B7 ", p.address] }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: formatExactMoney(p.purchase_price, p.currency) }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [p.latest_valuation
                                            ? `${p.latest_valuation.method} ${formatExactMoney(p.latest_valuation.value, p.currency)} on ${p.latest_valuation.valued_on}`
                                            : "not valued", p.charged_loan_number && _jsxs("span", { className: "text-slate-900", children: [" \u00B7 charged: ", p.charged_loan_number] })] }), _jsx("td", { className: "px-2 py-1.5 text-right", children: can("accounts:transact") && (_jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Desktop valuation ${p.property_number}`, onClick: () => value.mutate({ id: p.id, method: "desktop" }), children: "Desktop valuation" })) })] }, p.id))), properties.data && items.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No properties registered yet." }) }))] }) }), can("mortgages:manage") && items.length > 0 && _jsx(SurveyForm, { properties: items })] }));
}
const EMPTY = { customer: "", property: "", product: "home-75", account: "", amount: "", years: "25", income: "" };
function ApplicationPanel() {
    const quote = useQuote();
    const apply = useRequestOffer();
    const products = useMortgageProducts();
    const properties = useProperties();
    const [form, setForm] = useState(EMPTY);
    // Amounts are entered in major units of the property's currency.
    const currency = properties.data?.items.find((p) => p.property_number === form.property.trim().toUpperCase())?.currency ?? "USD";
    const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
    const body = () => ({
        customer_number: form.customer.trim(),
        property_number: form.property.trim(),
        product_code: form.product,
        account_number: form.account.trim(),
        loan_amount: toMinorUnits(Number(form.amount), currency),
        term_years: Number(form.years),
        declared_monthly_income: toMinorUnits(Number(form.income), currency),
    });
    const onSubmit = (event) => {
        event.preventDefault();
        quote.mutate(body());
    };
    const result = quote.data;
    return (_jsxs(Panel, { title: "Mortgage application", subtitle: "Check eligibility shows every lending rule; Apply records the application for an underwriter other than you to decide.", children: [_jsxs("form", { "aria-label": "Mortgage application", onSubmit: onSubmit, className: "flex flex-wrap items-end gap-2 text-xs", children: [_jsx(Field, { label: "Customer", children: _jsx("input", { "aria-label": "Applicant", required: true, className: `w-32 ${INPUT}`, value: form.customer, onChange: set("customer") }) }), _jsx(Field, { label: "Property", children: _jsx("input", { "aria-label": "Property number", required: true, placeholder: "PRP-0000001", className: `w-32 ${INPUT}`, value: form.property, onChange: set("property") }) }), _jsx(Field, { label: "Product", children: _jsx("select", { "aria-label": "Product", className: INPUT, value: form.product, onChange: set("product"), children: (products.data ?? []).map((p) => (_jsxs("option", { value: p.product_code, children: [p.name, " (up to ", p.max_ltv_bps / 100, " %, ", percent(p.annual_rate_bps), ")"] }, p.product_code))) }) }), _jsx(Field, { label: "Account", children: _jsx("input", { "aria-label": "Drawdown account", required: true, className: `w-40 ${INPUT}`, value: form.account, onChange: set("account") }) }), _jsx(Field, { label: "Loan", children: _jsx("input", { "aria-label": "Loan amount", required: true, inputMode: "decimal", className: `w-28 ${INPUT}`, value: form.amount, onChange: set("amount") }) }), _jsx(Field, { label: "Years", children: _jsx("input", { "aria-label": "Term in years", required: true, inputMode: "numeric", className: `w-14 ${INPUT}`, value: form.years, onChange: set("years") }) }), _jsx(Field, { label: "Monthly income", children: _jsx("input", { "aria-label": "Declared monthly income", required: true, inputMode: "decimal", className: `w-28 ${INPUT}`, value: form.income, onChange: set("income") }) }), _jsx(Button, { size: "sm", type: "submit", variant: "secondary", disabled: quote.isPending, children: "Check eligibility" }), _jsx(Button, { size: "sm", type: "button", disabled: apply.isPending, onClick: () => apply.mutate(body(), { onSuccess: () => setForm(EMPTY) }), children: "Apply" })] }), _jsx(ErrorMessage, { error: quote.error ?? apply.error }), apply.data && (_jsxs("p", { role: "status", className: "mt-2 text-sm text-emerald-700", children: [apply.data.offer_number, " recorded: waiting for an underwriter."] })), result && (_jsxs("div", { "aria-label": "Eligibility", className: "mt-3 text-xs", children: [_jsxs("p", { className: `mb-1 text-sm font-medium ${result.eligible ? "text-emerald-700" : "text-rose-700"}`, children: [result.eligible ? "Eligible" : "Not eligible", " \u00B7 loan-to-value ", percent(result.ltv_bps), " \u00B7 ", formatExactMoney(result.monthly_payment, result.currency), " a month at ", percent(result.annual_rate_bps), " \u00B7 score ", result.credit_score] }), _jsx("ul", { className: "space-y-0.5", children: result.checks.map((c) => (_jsxs("li", { className: c.passed ? "text-slate-600" : "text-rose-700", children: [c.passed ? "✓" : "✗", " ", humanize(c.rule), ": ", c.detail] }, c.rule))) })] }))] }));
}
function OffersPanel() {
    const { can } = useAuth();
    const offers = useOffers();
    const action = useOfferAction();
    const act = (o, kind, approve) => action.mutate({ id: o.id, action: kind, approve });
    return (_jsxs(Panel, { title: "Offers", subtitle: "An underwriter other than the person who took the application decides; an offer is valid for 90 days. Completion draws the loan down into the customer's account and charges it on the property.", children: [_jsx(ErrorMessage, { error: offers.error ?? action.error }), _jsx("table", { "aria-label": "Offers", className: "min-w-full text-sm", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: offers.data?.items.map((o) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: o.offer_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [o.customer_number, " \u00B7 ", o.property_number, " \u00B7 ", o.product_code, " \u00B7 ", o.term_months / 12, " years \u00B7 LTV ", percent(o.ltv_bps), " \u00B7", " ", formatExactMoney(o.monthly_payment, o.currency), " a month", o.expires_on && o.status === "offered" && ` · until ${o.expires_on}`, o.loan_number && ` · ${o.loan_number}`] }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: formatExactMoney(o.loan_amount, o.currency) }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: o.expired ? "bad" : OFFER_TONE[o.status], label: o.expired ? "expired" : o.status }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: _jsxs("div", { className: "flex justify-end gap-1", children: [o.status === "pending" && can("loans:approve") && (_jsxs(_Fragment, { children: [_jsx(Button, { size: "sm", "aria-label": `Approve ${o.offer_number}`, onClick: () => act(o, "decide", true), children: "Approve" }), _jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Decline ${o.offer_number}`, onClick: () => act(o, "decide", false), children: "Decline" })] })), o.status === "offered" && !o.expired && can("accounts:transact") && (_jsx(Button, { size: "sm", "aria-label": `Accept ${o.offer_number}`, onClick: () => act(o, "accept"), children: "Accept" })), o.status === "accepted" && can("loans:approve") && (_jsx(Button, { size: "sm", "aria-label": `Complete ${o.offer_number}`, onClick: () => act(o, "complete"), children: "Complete" }))] }) })] }, o.id))) }) })] }));
}
/** Mortgages (Phase 33): properties, valuations, applications, offers and completion. */
export function MortgagesPage() {
    const { can } = useAuth();
    const summary = useMortgageSummary();
    const products = useMortgageProducts();
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Mortgages", description: "Secured lending: properties and their valuations, decisions in principle against every lending rule, offers decided by a second person, and completion into an ordinary loan charged on the property." }), summary.data && (_jsx("dl", { "aria-label": "Mortgage summary", className: "mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5", children: [
                    ["Properties", summary.data.properties],
                    ["Pending", summary.data.pending],
                    ["Offered", summary.data.offered],
                    ["Accepted", summary.data.accepted],
                    ["Active mortgages", summary.data.active_mortgages],
                ].map(([label, value]) => (_jsxs("div", { className: "rounded-lg border border-slate-200 bg-white p-3", children: [_jsx("dt", { className: "text-xs text-slate-500", children: label }), _jsx("dd", { className: "text-lg font-semibold text-slate-900", children: value })] }, label))) })), _jsxs("div", { className: "space-y-6", children: [_jsxs(Panel, { title: "Products", subtitle: "Loan sizes are set in US dollars and converted to each property's currency.", children: [_jsx(ErrorMessage, { error: products.error }), _jsx("table", { "aria-label": "Mortgage products", className: "min-w-full text-sm", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: products.data?.map((p) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-medium", children: p.name }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: ["up to ", p.max_ltv_bps / 100, " % loan-to-value \u00B7 ", percent(p.annual_rate_bps), " fixed \u00B7 up to ", p.max_term_years, " years \u00B7 US$", p.min_loan_usd.toLocaleString("en-US"), "\u2013", p.max_loan_usd.toLocaleString("en-US")] })] }, p.product_code))) }) })] }), _jsx(PropertiesPanel, {}), can("accounts:transact") && _jsx(ApplicationPanel, {}), _jsx(OffersPanel, {})] })] }));
}
