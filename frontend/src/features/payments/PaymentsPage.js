import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { StatusPill } from "@/components/StatusPill";
import { SyntheticDataBadge } from "@/components/SyntheticDataBadge";
import { formatTimestamp } from "@/features/dashboard/format";
import { usePayments } from "@/services/banking";
import { formatExactMoney } from "@/services/format";
const PAGE_SIZE = 25;
const STATUS_TONE = { pending: "warn", released: "good", rejected: "bad" };
const FILTERS = [
    { value: "", label: "All" },
    { value: "pending", label: "In progress" },
    { value: "released", label: "Released" },
    { value: "rejected", label: "Rejected" },
];
export function PaymentsPage() {
    const [status, setStatus] = useState("");
    const [q, setQ] = useState("");
    const [offset, setOffset] = useState(0);
    const payments = usePayments({ status: status || null, q: q || null, limit: PAGE_SIZE, offset });
    return (_jsxs("div", { className: "space-y-6", children: [_jsx(PageHeader, { title: "Payments", description: "Domestic payments between synthetic accounts. Each one runs through WF-0002: screening, fraud review, four-eyes approval above the high-value limit and a balanced ledger posting.", actions: _jsx(SyntheticDataBadge, {}) }), _jsxs("div", { className: "flex flex-wrap items-center gap-3", children: [_jsx("div", { role: "tablist", "aria-label": "Payment status", className: "inline-flex rounded-lg border border-slate-200 bg-white p-0.5 text-xs", children: FILTERS.map((f) => (_jsx("button", { role: "tab", type: "button", "aria-selected": status === f.value, onClick: () => {
                                setStatus(f.value);
                                setOffset(0);
                            }, className: `rounded-md px-2.5 py-1 font-medium ${status === f.value ? "bg-navy-900 text-white" : "text-slate-600 hover:bg-slate-50"}`, children: f.label }, f.label))) }), _jsxs("div", { className: "relative", children: [_jsx(Search, { "aria-hidden": true, className: "pointer-events-none absolute top-2 left-2.5 h-4 w-4 text-slate-400" }), _jsx("input", { "aria-label": "Search payments", placeholder: "Payment number or reference", className: "w-64 rounded-lg border border-slate-200 bg-white py-1.5 pr-3 pl-8 text-sm", value: q, onChange: (e) => {
                                    setQ(e.target.value);
                                    setOffset(0);
                                } })] })] }), _jsx(ErrorMessage, { error: payments.error }), _jsx("div", { className: "overflow-x-auto rounded-xl border border-slate-200 bg-white", children: _jsxs("table", { "aria-label": "Payments", className: "min-w-full text-sm", children: [_jsx("thead", { className: "bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-3 py-2", children: "Payment" }), _jsx("th", { className: "px-3 py-2", children: "From" }), _jsx("th", { className: "px-3 py-2", children: "To" }), _jsx("th", { className: "px-3 py-2 text-right", children: "Amount" }), _jsx("th", { className: "px-3 py-2", children: "Status" }), _jsx("th", { className: "px-3 py-2", children: "Approved by" })] }) }), _jsxs("tbody", { className: "divide-y divide-slate-100", children: [payments.data?.items.map((p) => (_jsxs("tr", { className: "align-top", children: [_jsxs("td", { className: "px-3 py-2", children: [_jsx("div", { className: "font-mono text-xs text-slate-900", children: p.payment_number }), _jsx("div", { className: "text-xs text-slate-500", children: p.reference }), _jsx("div", { className: "text-[11px] text-slate-400", children: formatTimestamp(p.created_at) })] }), _jsxs("td", { className: "px-3 py-2", children: [_jsx("div", { className: "text-slate-900", children: p.debtor_name }), _jsx("div", { className: "font-mono text-[11px] text-slate-500", children: p.debtor_account_number })] }), _jsxs("td", { className: "px-3 py-2", children: [_jsx("div", { className: "text-slate-900", children: p.creditor_name }), _jsx("div", { className: "font-mono text-[11px] text-slate-500", children: p.creditor_account_number })] }), _jsxs("td", { className: "px-3 py-2 text-right tabular-nums", children: [formatExactMoney(p.amount, p.currency), p.creditor_currency && p.creditor_amount != null && (_jsxs("div", { className: "text-[11px] text-slate-500", title: p.fx_rate ? `Rate ${p.fx_rate}` : "Estimate at today's rate", children: ["\u2192 ", formatExactMoney(p.creditor_amount, p.creditor_currency), p.fx_deal_number ? ` · ${p.fx_deal_number}` : " (est.)"] })), p.high_value && _jsx("div", { className: "text-[11px] text-amber-700", children: "High value" }), p.value_date && _jsxs("div", { className: "text-[11px] text-slate-500", children: ["Value date ", p.value_date] })] }), _jsxs("td", { className: "px-3 py-2", children: [_jsx(StatusPill, { tone: STATUS_TONE[p.status], label: p.status === "pending" ? "In progress" : p.status === "released" ? "Released" : "Rejected" }), p.rejection_reason && _jsx("div", { className: "mt-1 max-w-xs text-xs text-slate-500", children: p.rejection_reason }), p.workflow_execution_id && (_jsx(Link, { className: "mt-1 block text-xs text-navy-700 underline", to: `/workflows?tab=executions&execution=${p.workflow_execution_id}`, children: "Workflow case" }))] }), _jsx("td", { className: "px-3 py-2 text-xs text-slate-600", children: p.approved_by_username ?? (p.status === "released" ? "Straight-through" : "—") })] }, p.id))), payments.data?.items.length === 0 && (_jsx("tr", { children: _jsx("td", { colSpan: 6, className: "px-3 py-6 text-center text-sm text-slate-500", children: "No payments yet. Start one from the Workflow Explorer (WF-0002)." }) }))] })] }) }), payments.data && _jsx(Pagination, { total: payments.data.total, limit: PAGE_SIZE, offset: offset, onChange: setOffset })] }));
}
