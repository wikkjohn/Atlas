import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { formatExactMoney } from "@/services/format";
import { useCancelStandingOrder, useCreateStandingOrder, useMonthEnds, useRetailProducts, useRetailSummary, useRunMonthEnd, useStandingOrders, useStatement, useStatements, useUpdateProduct, } from "@/services/retail";
const percent = (bps) => `${(bps / 100).toFixed(2)} %`;
const usd = (cents) => formatExactMoney(cents, "USD");
const ORDER_TONE = { active: "good", cancelled: "neutral", ended: "neutral", failed: "bad" };
function ProductRow({ product, manage }) {
    const update = useUpdateProduct();
    const [editing, setEditing] = useState(false);
    const [credit, setCredit] = useState(String(product.credit_rate_bps));
    const [overdraft, setOverdraft] = useState(String(product.overdraft_rate_bps));
    const [fee, setFee] = useState(String(product.monthly_fee_usd_cents));
    const save = () => update.mutate({
        account_type: product.account_type,
        credit_rate_bps: Number(credit),
        overdraft_rate_bps: Number(overdraft),
        monthly_fee_usd_cents: Number(fee),
    }, { onSuccess: () => setEditing(false) });
    const input = (label, value, set) => (_jsx("input", { "aria-label": `${label} of ${product.name}`, className: "w-20 rounded border border-slate-200 px-1 py-0.5 text-xs", value: value, onChange: (e) => set(e.target.value) }));
    return (_jsxs("tr", { children: [_jsxs("td", { className: "px-2 py-1.5", children: [_jsx("div", { className: "font-medium text-slate-900", children: product.name }), _jsxs("div", { className: "text-xs text-slate-500", children: [product.account_type.replace("_", " "), " accounts"] })] }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: editing ? input("Credit interest (bps)", credit, setCredit) : percent(product.credit_rate_bps) }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: editing ? input("Overdraft interest (bps)", overdraft, setOverdraft) : percent(product.overdraft_rate_bps) }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: editing ? input("Monthly fee (US cents)", fee, setFee) : usd(product.monthly_fee_usd_cents) }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: product.max_overdraft_usd ? usd(product.max_overdraft_usd * 100) : "None" }), _jsxs("td", { className: "px-2 py-1.5 text-right", children: [manage &&
                        (editing ? (_jsx(Button, { size: "sm", onClick: save, disabled: update.isPending, children: "Save" })) : (_jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Edit ${product.name}`, onClick: () => setEditing(true), children: "Edit" }))), _jsx(ErrorMessage, { error: update.error })] })] }));
}
function ProductsPanel() {
    const { can } = useAuth();
    const products = useRetailProducts();
    return (_jsxs(Panel, { title: "Products", subtitle: "Interest a year on credit and overdrawn balances, the monthly fee and the largest arranged overdraft. Dollar amounts are converted to each account's currency at the synthetic FX anchor rates.", children: [_jsx(ErrorMessage, { error: products.error }), _jsxs("table", { "aria-label": "Retail products", className: "min-w-full text-sm", children: [_jsx("thead", { className: "text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-2 py-1", children: "Product" }), _jsx("th", { className: "px-2 py-1 text-right", children: "Credit interest" }), _jsx("th", { className: "px-2 py-1 text-right", children: "Overdraft interest" }), _jsx("th", { className: "px-2 py-1 text-right", children: "Monthly fee" }), _jsx("th", { className: "px-2 py-1 text-right", children: "Overdraft up to" }), _jsx("th", { className: "px-2 py-1" })] }) }), _jsx("tbody", { className: "divide-y divide-slate-100", children: products.data?.map((p) => (_jsx(ProductRow, { product: p, manage: can("retail:manage") }, p.account_type))) })] })] }));
}
function StandingOrdersPanel() {
    const { can } = useAuth();
    const orders = useStandingOrders();
    const create = useCreateStandingOrder();
    const cancel = useCancelStandingOrder();
    const [payer, setPayer] = useState("");
    const [payee, setPayee] = useState("");
    const [amount, setAmount] = useState("");
    const [frequency, setFrequency] = useState("monthly");
    const [first, setFirst] = useState("");
    const [reference, setReference] = useState("");
    const transact = can("accounts:transact");
    const onSubmit = (event) => {
        event.preventDefault();
        create.mutate({
            debtor_account_number: payer.trim(),
            creditor_account_number: payee.trim(),
            amount: Math.round(Number(amount) * 100),
            frequency,
            first_date: first,
            reference,
        }, { onSuccess: () => setAmount("") });
    };
    return (_jsxs(Panel, { title: "Standing orders", subtitle: "Paid by the daily standing-order job on business days of the payer's country; three missed payments in a row stop an order.", children: [transact && (_jsxs("form", { "aria-label": "New standing order", onSubmit: onSubmit, className: "mb-3 flex flex-wrap items-end gap-2 text-xs", children: [[
                        ["Payer account", payer, setPayer, "w-40"],
                        ["Payee account", payee, setPayee, "w-40"],
                        ["Amount", amount, setAmount, "w-24"],
                        ["Reference", reference, setReference, "w-32"],
                    ].map(([label, value, set, width]) => (_jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: [label, _jsx("input", { "aria-label": label, required: true, className: `${width} rounded-md border border-slate-200 px-2 py-1`, value: value, onChange: (e) => set(e.target.value) })] }, label))), _jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Frequency", _jsxs("select", { "aria-label": "Frequency", className: "rounded-md border border-slate-200 px-2 py-1", value: frequency, onChange: (e) => setFrequency(e.target.value), children: [_jsx("option", { value: "monthly", children: "Monthly" }), _jsx("option", { value: "weekly", children: "Weekly" })] })] }), _jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["First payment", _jsx("input", { "aria-label": "First payment", type: "date", required: true, className: "rounded-md border border-slate-200 px-2 py-1", value: first, onChange: (e) => setFirst(e.target.value) })] }), _jsx(Button, { size: "sm", type: "submit", disabled: create.isPending, children: "Set up" })] })), _jsx(ErrorMessage, { error: create.error ?? cancel.error ?? orders.error }), _jsx("table", { "aria-label": "Standing orders", className: "min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [orders.data?.items.map((o) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: o.order_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs", children: [_jsxs("div", { className: "text-slate-900", children: [o.debtor_account_number, " \u2192 ", o.creditor_account_number] }), _jsxs("div", { className: "text-slate-500", children: [o.reference, " \u00B7 ", o.frequency, " \u00B7 next ", o.next_date, " \u00B7 ", o.payments_made, " paid", o.last_error && _jsxs("span", { className: "text-rose-700", children: [" \u00B7 ", o.last_error] })] })] }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: formatExactMoney(o.amount, o.currency) }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: ORDER_TONE[o.status], label: o.status }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: transact && o.status === "active" && (_jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Cancel ${o.order_number}`, disabled: cancel.isPending, onClick: () => cancel.mutate(o.id), children: "Cancel" })) })] }, o.id))), orders.data?.items.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No standing orders yet." }) }))] }) })] }));
}
function StatementView({ id, onClose }) {
    const statement = useStatement(id);
    const s = statement.data;
    return (_jsxs(Modal, { wide: true, title: s ? `Statement ${s.statement_number}` : "Statement", onClose: onClose, children: [_jsx(ErrorMessage, { error: statement.error }), s && (_jsxs("div", { className: "space-y-3 text-sm", children: [_jsxs("p", { className: "text-slate-600", children: ["Account ", s.account_number, " \u00B7 ", s.period_start, " to ", s.period_end, " \u00B7 opening ", formatExactMoney(s.opening_balance, s.currency), " \u00B7 closing", " ", formatExactMoney(s.closing_balance, s.currency)] }), _jsx("table", { "aria-label": "Statement entries", className: "min-w-full text-xs", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: s.entries.map((e) => (_jsxs("tr", { children: [_jsx("td", { className: "py-1 pr-3 font-mono text-slate-500", children: e.date }), _jsx("td", { className: "py-1 pr-3 text-slate-900", children: e.description }), _jsx("td", { className: `py-1 pr-3 text-right tabular-nums ${e.amount < 0 ? "text-rose-700" : "text-emerald-700"}`, children: formatExactMoney(e.amount, s.currency) }), _jsx("td", { className: "py-1 text-right tabular-nums text-slate-600", children: formatExactMoney(e.balance, s.currency) })] }, e.entry_number))) }) })] }))] }));
}
function MonthEndPanel() {
    const { can } = useAuth();
    const runs = useMonthEnds();
    const run = useRunMonthEnd();
    const statements = useStatements();
    const [open, setOpen] = useState(null);
    return (_jsxs(Panel, { title: "Month end and statements", subtitle: "Month end posts credit interest, overdraft interest and monthly fees on the last day of the month, then issues each account's statement. It runs once per month.", children: [can("retail:manage") && (_jsxs("div", { className: "mb-3 flex items-center gap-2", children: [_jsx(Button, { size: "sm", onClick: () => run.mutate(null), disabled: run.isPending, children: "Run month end" }), run.data && _jsxs("span", { role: "status", className: "text-xs text-slate-600", children: ["Job #", run.data.job_number, " queued for the last complete month."] })] })), _jsx(ErrorMessage, { error: run.error ?? runs.error ?? statements.error }), _jsx("table", { "aria-label": "Month-end runs", className: "mb-4 min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [runs.data?.map((r) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-medium text-slate-900", children: r.period_start.slice(0, 7) }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [r.accounts, " accounts \u00B7 ", r.entries, " postings \u00B7 ", r.statements, " statements"] }), _jsx("td", { className: "px-2 py-1.5 text-xs text-slate-500", children: Object.entries(r.totals)
                                        .slice(0, 4)
                                        .map(([ccy, t]) => `${ccy}: interest ${formatExactMoney(t.interest_paid, ccy)} paid, ${formatExactMoney(t.interest_charged, ccy)} charged, fees ${formatExactMoney(t.fees, ccy)}`)
                                        .join(" · ") })] }, r.id))), runs.data?.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No month end has run yet." }) }))] }) }), _jsx("h3", { className: "mb-1 text-xs font-medium tracking-wide text-slate-500 uppercase", children: "Recent statements" }), _jsx("ul", { "aria-label": "Recent statements", className: "divide-y divide-slate-100 text-sm", children: statements.data?.items.map((s) => (_jsxs("li", { className: "flex items-center justify-between gap-3 py-1.5", children: [_jsx("button", { type: "button", className: "font-mono text-xs text-navy-700 hover:underline", onClick: () => setOpen(s.id), children: s.statement_number }), _jsxs("span", { className: "text-xs text-slate-600", children: [s.account_number, " \u00B7 ", s.period_start.slice(0, 7), " \u00B7 ", s.lines, " entries"] }), _jsx("span", { className: "tabular-nums", children: formatExactMoney(s.closing_balance, s.currency) })] }, s.id))) }), open && _jsx(StatementView, { id: open, onClose: () => setOpen(null) })] }));
}
/** Retail banking (Phase 29): products, standing orders, month end and statements. */
export function RetailPage() {
    const summary = useRetailSummary();
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Retail Banking", description: "Deposit products and their terms, arranged overdrafts, standing orders, and the month end that pays interest, charges fees and issues statements \u2014 every amount through the ledger." }), summary.data && (_jsx("dl", { "aria-label": "Retail summary", className: "mb-6 grid grid-cols-3 gap-3 text-sm", children: [
                    ["Arranged overdrafts", summary.data.overdrafts],
                    ["Active standing orders", summary.data.active_standing_orders],
                    ["Statements issued", summary.data.statements],
                ].map(([label, value]) => (_jsxs("div", { className: "rounded-lg border border-slate-200 bg-white p-3", children: [_jsx("dt", { className: "text-xs text-slate-500", children: label }), _jsx("dd", { className: "text-lg font-semibold text-slate-900", children: value })] }, label))) })), _jsxs("div", { className: "space-y-6", children: [_jsx(ProductsPanel, {}), _jsx(StandingOrdersPanel, {}), _jsx(MonthEndPanel, {})] })] }));
}
