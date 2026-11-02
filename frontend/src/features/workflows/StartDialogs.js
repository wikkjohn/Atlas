import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { apiPost, newIdempotencyKey } from "@/services/api";
import { useAccounts } from "@/services/banking";
import { currencyDigits, formatExactMoney } from "@/services/format";
import { useStartExecution } from "@/services/workflows";
/** A decimal amount typed by a user, in minor units (NaN when it is not a valid amount). */
function minorUnits(value, currency, allowZero = false) {
    const amount = Number(value);
    if (!value.trim() || !Number.isFinite(amount) || amount < 0 || (amount === 0 && !allowZero))
        return Number.NaN;
    return Math.round(amount * 10 ** currencyDigits(currency));
}
function accountLabel(a) {
    return `${a.account_number} · ${a.customer_name} (${formatExactMoney(a.balance, a.currency)})`;
}
const PICKER_PAGE = 50;
/** Open accounts, searched on the server by number or customer name, so any account can be
 * chosen however many exist. The chosen account stays selected while the search changes. */
function AccountPicker({ label, searchLabel, value, onChange, filters, allow, describe = accountLabel, error }) {
    const [q, setQ] = useState("");
    const accounts = useAccounts({ status: "open", q: q.trim() || null, limit: PICKER_PAGE, ...filters });
    const found = (accounts.data?.items ?? []).filter((a) => !allow || allow(a));
    const options = value && !found.some((a) => a.id === value.id) ? [value, ...found] : found;
    const total = accounts.data?.total ?? 0;
    return (_jsxs("div", { className: "space-y-1.5", children: [_jsx("input", { "aria-label": searchLabel, placeholder: "Search by account number or customer", className: inputClass, value: q, onChange: (e) => setQ(e.target.value) }), _jsx(Field, { label: label, error: error, hint: total > PICKER_PAGE ? `First ${PICKER_PAGE} of ${total.toLocaleString()} — search to narrow.` : undefined, children: (p) => (_jsxs("select", { ...p, className: inputClass, value: value?.account_number ?? "", onChange: (e) => onChange(options.find((a) => a.account_number === e.target.value) ?? null), children: [_jsx("option", { value: "", children: "Select\u2026" }), options.map((a) => (_jsx("option", { value: a.account_number, children: describe(a) }, a.id)))] })) }), _jsx(ErrorMessage, { error: accounts.error })] }));
}
function StartFooter({ form, pending, label, onClose }) {
    return (_jsxs(_Fragment, { children: [_jsx(Button, { variant: "secondary", onClick: onClose, children: "Cancel" }), _jsx(Button, { type: "submit", form: form, disabled: pending, children: pending ? "Submitting…" : label })] }));
}
export function StartPaymentDialog({ onClose, onStarted }) {
    const start = useStartExecution("WF-0002");
    const [key] = useState(newIdempotencyKey);
    const [debtor, setDebtor] = useState(null);
    const [creditor, setCreditor] = useState(null);
    const [form, setForm] = useState({ amount: "", reference: "" });
    const [submitted, setSubmitted] = useState(false);
    const set = (k, v) => setForm({ ...form, [k]: v });
    const payable = (a) => a.id !== debtor?.id;
    const amount = debtor ? minorUnits(form.amount, debtor.currency) : Number.NaN;
    // A payee in another currency receives the amount converted at release (Phase 24).
    const converting = Boolean(debtor && creditor && debtor.currency !== creditor.currency);
    const estimate = useQuery({
        queryKey: ["fx", "quote", debtor?.currency, creditor?.currency, amount],
        queryFn: () => apiPost("/api/v1/fx/quote", { sell_currency: debtor.currency, buy_currency: creditor.currency, sell_amount: amount }),
        enabled: converting && !Number.isNaN(amount),
    });
    const errors = {
        debtor: debtor ? null : "Choose the paying account.",
        creditor: creditor && payable(creditor) ? null : "Choose a payee.",
        amount: Number.isNaN(amount) ? "Enter an amount above zero." : null,
        reference: form.reference.trim() ? null : "A reference is required.",
    };
    const show = (k) => (submitted ? errors[k] : null);
    const onSubmit = (event) => {
        event.preventDefault();
        setSubmitted(true);
        if (Object.values(errors).some(Boolean) || !debtor || !creditor)
            return;
        start.mutate({
            idempotencyKey: key,
            input: {
                debtor_account_number: debtor.account_number,
                creditor_account_number: creditor.account_number,
                amount,
                currency: debtor.currency,
                reference: form.reference.trim(),
                channel: "branch",
            },
        }, { onSuccess: (execution) => onStarted(execution.id) });
    };
    return (_jsxs(Modal, { wide: true, title: "New payment (WF-0002)", onClose: onClose, footer: _jsx(StartFooter, { form: "wf0002-start", pending: start.isPending, label: "Submit payment", onClose: onClose }), children: [_jsxs("form", { id: "wf0002-start", "aria-label": "New payment", onSubmit: onSubmit, className: "grid grid-cols-1 gap-4 sm:grid-cols-2", children: [_jsx(AccountPicker, { label: "Paying account", searchLabel: "Search paying accounts", value: debtor, onChange: (a) => {
                            setDebtor(a);
                            setCreditor(null);
                        }, error: show("debtor") }), _jsx(AccountPicker, { label: "Payee account", searchLabel: "Search payees", value: creditor, onChange: setCreditor, allow: payable, describe: (a) => `${a.account_number} · ${a.customer_name} (${a.currency})`, error: show("creditor") }), _jsx(Field, { label: `Amount${debtor ? ` (${debtor.currency})` : ""}`, hint: "High-value payments (10,000 or more) need a second approver.", error: show("amount"), children: (p) => _jsx("input", { ...p, type: "number", min: 0, step: "any", className: inputClass, value: form.amount, onChange: (e) => set("amount", e.target.value) }) }), _jsx(Field, { label: "Reference", error: show("reference"), children: (p) => _jsx("input", { ...p, maxLength: 140, className: inputClass, value: form.reference, onChange: (e) => set("reference", e.target.value) }) })] }), converting && (_jsx("p", { role: "status", "aria-label": "Conversion estimate", className: "mt-3 text-sm text-slate-700", children: estimate.data
                    ? `The payee receives about ${formatExactMoney(estimate.data.buy_amount, estimate.data.buy_currency)} at today's rate (${Number(estimate.data.customer_rate).toPrecision(6)}, ${estimate.data.margin_bps / 100} % margin); the rate on the release date applies.`
                    : `The amount is converted from ${debtor.currency} to ${creditor.currency} when the payment is released.` })), _jsx("p", { className: "mt-3 text-xs text-slate-500", children: "Screening holds payments with scam indicators (for example a reference mentioning gift cards), payees on the synthetic watchlist and first payments that empty an account; fraud analysts decide them." }), _jsx(ErrorMessage, { error: start.error, className: "mt-4" })] }));
}
const PURPOSES = [
    ["home_improvement", "Home improvement"],
    ["vehicle", "Vehicle"],
    ["education", "Education"],
    ["debt_consolidation", "Debt consolidation"],
    ["other", "Other"],
];
export function StartLoanDialog({ onClose, onStarted }) {
    const start = useStartExecution("WF-0003");
    const [key] = useState(newIdempotencyKey);
    const [account, setAccount] = useState(null);
    const [form, setForm] = useState({
        amount: "",
        term_months: "36",
        purpose: "home_improvement",
        monthly_income: "",
        monthly_debt_payments: "0",
        employment_status: "employed",
    });
    const [submitted, setSubmitted] = useState(false);
    const set = (k, v) => setForm({ ...form, [k]: v });
    const currency = account?.currency ?? "USD";
    const amount = minorUnits(form.amount, currency);
    const income = minorUnits(form.monthly_income, currency);
    const debts = minorUnits(form.monthly_debt_payments, currency, true);
    const errors = {
        account: account ? null : "Choose the customer's current account.",
        amount: Number.isNaN(amount) ? "Enter the amount to borrow." : null,
        monthly_income: Number.isNaN(income) ? "Enter the declared monthly income." : null,
        monthly_debt_payments: Number.isNaN(debts) ? "Enter 0 or the monthly repayments." : null,
    };
    const show = (k) => (submitted ? errors[k] : null);
    const onSubmit = (event) => {
        event.preventDefault();
        setSubmitted(true);
        if (Object.values(errors).some(Boolean) || !account)
            return;
        start.mutate({
            idempotencyKey: key,
            input: {
                customer_number: account.customer_number,
                disbursement_account_number: account.account_number,
                amount,
                term_months: Number(form.term_months),
                purpose: form.purpose,
                monthly_income: income,
                monthly_debt_payments: debts,
                employment_status: form.employment_status,
            },
        }, { onSuccess: (execution) => onStarted(execution.id) });
    };
    return (_jsxs(Modal, { wide: true, title: "New personal loan application (WF-0003)", onClose: onClose, footer: _jsx(StartFooter, { form: "wf0003-start", pending: start.isPending, label: "Submit application", onClose: onClose }), children: [_jsxs("form", { id: "wf0003-start", "aria-label": "New personal loan application", onSubmit: onSubmit, className: "grid grid-cols-1 gap-4 sm:grid-cols-2", children: [_jsx(AccountPicker, { label: "Customer and disbursement account", searchLabel: "Search customers", value: account, onChange: setAccount, filters: { account_type: "current" }, allow: (a) => a.account_type === "current", describe: (a) => `${a.customer_name} · ${a.account_number}`, error: show("account") }), _jsx(Field, { label: `Amount (${currency})`, hint: "Personal loans: 1,000 to 50,000; above 25,000 the credit committee also decides.", error: show("amount"), children: (p) => _jsx("input", { ...p, type: "number", min: 0, step: "any", className: inputClass, value: form.amount, onChange: (e) => set("amount", e.target.value) }) }), _jsx(Field, { label: "Term", children: (p) => (_jsx("select", { ...p, className: inputClass, value: form.term_months, onChange: (e) => set("term_months", e.target.value), children: [12, 24, 36, 48, 60, 72, 84].map((m) => (_jsxs("option", { value: m, children: [m, " months"] }, m))) })) }), _jsx(Field, { label: "Purpose", children: (p) => (_jsx("select", { ...p, className: inputClass, value: form.purpose, onChange: (e) => set("purpose", e.target.value), children: PURPOSES.map(([value, label]) => (_jsx("option", { value: value, children: label }, value))) })) }), _jsx(Field, { label: `Monthly income (${currency})`, hint: "As declared by the applicant.", error: show("monthly_income"), children: (p) => _jsx("input", { ...p, type: "number", min: 0, step: "any", className: inputClass, value: form.monthly_income, onChange: (e) => set("monthly_income", e.target.value) }) }), _jsx(Field, { label: `Existing monthly repayments (${currency})`, error: show("monthly_debt_payments"), children: (p) => (_jsx("input", { ...p, type: "number", min: 0, step: "any", className: inputClass, value: form.monthly_debt_payments, onChange: (e) => set("monthly_debt_payments", e.target.value) })) }), _jsx(Field, { label: "Employment", children: (p) => (_jsxs("select", { ...p, className: inputClass, value: form.employment_status, onChange: (e) => set("employment_status", e.target.value), children: [_jsx("option", { value: "employed", children: "Employed" }), _jsx("option", { value: "self_employed", children: "Self-employed" }), _jsx("option", { value: "retired", children: "Retired" }), _jsx("option", { value: "unemployed", children: "Unemployed" })] })) })] }), _jsx("p", { className: "mt-3 text-xs text-slate-500", children: "The credit bureau is synthetic: each customer's score is derived from their name and date of birth. Applications that break the credit policy are declined automatically; the rest go to an underwriter." }), _jsx(ErrorMessage, { error: start.error, className: "mt-4" })] }));
}
