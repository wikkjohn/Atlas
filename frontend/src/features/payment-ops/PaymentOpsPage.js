import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { formatExactMoney, humanize } from "@/services/format";
import { OPS_PAGE, useBanks, useBatches, useBulkFiles, useCreateOutgoing, useDecideBulk, useDecideOutgoing, useOutgoing, usePaymentOpsSummary, useReceiveBulk, useRecallAction, useRecalls, useRequestRecall, useRunCycle, } from "@/services/paymentOps";
import { RECALL_REASONS } from "@/types/paymentOps";
const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const TONE = {
    awaiting_approval: "warn",
    pending: "warn",
    in_clearing: "warn",
    settled: "good",
    returned: "bad",
    rejected: "neutral",
    recalled: "neutral",
};
function Field({ label, children }) {
    return (_jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: [label, children] }));
}
const EMPTY = { account: "", name: "", bank: "", beneficiary: "", amount: "", reference: "" };
function OutgoingForm() {
    const banks = useBanks();
    const create = useCreateOutgoing();
    const [form, setForm] = useState(EMPTY);
    const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
    const onSubmit = (event) => {
        event.preventDefault();
        create.mutate({
            account_number: form.account.trim(),
            beneficiary_name: form.name,
            beneficiary_bank: form.bank,
            beneficiary_account: form.beneficiary.trim(),
            amount_major: Number(form.amount),
            reference: form.reference,
        }, { onSuccess: () => setForm(EMPTY) });
    };
    return (_jsxs("form", { "aria-label": "Pay another bank", onSubmit: onSubmit, className: "mb-3 flex flex-wrap items-end gap-2 text-xs", children: [_jsx(Field, { label: "From account", children: _jsx("input", { "aria-label": "From account", required: true, className: `w-40 ${INPUT}`, value: form.account, onChange: set("account") }) }), _jsx(Field, { label: "Beneficiary", children: _jsx("input", { "aria-label": "Beneficiary name", required: true, className: `w-40 ${INPUT}`, value: form.name, onChange: set("name") }) }), _jsx(Field, { label: "Bank", children: _jsxs("select", { "aria-label": "Beneficiary bank", required: true, className: INPUT, value: form.bank, onChange: set("bank"), children: [_jsx("option", { value: "", children: "Choose\u2026" }), banks.data?.map((b) => (_jsxs("option", { value: b.code, children: [b.code, " \u00B7 ", b.name] }, b.code)))] }) }), _jsx(Field, { label: "Account (14 digits)", children: _jsx("input", { "aria-label": "Beneficiary account", required: true, inputMode: "numeric", className: `w-36 ${INPUT}`, value: form.beneficiary, onChange: set("beneficiary") }) }), _jsx(Field, { label: "Amount", children: _jsx("input", { "aria-label": "Amount", required: true, inputMode: "decimal", className: `w-28 ${INPUT}`, value: form.amount, onChange: set("amount") }) }), _jsx(Field, { label: "Reference", children: _jsx("input", { "aria-label": "Reference", className: `w-32 ${INPUT}`, value: form.reference, onChange: set("reference") }) }), _jsx(Button, { size: "sm", type: "submit", disabled: create.isPending, children: "Send" }), _jsx(ErrorMessage, { error: create.error })] }));
}
/** Newer/older paging for a list served newest first, `OPS_PAGE` rows at a time. */
function Pager({ label, offset, total, onChange }) {
    if (total <= OPS_PAGE)
        return null;
    return (_jsxs("nav", { "aria-label": label, className: "mt-2 flex items-center justify-end gap-2 text-xs text-slate-600", children: [_jsxs("span", { children: [offset + 1, "\u2013", Math.min(offset + OPS_PAGE, total), " of ", total] }), _jsx(Button, { size: "sm", variant: "secondary", disabled: offset === 0, onClick: () => onChange(Math.max(offset - OPS_PAGE, 0)), children: "Newer" }), _jsx(Button, { size: "sm", variant: "secondary", disabled: offset + OPS_PAGE >= total, onClick: () => onChange(offset + OPS_PAGE), children: "Older" })] }));
}
function OutgoingPanel() {
    const { can } = useAuth();
    const [offset, setOffset] = useState(0);
    const outgoing = useOutgoing(offset);
    const decide = useDecideOutgoing();
    const items = outgoing.data?.items ?? [];
    const total = outgoing.data?.total ?? 0;
    return (_jsxs(Panel, { title: "Outgoing payments", subtitle: "Payments to other (synthetic) banks. High value waits for someone else's approval; every payment then waits for the next clearing cycle.", children: [can("accounts:transact") && _jsx(OutgoingForm, {}), _jsx(ErrorMessage, { error: outgoing.error ?? decide.error }), _jsx("table", { "aria-label": "Outgoing payments", className: "min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [items.map((p) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: p.payment_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [p.account_number, " \u2192 ", p.beneficiary_name, " (", p.beneficiary_bank, " ", p.beneficiary_account, ") \u00B7 ", p.reference, p.return_code && ` · ${p.return_code}: ${p.reason}`] }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: formatExactMoney(p.amount, p.currency) }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: TONE[p.status], label: humanize(p.status) }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: p.status === "awaiting_approval" && can("payments:approve") && (_jsxs("div", { className: "flex justify-end gap-1", children: [_jsx(Button, { size: "sm", "aria-label": `Approve ${p.payment_number}`, onClick: () => decide.mutate({ id: p.id, approve: true }), children: "Approve" }), _jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Reject ${p.payment_number}`, onClick: () => decide.mutate({ id: p.id, approve: false }), children: "Reject" })] })) })] }, p.id))), outgoing.data && items.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No outgoing payments yet." }) }))] }) }), _jsx(Pager, { label: "Payment pages", offset: offset, total: total, onChange: setOffset })] }));
}
function ClearingPanel() {
    const { can } = useAuth();
    const batches = useBatches();
    const run = useRunCycle();
    const [currency, setCurrency] = useState("");
    const onSubmit = (event) => {
        event.preventDefault();
        run.mutate(currency.trim());
    };
    return (_jsxs(Panel, { title: "Clearing", subtitle: "A cycle puts a currency's pending payments in a batch, debits each payer into clearing suspense, then settles: payments to accounts the beneficiary bank has closed come back (AC04), the rest are paid out of the bank's cash.", children: [can("payments:operate") && (_jsxs("form", { "aria-label": "Run a clearing cycle", onSubmit: onSubmit, className: "mb-3 flex items-end gap-2 text-xs", children: [_jsx(Field, { label: "Currency", children: _jsx("input", { "aria-label": "Cycle currency", required: true, maxLength: 3, className: `w-16 ${INPUT}`, value: currency, onChange: (e) => setCurrency(e.target.value) }) }), _jsx(Button, { size: "sm", type: "submit", disabled: run.isPending, children: "Run cycle" }), run.data && !run.data.batch && _jsx("span", { className: "text-slate-500", children: "Nothing pending in that currency." }), _jsx(ErrorMessage, { error: run.error })] })), _jsx(ErrorMessage, { error: batches.error }), _jsx("table", { "aria-label": "Clearing batches", className: "min-w-full text-sm", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: batches.data?.items.map((b) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: b.batch_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [b.business_date, " \u00B7 ", b.payments, " payments \u00B7 ", b.settled_count, " settled, ", b.returned_count, " returned"] }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: formatExactMoney(b.total, b.currency) })] }, b.id))) }) })] }));
}
function BulkPanel() {
    const { can } = useAuth();
    const [offset, setOffset] = useState(0);
    const files = useBulkFiles(offset);
    const receive = useReceiveBulk();
    const decide = useDecideBulk();
    const [form, setForm] = useState({ account: "", name: "", text: "" });
    const onSubmit = (event) => {
        event.preventDefault();
        receive.mutate({ account_number: form.account.trim(), file_name: form.name || "bulk", text: form.text }, { onSuccess: () => setForm({ account: "", name: "", text: "" }) });
    };
    return (_jsxs(Panel, { title: "Bulk files", subtitle: "Many payments from one account. Every line is checked; someone other than the receiver releases the file.", children: [can("accounts:transact") && (_jsxs("form", { "aria-label": "Bulk file", onSubmit: onSubmit, className: "mb-3 flex flex-wrap items-end gap-2 text-xs", children: [_jsx(Field, { label: "Account", children: _jsx("input", { "aria-label": "Bulk account", required: true, className: `w-40 ${INPUT}`, value: form.account, onChange: (e) => setForm({ ...form, account: e.target.value }) }) }), _jsx(Field, { label: "File name", children: _jsx("input", { "aria-label": "File name", className: `w-36 ${INPUT}`, value: form.name, onChange: (e) => setForm({ ...form, name: e.target.value }) }) }), _jsx(Field, { label: "Lines: name, bank, account, amount, reference", children: _jsx("textarea", { "aria-label": "Lines", required: true, rows: 3, className: `w-96 font-mono ${INPUT}`, value: form.text, onChange: (e) => setForm({ ...form, text: e.target.value }) }) }), _jsx(Button, { size: "sm", type: "submit", disabled: receive.isPending, children: "Receive file" }), _jsx(ErrorMessage, { error: receive.error })] })), _jsx(ErrorMessage, { error: files.error ?? decide.error }), _jsx("table", { "aria-label": "Bulk files", className: "min-w-full text-sm", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: files.data?.items.map((f) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: f.file_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [f.file_name, " \u00B7 ", f.account_number, " \u00B7 ", f.valid_count, " valid, ", f.invalid_count, " invalid", f.lines.find((l) => l.error) && ` (line ${f.lines.find((l) => l.error)?.line}: ${f.lines.find((l) => l.error)?.error})`] }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: formatExactMoney(f.valid_total, f.currency) }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: f.status === "released" ? "good" : f.status === "received" ? "warn" : "neutral", label: f.status }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: f.status === "received" && can("payments:approve") && (_jsxs("div", { className: "flex justify-end gap-1", children: [_jsx(Button, { size: "sm", "aria-label": `Release ${f.file_number}`, onClick: () => decide.mutate({ id: f.id, release: true }), children: "Release" }), _jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Reject ${f.file_number}`, onClick: () => decide.mutate({ id: f.id, release: false }), children: "Reject" })] })) })] }, f.id))) }) }), _jsx(Pager, { label: "Bulk file pages", offset: offset, total: files.data?.total ?? 0, onChange: setOffset })] }));
}
function RecallsPanel() {
    const { can } = useAuth();
    const [offset, setOffset] = useState(0);
    const recalls = useRecalls(offset);
    const request = useRequestRecall();
    const action = useRecallAction();
    const [form, setForm] = useState({ payment: "", reason: "DUPL" });
    const onSubmit = (event) => {
        event.preventDefault();
        request.mutate({ payment_number: form.payment.trim().toUpperCase(), reason_code: form.reason }, { onSuccess: () => setForm({ ...form, payment: "" }) });
    };
    return (_jsxs(Panel, { title: "Recalls", subtitle: "Someone other than the requester approves. A payment not yet cleared is cancelled; a settled one is asked back, and the beneficiary's bank returns it within 10 days (duplicates, technical errors), 5 (customer requests) or 3 (fraud) of settlement.", children: [can("accounts:transact") && (_jsxs("form", { "aria-label": "Recall a payment", onSubmit: onSubmit, className: "mb-3 flex flex-wrap items-end gap-2 text-xs", children: [_jsx(Field, { label: "Payment", children: _jsx("input", { "aria-label": "Payment number", required: true, className: `w-36 ${INPUT}`, value: form.payment, onChange: (e) => setForm({ ...form, payment: e.target.value }) }) }), _jsx(Field, { label: "Reason", children: _jsx("select", { "aria-label": "Reason", className: INPUT, value: form.reason, onChange: (e) => setForm({ ...form, reason: e.target.value }), children: Object.entries(RECALL_REASONS).map(([code, label]) => (_jsx("option", { value: code, children: label }, code))) }) }), _jsx(Button, { size: "sm", type: "submit", disabled: request.isPending, children: "Request recall" }), _jsx(ErrorMessage, { error: request.error })] })), _jsx(ErrorMessage, { error: recalls.error ?? action.error }), _jsx("table", { "aria-label": "Recalls", className: "min-w-full text-sm", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: recalls.data?.items.map((r) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: r.recall_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [r.payment_number, " \u00B7 ", RECALL_REASONS[r.reason_code], r.outcome_note && ` · ${r.outcome_note}`] }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: r.status === "accepted" ? "good" : r.status === "refused" ? "bad" : r.status === "withdrawn" ? "neutral" : "warn", label: r.status }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: _jsxs("div", { className: "flex justify-end gap-1", children: [r.status === "requested" && can("payments:approve") && (_jsxs(_Fragment, { children: [_jsx(Button, { size: "sm", "aria-label": `Approve ${r.recall_number}`, onClick: () => action.mutate({ id: r.id, action: "approve" }), children: "Approve" }), _jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Withdraw ${r.recall_number}`, onClick: () => action.mutate({ id: r.id, action: "withdraw" }), children: "Withdraw" })] })), r.status === "sent" && can("payments:operate") && (_jsx(Button, { size: "sm", "aria-label": `Record answer ${r.recall_number}`, onClick: () => action.mutate({ id: r.id, action: "resolve" }), children: "Record answer" }))] }) })] }, r.id))) }) }), _jsx(Pager, { label: "Recall pages", offset: offset, total: recalls.data?.total ?? 0, onChange: setOffset })] }));
}
/** Payments operations (Phase 41): payments to other banks, clearing, bulk files and recalls. */
export function PaymentOpsPage() {
    const summary = usePaymentOpsSummary();
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Payments Operations", description: "Payments to accounts at other (synthetic) banks through a simulated clearing system: approvals for high value, clearing cycles with returns, bulk payment files and recalls." }), summary.data && (_jsx("dl", { "aria-label": "Payments operations summary", className: "mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5", children: [
                    ["Awaiting approval", summary.data.awaiting_approval],
                    ["Waiting for clearing", summary.data.pending],
                    ["Returned", summary.data.returned],
                    ["Bulk files to release", summary.data.bulk_received],
                    ["Open recalls", summary.data.open_recalls],
                ].map(([label, value]) => (_jsxs("div", { className: "rounded-lg border border-slate-200 bg-white p-3", children: [_jsx("dt", { className: "text-xs text-slate-500", children: label }), _jsx("dd", { className: "text-lg font-semibold text-slate-900", children: value })] }, label))) })), _jsxs("div", { className: "flex flex-col gap-6", children: [_jsx(OutgoingPanel, {}), _jsx(ClearingPanel, {}), _jsx(BulkPanel, {}), _jsx(RecallsPanel, {})] })] }));
}
