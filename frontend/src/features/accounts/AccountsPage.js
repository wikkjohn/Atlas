import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { CheckCircle2, Search, XCircle } from "lucide-react";
import { Fragment, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "@/app/auth";
import { ACCOUNT_TYPE_LABELS, AccountStatusBadge, RequestStatusBadge, RiskBadge, } from "@/components/BankingBadges";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { formatTimestamp } from "@/features/dashboard/format";
import { newIdempotencyKey } from "@/services/api";
import { useAccount, useAccountRequests, useAccounts, useAccountStatus, useDecideRequest, useJournalEntries, useLedgerAccounts, useMovement, useReconciliation, useReconciliationRuns, useTransactions, } from "@/services/banking";
import { currencyDigits, formatMoney, humanize, toMinorUnits } from "@/services/format";
const PAGE_SIZE = 25;
/** Exact amount with the currency's minor digits (statements need precision). */
function exactMoney(minor, currency) {
    const digits = currencyDigits(currency);
    try {
        return new Intl.NumberFormat("en", {
            style: "currency",
            currency,
            minimumFractionDigits: digits,
            maximumFractionDigits: digits,
        }).format(minor / 10 ** digits);
    }
    catch {
        return `${minor} ${currency}`;
    }
}
function MovementForm({ account, kind }) {
    const movement = useMovement(account.id);
    const [amount, setAmount] = useState("");
    // One key per intended transaction: a retry after a failure reuses it, so the ledger
    // can never post the same deposit twice. A fresh key is taken after success.
    const [key, setKey] = useState(newIdempotencyKey);
    const label = kind === "deposits" ? "Deposit" : "Withdraw";
    const onSubmit = (event) => {
        event.preventDefault();
        movement.mutate({ kind, amount: toMinorUnits(Number(amount), account.currency), idempotencyKey: key }, {
            onSuccess: () => {
                setAmount("");
                setKey(newIdempotencyKey());
            },
        });
    };
    return (_jsxs("form", { onSubmit: onSubmit, "aria-label": label, className: "space-y-2", children: [_jsxs("div", { className: "flex items-end gap-2", children: [_jsx(Field, { label: `${label} (${account.currency})`, children: (p) => (_jsx("input", { ...p, className: inputClass, type: "number", min: 1 / 10 ** currencyDigits(account.currency), step: 1 / 10 ** currencyDigits(account.currency), required: true, value: amount, onChange: (e) => {
                                setAmount(e.target.value);
                                setKey(newIdempotencyKey());
                            } })) }), _jsx(Button, { type: "submit", variant: kind === "deposits" ? "primary" : "secondary", disabled: movement.isPending, children: label })] }), movement.data && (_jsxs("p", { role: "status", className: "text-xs text-emerald-700", children: ["Posted ", movement.data.entry_number, movement.data.replayed ? " (already posted — not repeated)" : "", "."] })), _jsx(ErrorMessage, { error: movement.error })] }));
}
function StatusActions({ account }) {
    const change = useAccountStatus(account.id);
    const [reason, setReason] = useState("");
    if (account.status === "closed")
        return null;
    const actions = account.status === "open"
        ? [
            { action: "freeze", label: "Freeze" },
            { action: "close", label: "Close account" },
        ]
        : [
            { action: "unfreeze", label: "Unfreeze" },
            { action: "close", label: "Close account" },
        ];
    return (_jsxs("section", { "aria-label": "Account controls", className: "space-y-2 rounded-lg border border-slate-200 p-4", children: [_jsx("h4", { className: "text-xs font-semibold tracking-wide text-slate-500 uppercase", children: "Controls" }), _jsx(Field, { label: "Reason", hint: "Recorded in the audit log.", children: (p) => _jsx("input", { ...p, className: inputClass, value: reason, onChange: (e) => setReason(e.target.value) }) }), _jsx("div", { className: "flex gap-2", children: actions.map(({ action, label }) => (_jsx(Button, { size: "sm", variant: action === "close" ? "danger" : "secondary", disabled: reason.trim().length < 3 || change.isPending, onClick: () => change.mutate({ action, reason: reason.trim() }, { onSuccess: () => setReason("") }), children: label }, action))) }), _jsx(ErrorMessage, { error: change.error })] }));
}
function AccountDetail({ id, onClose }) {
    const { can } = useAuth();
    const account = useAccount(id);
    const transactions = useTransactions(id);
    const a = account.data;
    return (_jsxs(Modal, { wide: true, title: "Account", onClose: onClose, children: [_jsx(ErrorMessage, { error: account.error }), a && (_jsxs("div", { className: "space-y-5", children: [_jsxs("div", { className: "flex flex-wrap items-start justify-between gap-3", children: [_jsxs("div", { children: [_jsx("h3", { className: "font-mono text-lg font-semibold text-slate-900", children: a.account_number }), _jsxs("p", { className: "text-sm text-slate-600", children: [a.customer_name, " \u00B7 ", ACCOUNT_TYPE_LABELS[a.account_type], " \u00B7 opened ", formatTimestamp(a.opened_at)] }), _jsxs("p", { className: "font-mono text-[11px] text-slate-500", children: ["Ledger account ", a.ledger_account_code] })] }), _jsxs("div", { className: "text-right", children: [_jsx(AccountStatusBadge, { status: a.status }), _jsx("p", { "aria-label": "Balance", className: "mt-1 text-2xl font-semibold text-slate-900", children: exactMoney(a.balance, a.currency) }), _jsx("p", { className: "text-[11px] text-slate-500", children: "Derived from posted ledger entries" }), a.overdraft_limit > 0 && (_jsxs("p", { "aria-label": "Overdraft", className: "text-xs text-slate-600", children: ["Arranged overdraft ", exactMoney(a.overdraft_limit, a.currency), " \u00B7 available ", exactMoney(a.available, a.currency)] }))] })] }), can("accounts:transact") && a.status === "open" && (_jsxs("div", { className: "grid grid-cols-1 gap-4 sm:grid-cols-2", children: [_jsx(MovementForm, { account: a, kind: "deposits" }), _jsx(MovementForm, { account: a, kind: "withdrawals" })] })), _jsxs("section", { "aria-label": "Transactions", children: [_jsx("h4", { className: "mb-1.5 text-xs font-semibold tracking-wide text-slate-500 uppercase", children: "Transactions" }), transactions.data?.items.length === 0 && _jsx("p", { className: "text-sm text-slate-500", children: "No postings yet." }), _jsx("table", { className: "min-w-full text-sm", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: transactions.data?.items.map((t) => (_jsxs("tr", { children: [_jsx("td", { className: "py-1.5 text-xs whitespace-nowrap text-slate-500", children: formatTimestamp(t.posted_at) }), _jsx("td", { className: "py-1.5 font-mono text-xs text-slate-500", children: t.entry_number }), _jsx("td", { className: "py-1.5 text-slate-700", children: t.description }), _jsxs("td", { className: `py-1.5 text-right font-medium whitespace-nowrap ${t.direction === "credit" ? "text-emerald-700" : "text-slate-900"}`, children: [t.direction === "credit" ? "+" : "−", exactMoney(t.amount, a.currency)] })] }, `${t.entry_id}-${t.direction}`))) }) })] }), can("accounts:manage") && _jsx(StatusActions, { account: a }, a.status)] }))] }));
}
function AccountsTab({ onOpen }) {
    const [search, setSearch] = useState("");
    const [q, setQ] = useState("");
    const [status, setStatus] = useState("");
    const [offset, setOffset] = useState(0);
    const accounts = useAccounts({ q: q || undefined, status: status || undefined, limit: PAGE_SIZE, offset });
    return (_jsxs(_Fragment, { children: [_jsxs("div", { className: "mb-4 flex flex-wrap items-center gap-3", children: [_jsxs("form", { role: "search", className: "relative", onSubmit: (e) => {
                            e.preventDefault();
                            setQ(search.trim());
                            setOffset(0);
                        }, children: [_jsx(Search, { "aria-hidden": true, className: "pointer-events-none absolute top-2 left-2.5 h-4 w-4 text-slate-400" }), _jsx("input", { "aria-label": "Search accounts", placeholder: "Account number or customer", className: "w-64 rounded-lg border border-slate-200 bg-white py-1.5 pr-3 pl-8 text-sm", value: search, onChange: (e) => setSearch(e.target.value) })] }), _jsxs("select", { "aria-label": "Account status", className: "rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm", value: status, onChange: (e) => {
                            setStatus(e.target.value);
                            setOffset(0);
                        }, children: [_jsx("option", { value: "", children: "Any status" }), _jsx("option", { value: "open", children: "Open" }), _jsx("option", { value: "frozen", children: "Frozen" }), _jsx("option", { value: "closed", children: "Closed" })] })] }), _jsx(ErrorMessage, { error: accounts.error, className: "mb-4" }), _jsx("div", { className: "overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm", children: _jsxs("table", { className: "min-w-full text-sm", children: [_jsx("thead", { className: "bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-4 py-2.5", children: "Account" }), _jsx("th", { className: "px-4 py-2.5", children: "Customer" }), _jsx("th", { className: "px-4 py-2.5", children: "Type" }), _jsx("th", { className: "px-4 py-2.5", children: "Status" }), _jsx("th", { className: "px-4 py-2.5 text-right", children: "Balance" })] }) }), _jsxs("tbody", { className: "divide-y divide-slate-100", children: [accounts.data?.items.length === 0 && (_jsx("tr", { children: _jsx("td", { colSpan: 5, className: "px-4 py-6 text-center text-slate-500", children: "No accounts match." }) })), accounts.data?.items.map((a) => (_jsxs("tr", { className: "cursor-pointer hover:bg-slate-50", onClick: () => onOpen(a.id), children: [_jsx("td", { className: "px-4 py-2.5", children: _jsx("button", { type: "button", className: "font-mono text-sm text-slate-900 hover:underline", children: a.account_number }) }), _jsx("td", { className: "px-4 py-2.5 text-slate-700", children: a.customer_name }), _jsx("td", { className: "px-4 py-2.5 text-slate-600", children: ACCOUNT_TYPE_LABELS[a.account_type] }), _jsx("td", { className: "px-4 py-2.5", children: _jsx(AccountStatusBadge, { status: a.status }) }), _jsx("td", { className: "px-4 py-2.5 text-right font-medium whitespace-nowrap text-slate-900", children: formatMoney(a.balance, a.currency) })] }, a.id)))] })] }) }), accounts.data && (_jsx("div", { className: "mt-3", children: _jsx(Pagination, { total: accounts.data.total, limit: PAGE_SIZE, offset: offset, onChange: setOffset }) }))] }));
}
function RequestActions({ request }) {
    const { user, can } = useAuth();
    const decide = useDecideRequest();
    const [rejecting, setRejecting] = useState(false);
    const [reason, setReason] = useState("");
    if (request.status !== "pending" || !can("accounts:approve"))
        return null;
    if (request.requested_by === user?.id) {
        return _jsx("span", { className: "text-xs text-slate-400", title: "Four-eyes rule", children: "Needs another approver" });
    }
    return (_jsxs("div", { className: "flex flex-col items-end gap-1", children: [_jsxs("div", { className: "flex gap-1.5", children: [_jsxs(Button, { size: "sm", disabled: decide.isPending, onClick: () => decide.mutate({ id: request.id, decision: "approve", body: { note: null } }), children: [_jsx(CheckCircle2, { "aria-hidden": true, className: "h-3.5 w-3.5" }), "Approve"] }), _jsxs(Button, { size: "sm", variant: "secondary", onClick: () => setRejecting(true), children: [_jsx(XCircle, { "aria-hidden": true, className: "h-3.5 w-3.5" }), "Reject"] })] }), decide.error && _jsx(ErrorMessage, { error: decide.error, className: "max-w-xs text-left text-xs" }), rejecting && (_jsx(Modal, { title: "Reject account request", onClose: () => setRejecting(false), footer: _jsx(Button, { variant: "danger", disabled: reason.trim().length < 3 || decide.isPending, onClick: () => decide.mutate({ id: request.id, decision: "reject", body: { reason: reason.trim() } }, { onSuccess: () => setRejecting(false) }), children: "Reject request" }), children: _jsx(Field, { label: "Reason", children: (p) => _jsx("input", { ...p, className: inputClass, value: reason, onChange: (e) => setReason(e.target.value) }) }) }))] }));
}
function RequestsTab() {
    const [status, setStatus] = useState("pending");
    const [offset, setOffset] = useState(0);
    const requests = useAccountRequests({ status: status || undefined, limit: PAGE_SIZE, offset });
    return (_jsxs(_Fragment, { children: [_jsxs("div", { className: "mb-4 flex items-center gap-3", children: [_jsxs("select", { "aria-label": "Request status", className: "rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm", value: status, onChange: (e) => {
                            setStatus(e.target.value);
                            setOffset(0);
                        }, children: [_jsx("option", { value: "pending", children: "Pending" }), _jsx("option", { value: "approved", children: "Approved" }), _jsx("option", { value: "rejected", children: "Rejected" }), _jsx("option", { value: "", children: "All" })] }), _jsx("p", { className: "text-xs text-slate-500", children: "Approval opens the account. Requesters cannot approve their own requests; high-risk customers need a compliance approver." })] }), _jsx(ErrorMessage, { error: requests.error, className: "mb-4" }), _jsx("div", { className: "overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm", children: _jsxs("table", { className: "min-w-full text-sm", children: [_jsx("thead", { className: "bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-4 py-2.5", children: "Customer" }), _jsx("th", { className: "px-4 py-2.5", children: "Account" }), _jsx("th", { className: "px-4 py-2.5", children: "Requested" }), _jsx("th", { className: "px-4 py-2.5", children: "Status" }), _jsx("th", { className: "px-4 py-2.5 text-right", children: "Decision" })] }) }), _jsxs("tbody", { className: "divide-y divide-slate-100", children: [requests.data?.items.length === 0 && (_jsx("tr", { children: _jsx("td", { colSpan: 5, className: "px-4 py-6 text-center text-slate-500", children: "No requests." }) })), requests.data?.items.map((r) => (_jsxs("tr", { children: [_jsxs("td", { className: "px-4 py-2.5", children: [_jsx("div", { className: "font-medium text-slate-900", children: r.customer_name }), _jsxs("div", { className: "mt-0.5 flex items-center gap-2", children: [_jsx("span", { className: "font-mono text-[11px] text-slate-500", children: r.customer_number }), _jsx(RiskBadge, { rating: r.customer_risk_rating })] })] }), _jsxs("td", { className: "px-4 py-2.5 text-slate-700", children: [ACCOUNT_TYPE_LABELS[r.account_type], " \u00B7 ", r.currency] }), _jsxs("td", { className: "px-4 py-2.5 text-xs text-slate-600", children: [r.requested_by_username, _jsx("div", { className: "text-slate-400", children: formatTimestamp(r.created_at) })] }), _jsxs("td", { className: "px-4 py-2.5", children: [_jsx(RequestStatusBadge, { status: r.status }), r.decided_by_username && (_jsxs("div", { className: "mt-0.5 text-[11px] text-slate-500", children: ["by ", r.decided_by_username] }))] }), _jsx("td", { className: "px-4 py-2.5 text-right", children: _jsx(RequestActions, { request: r }) })] }, r.id)))] })] }) }), requests.data && (_jsx("div", { className: "mt-3", children: _jsx(Pagination, { total: requests.data.total, limit: PAGE_SIZE, offset: offset, onChange: setOffset }) }))] }));
}
function ReconciliationHistory() {
    const runs = useReconciliationRuns();
    if (!runs.data?.items.length)
        return null;
    return (_jsx("div", { className: "mt-4 overflow-x-auto", children: _jsxs("table", { "aria-label": "Reconciliation history", className: "min-w-full text-sm", children: [_jsx("thead", { className: "text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-2 py-1", children: "Run" }), _jsx("th", { className: "px-2 py-1", children: "Mode" }), _jsx("th", { className: "px-2 py-1", children: "Result" }), _jsx("th", { className: "px-2 py-1 text-right", children: "Entries" }), _jsx("th", { className: "px-2 py-1 text-right", children: "Duration" }), _jsx("th", { className: "px-2 py-1", children: "By" })] }) }), _jsx("tbody", { className: "divide-y divide-slate-100", children: runs.data.items.map((r) => (_jsxs("tr", { children: [_jsxs("td", { className: "px-2 py-1.5", children: [_jsxs("span", { className: "font-mono text-xs", children: ["#", r.run_number] }), _jsx("span", { className: "ml-2 text-[11px] text-slate-400", children: formatTimestamp(r.created_at) })] }), _jsx("td", { className: "px-2 py-1.5", children: humanize(r.mode) }), _jsx("td", { className: `px-2 py-1.5 ${r.ok ? "text-emerald-700" : "text-rose-700"}`, children: r.ok ? "Passed" : `Failed: ${r.failed_checks.join(", ")}` }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: r.entries_checked.toLocaleString() }), _jsxs("td", { className: "px-2 py-1.5 text-right tabular-nums", children: [r.duration_ms, " ms"] }), _jsx("td", { className: "px-2 py-1.5 text-slate-600", children: r.run_by_username ?? "—" })] }, r.id))) })] }) }));
}
function LedgerTab() {
    const [currency, setCurrency] = useState("");
    const [expanded, setExpanded] = useState(null);
    const reconciliation = useReconciliation();
    const accounts = useLedgerAccounts({ currency: currency || undefined, code_prefix: "1000-", limit: 20 });
    const entries = useJournalEntries({ currency: currency || undefined, limit: 25 });
    const report = reconciliation.data;
    return (_jsxs("div", { className: "space-y-6", children: [_jsxs("section", { "aria-label": "Reconciliation", className: "rounded-xl border border-slate-200 bg-white p-5 shadow-sm", children: [_jsxs("div", { className: "flex flex-wrap items-center justify-between gap-3", children: [_jsxs("div", { children: [_jsx("h2", { className: "text-sm font-semibold text-slate-900", children: "Reconciliation" }), _jsx("p", { className: "text-xs text-slate-500", children: "Verifies every entry balances, currencies match, debits equal credits per currency and the stored balances match their lines. An incremental check covers what was posted since the last run; a full run checks everything. Every run is recorded and audited." })] }), _jsxs("div", { className: "flex gap-2", children: [_jsx(Button, { variant: "secondary", onClick: () => reconciliation.mutate("incremental"), disabled: reconciliation.isPending, children: "Incremental check" }), _jsx(Button, { onClick: () => reconciliation.mutate("full"), disabled: reconciliation.isPending, children: reconciliation.isPending ? "Running…" : "Full reconciliation" })] })] }), _jsx(ErrorMessage, { error: reconciliation.error, className: "mt-3" }), report && (_jsxs("div", { className: "mt-4", children: [_jsxs("p", { className: `text-sm font-medium ${report.ok ? "text-emerald-700" : "text-rose-700"}`, children: [report.ok ? "All checks passed" : "Reconciliation found problems", " \u00B7 run #", report.run_number, " (", report.mode, ") \u00B7 ", report.entries_checked, " entries, ", report.lines_checked, " lines", report.duration_ms !== null && ` · ${report.duration_ms} ms`] }), report.window_start && (_jsxs("p", { className: "text-xs text-slate-500", children: ["Entries posted since ", formatTimestamp(report.window_start)] })), _jsx("ul", { className: "mt-2 space-y-1 text-sm", children: report.checks.map((check) => (_jsxs("li", { className: "flex items-start gap-2", children: [check.passed ? (_jsx(CheckCircle2, { "aria-label": "passed", className: "mt-0.5 h-4 w-4 shrink-0 text-emerald-600" })) : (_jsx(XCircle, { "aria-label": "failed", className: "mt-0.5 h-4 w-4 shrink-0 text-rose-600" })), _jsxs("span", { children: [_jsx("span", { className: "font-medium text-slate-900", children: check.name }), _jsxs("span", { className: "text-slate-500", children: [" \u2014 ", check.detail] })] })] }, check.name))) })] })), _jsx(ReconciliationHistory, {})] }), _jsxs("div", { className: "flex items-center gap-3", children: [_jsx("label", { htmlFor: "ledger-currency", className: "text-xs font-medium text-slate-600", children: "Currency" }), _jsxs("select", { id: "ledger-currency", className: "rounded-lg border border-slate-200 bg-white px-2 py-1 text-sm", value: currency, onChange: (e) => setCurrency(e.target.value), children: [_jsx("option", { value: "", children: "All" }), ["USD", "GBP", "EUR", "SGD", "JPY"].map((c) => (_jsx("option", { value: c, children: c }, c)))] })] }), _jsxs("section", { "aria-label": "Cash accounts", className: "rounded-xl border border-slate-200 bg-white shadow-sm", children: [_jsx("h2", { className: "border-b border-slate-100 px-5 py-3 text-sm font-semibold text-slate-900", children: "Bank cash accounts" }), _jsx("table", { className: "min-w-full text-sm", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: accounts.data?.items.map((a) => (_jsxs("tr", { children: [_jsx("td", { className: "px-5 py-2 font-mono text-xs text-slate-700", children: a.code }), _jsx("td", { className: "px-5 py-2 text-slate-700", children: a.name }), _jsx("td", { className: "px-5 py-2 text-right font-medium text-slate-900", children: exactMoney(a.balance, a.currency) })] }, a.id))) }) })] }), _jsxs("section", { "aria-label": "Journal", className: "rounded-xl border border-slate-200 bg-white shadow-sm", children: [_jsx("h2", { className: "border-b border-slate-100 px-5 py-3 text-sm font-semibold text-slate-900", children: "Journal (latest)" }), _jsx(ErrorMessage, { error: entries.error, className: "m-4" }), _jsx("table", { className: "min-w-full text-sm", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: entries.data?.items.map((e) => (_jsxs(Fragment, { children: [_jsxs("tr", { className: "cursor-pointer hover:bg-slate-50", onClick: () => setExpanded(expanded === e.id ? null : e.id), children: [_jsx("td", { className: "px-5 py-2 font-mono text-xs text-slate-500", children: e.entry_number }), _jsx("td", { className: "px-5 py-2 text-xs whitespace-nowrap text-slate-500", children: formatTimestamp(e.posted_at) }), _jsx("td", { className: "px-5 py-2 text-slate-700", children: e.description }), _jsx("td", { className: "px-5 py-2 text-xs text-slate-500", children: e.status }), _jsx("td", { className: "px-5 py-2 text-right font-medium whitespace-nowrap", children: exactMoney(e.total, e.currency) })] }), expanded === e.id && (_jsx("tr", { className: "bg-slate-50", children: _jsx("td", { colSpan: 5, className: "px-5 py-2", children: _jsx("table", { "aria-label": `Lines of ${e.entry_number}`, className: "w-full text-xs", children: _jsx("tbody", { children: e.lines.map((line) => (_jsxs("tr", { children: [_jsx("td", { className: "py-0.5 font-mono", children: line.ledger_account_code }), _jsx("td", { className: "py-0.5", children: line.ledger_account_name }), _jsx("td", { className: "py-0.5 text-right", children: line.direction === "debit" ? exactMoney(line.amount, e.currency) : "" }), _jsx("td", { className: "py-0.5 text-right", children: line.direction === "credit" ? exactMoney(line.amount, e.currency) : "" })] }, line.line_number))) }) }) }) }))] }, e.id))) }) })] })] }));
}
export function AccountsPage() {
    const { can } = useAuth();
    const [params, setParams] = useSearchParams();
    const tab = params.get("tab") ?? "accounts";
    const openId = params.get("account");
    const tabs = [
        { id: "accounts", label: "Accounts", visible: true },
        { id: "requests", label: "Opening requests", visible: true },
        { id: "ledger", label: "General ledger", visible: can("ledger:read") },
    ];
    const set = (changes) => {
        const next = new URLSearchParams(params);
        for (const [key, value] of Object.entries(changes)) {
            if (value)
                next.set(key, value);
            else
                next.delete(key);
        }
        setParams(next);
    };
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Accounts", description: "Synthetic bank accounts. Balances are derived from the double-entry ledger; accounts open only through approved requests." }), _jsx("div", { role: "tablist", "aria-label": "Account views", className: "mb-5 flex gap-1 border-b border-slate-200", children: tabs
                    .filter((t) => t.visible)
                    .map((t) => (_jsx("button", { role: "tab", type: "button", "aria-selected": tab === t.id, onClick: () => set({ tab: t.id === "accounts" ? null : t.id }), className: `-mb-px border-b-2 px-3 py-2 text-sm font-medium ${tab === t.id ? "border-navy-900 text-navy-900" : "border-transparent text-slate-500 hover:text-slate-800"}`, children: t.label }, t.id))) }), tab === "accounts" && _jsx(AccountsTab, { onOpen: (id) => set({ account: id }) }), tab === "requests" && _jsx(RequestsTab, {}), tab === "ledger" && can("ledger:read") && _jsx(LedgerTab, {}), openId && _jsx(AccountDetail, { id: openId, onClose: () => set({ account: null }) }, openId)] }));
}
