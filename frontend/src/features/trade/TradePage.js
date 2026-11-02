import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { formatExactMoney, humanize, toMinorUnits } from "@/services/format";
import { INSTRUMENTS_PAGE, useDecideDemand, useDemands, useInstrumentAction, useInstruments, useReceiveDemand, useRequestInstrument, useTradeSummary, } from "@/services/trade";
import { DISCREPANCIES } from "@/types/trade";
const TONE = { requested: "warn", issued: "good", declined: "neutral", paid: "neutral", expired: "neutral" };
const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const KIND = { letter_of_credit: "Letter of credit", guarantee: "Guarantee" };
function Field({ label, children }) {
    return (_jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: [label, children] }));
}
const EMPTY = { kind: "letter_of_credit", customer: "", account: "", beneficiary: "", country: "", amount: "", expires: "", purpose: "" };
function RequestForm() {
    const request = useRequestInstrument();
    const [form, setForm] = useState(EMPTY);
    const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
    const onSubmit = (event) => {
        event.preventDefault();
        request.mutate({
            kind: form.kind,
            customer_number: form.customer.trim(),
            account_number: form.account.trim(),
            beneficiary_name: form.beneficiary,
            beneficiary_country: form.country.trim().toUpperCase(),
            amount_major: Number(form.amount),
            expires_on: form.expires,
            purpose: form.purpose || "Trade",
        }, { onSuccess: () => setForm(EMPTY) });
    };
    return (_jsxs("form", { "aria-label": "Request an instrument", onSubmit: onSubmit, className: "mb-3 flex flex-wrap items-end gap-2 text-xs", children: [_jsx(Field, { label: "Kind", children: _jsxs("select", { "aria-label": "Kind", className: INPUT, value: form.kind, onChange: set("kind"), children: [_jsx("option", { value: "letter_of_credit", children: "Letter of credit" }), _jsx("option", { value: "guarantee", children: "Guarantee" })] }) }), _jsx(Field, { label: "Business customer", children: _jsx("input", { "aria-label": "Business customer", required: true, className: `w-32 ${INPUT}`, value: form.customer, onChange: set("customer") }) }), _jsx(Field, { label: "Business account", children: _jsx("input", { "aria-label": "Business account", required: true, className: `w-40 ${INPUT}`, value: form.account, onChange: set("account") }) }), _jsx(Field, { label: "Beneficiary", children: _jsx("input", { "aria-label": "Beneficiary", required: true, className: `w-44 ${INPUT}`, value: form.beneficiary, onChange: set("beneficiary") }) }), _jsx(Field, { label: "Country", children: _jsx("input", { "aria-label": "Beneficiary country", required: true, maxLength: 2, className: `w-14 ${INPUT}`, value: form.country, onChange: set("country") }) }), _jsx(Field, { label: "Amount", children: _jsx("input", { "aria-label": "Amount", required: true, inputMode: "decimal", className: `w-28 ${INPUT}`, value: form.amount, onChange: set("amount") }) }), _jsx(Field, { label: "Expires", children: _jsx("input", { "aria-label": "Expires on", type: "date", required: true, className: INPUT, value: form.expires, onChange: set("expires") }) }), _jsx(Field, { label: "Purpose", children: _jsx("input", { "aria-label": "Purpose", className: `w-40 ${INPUT}`, value: form.purpose, onChange: set("purpose") }) }), _jsx(Button, { size: "sm", type: "submit", disabled: request.isPending, children: "Request" }), _jsx(ErrorMessage, { error: request.error })] }));
}
function InstrumentDetail({ instrument }) {
    const { can } = useAuth();
    const demands = useDemands(instrument.id);
    const receive = useReceiveDemand();
    const decide = useDecideDemand();
    const action = useInstrumentAction();
    const [amount, setAmount] = useState("");
    const [presented, setPresented] = useState("");
    const [discrepancy, setDiscrepancy] = useState("none");
    const isLc = instrument.kind === "letter_of_credit";
    const onSubmit = (event) => {
        event.preventDefault();
        receive.mutate({
            id: instrument.id,
            amount: toMinorUnits(Number(amount), instrument.currency),
            presented_on: presented,
            discrepancies: isLc && discrepancy !== "none" ? [discrepancy] : [],
        }, { onSuccess: () => setAmount("") });
    };
    const today = new Date().toISOString().slice(0, 10);
    return (_jsxs("section", { "aria-label": `Instrument ${instrument.instrument_number}`, className: "mt-4 rounded-lg border border-slate-200 p-3 text-xs", children: [_jsxs("h3", { className: "mb-2 text-sm font-semibold text-slate-900", children: [instrument.instrument_number, " \u00B7 ", KIND[instrument.kind], " for ", instrument.beneficiary_name] }), _jsxs("p", { className: "mb-2 text-slate-600", children: ["Margin held ", formatExactMoney(instrument.margin, instrument.currency), " (", instrument.margin_bps / 100, " %) \u00B7 beneficiary screened against", " ", instrument.screening_list ? "the synthetic sanctions lists" : "no list", ": clear \u00B7 expires ", instrument.expires_on] }), _jsx(ErrorMessage, { error: receive.error ?? decide.error ?? action.error ?? demands.error }), instrument.status === "issued" && can("accounts:transact") && (_jsxs("form", { "aria-label": isLc ? "Present documents" : "Make a claim", onSubmit: onSubmit, className: "flex flex-wrap items-end gap-2", children: [_jsx(Field, { label: `Amount (${instrument.currency})`, children: _jsx("input", { "aria-label": "Demand amount", required: true, inputMode: "decimal", className: `w-28 ${INPUT}`, value: amount, onChange: (e) => setAmount(e.target.value) }) }), _jsx(Field, { label: "Presented on", children: _jsx("input", { "aria-label": "Presented on", type: "date", required: true, className: INPUT, value: presented, onChange: (e) => setPresented(e.target.value) }) }), isLc && (_jsx(Field, { label: "Discrepancy found", children: _jsxs("select", { "aria-label": "Discrepancy", className: INPUT, value: discrepancy, onChange: (e) => setDiscrepancy(e.target.value), children: [_jsx("option", { value: "none", children: "None: complying" }), DISCREPANCIES.map((d) => (_jsx("option", { value: d, children: humanize(d) }, d)))] }) })), _jsx(Button, { size: "sm", type: "submit", disabled: receive.isPending, children: isLc ? "Present documents" : "Make claim" })] })), instrument.status === "issued" && instrument.expires_on < today && can("trade:manage") && (_jsx(Button, { size: "sm", variant: "secondary", onClick: () => action.mutate({ id: instrument.id, action: "expire" }), children: "Close as expired" })), _jsx("table", { "aria-label": "Demands", className: "mt-3 min-w-full", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: demands.data?.map((d) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1 font-mono", children: d.demand_number }), _jsxs("td", { className: "px-2 py-1 text-slate-600", children: [d.presented_on, " \u00B7 ", d.discrepancies.length ? d.discrepancies.map(humanize).join(", ") : "complying", d.decision_note && ` · ${d.decision_note}`] }), _jsx("td", { className: "px-2 py-1 text-right tabular-nums", children: formatExactMoney(d.amount, instrument.currency) }), _jsx("td", { className: "px-2 py-1", children: _jsx(StatusPill, { compact: true, tone: d.status === "paid" ? "good" : d.status === "pending" ? "warn" : "neutral", label: d.status }) }), _jsx("td", { className: "px-2 py-1 text-right", children: d.status === "pending" && can("trade:manage") && (_jsxs("div", { className: "flex justify-end gap-1", children: [_jsx(Button, { size: "sm", "aria-label": `Pay ${d.demand_number}`, onClick: () => decide.mutate({ id: d.id, pay: true }), children: d.discrepancies.length ? "Pay (waived)" : "Pay" }), _jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Reject ${d.demand_number}`, onClick: () => decide.mutate({ id: d.id, pay: false }), children: "Reject" })] })) })] }, d.id))) }) })] }));
}
/** Trade finance (Phase 37): letters of credit, guarantees, presentations and claims. */
export function TradePage() {
    const { can } = useAuth();
    const summary = useTradeSummary();
    const [offset, setOffset] = useState(0);
    const instruments = useInstruments(offset);
    const action = useInstrumentAction();
    const [selected, setSelected] = useState(null);
    const items = instruments.data?.items ?? [];
    const total = instruments.data?.total ?? 0;
    const chosen = items.find((i) => i.id === selected);
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Trade Finance", description: "Letters of credit and bank guarantees for business customers: beneficiaries screened against the sanctions lists, approval with four-eyes and above US$1m the credit committee, a cash margin held while live, documents checked for discrepancies and claims paid through the ledger." }), summary.data && (_jsx("dl", { "aria-label": "Trade summary", className: "mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5", children: [
                    ["Requested", summary.data.requested],
                    ["Issued", summary.data.issued],
                    ["Demands to check", summary.data.pending_demands],
                    ["Paid", summary.data.paid],
                    ["Expired", summary.data.expired],
                ].map(([label, value]) => (_jsxs("div", { className: "rounded-lg border border-slate-200 bg-white p-3", children: [_jsx("dt", { className: "text-xs text-slate-500", children: label }), _jsx("dd", { className: "text-lg font-semibold text-slate-900", children: value })] }, label))) })), _jsxs(Panel, { title: "Instruments", subtitle: "A credit approver other than the requester approves; above US$1m the credit committee too. Issuing takes the cash margin (20 % for letters of credit, 10 % for guarantees); payment releases it in proportion, expiry releases the rest.", children: [can("accounts:transact") && _jsx(RequestForm, {}), _jsx(ErrorMessage, { error: instruments.error ?? action.error }), _jsx("table", { "aria-label": "Instruments", className: "min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [items.map((i) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5", children: _jsx("button", { type: "button", "aria-label": `Select ${i.instrument_number}`, className: "font-mono text-xs text-sky-700 underline", onClick: () => setSelected(i.id), children: i.instrument_number }) }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [i.customer_name, " \u2192 ", i.beneficiary_name, " (", i.beneficiary_country, ") \u00B7 ", i.purpose, " \u00B7 expires ", i.expires_on] }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: formatExactMoney(i.amount, i.currency) }), _jsxs("td", { className: "px-2 py-1.5 text-right text-xs tabular-nums text-slate-600", children: ["drawn ", formatExactMoney(i.drawn, i.currency)] }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: TONE[i.status], label: i.status === "requested" && i.approved ? "awaiting committee" : i.status }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: i.status === "requested" && (_jsxs("div", { className: "flex justify-end gap-1", children: [!i.approved && can("loans:approve") && (_jsx(Button, { size: "sm", "aria-label": `Approve ${i.instrument_number}`, onClick: () => action.mutate({ id: i.id, action: "approve" }), children: "Approve" })), i.approved && i.needs_committee && !i.committee_approved && can("loans:approve_large") && (_jsx(Button, { size: "sm", "aria-label": `Committee approve ${i.instrument_number}`, onClick: () => action.mutate({ id: i.id, action: "committee" }), children: "Committee approve" })), can("loans:approve") && (_jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Decline ${i.instrument_number}`, onClick: () => action.mutate({ id: i.id, action: "decline" }), children: "Decline" }))] })) })] }, i.id))), instruments.data && items.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No instruments yet." }) }))] }) }), total > INSTRUMENTS_PAGE && (_jsxs("nav", { "aria-label": "Instrument pages", className: "mt-2 flex items-center justify-end gap-2 text-xs text-slate-600", children: [_jsxs("span", { children: [offset + 1, "\u2013", Math.min(offset + INSTRUMENTS_PAGE, total), " of ", total] }), _jsx(Button, { size: "sm", variant: "secondary", disabled: offset === 0, onClick: () => setOffset(Math.max(offset - INSTRUMENTS_PAGE, 0)), children: "Newer" }), _jsx(Button, { size: "sm", variant: "secondary", disabled: offset + INSTRUMENTS_PAGE >= total, onClick: () => setOffset(offset + INSTRUMENTS_PAGE), children: "Older" })] })), chosen && _jsx(InstrumentDetail, { instrument: chosen })] })] }));
}
