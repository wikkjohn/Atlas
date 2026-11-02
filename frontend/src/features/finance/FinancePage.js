import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { FINANCE_PAGE, downloadReportCsv, useAllocations, useCalculateAllocation, useCloses, useDecideAllocation, useDecideClose, useDecideJournal, useDecideReport, useFinanceSummary, useJournals, useProposeJournal, usePrepareClose, usePrepareReport, useRecordExpense, useReports, } from "@/services/finance";
import { formatExactMoney, toMinorUnits } from "@/services/format";
import { CHECK_LABELS, REPORT_LABELS } from "@/types/finance";
const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const TONE = { proposed: "warn", prepared: "warn", calculated: "warn", closed: "good", submitted: "good", posted: "good", rejected: "neutral" };
const lastMonth = () => {
    const d = new Date();
    d.setDate(0);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};
const thisMonth = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};
/** Newer/older paging, `FINANCE_PAGE` rows at a time. */
function Pager({ label, offset, total, onChange }) {
    if (total <= FINANCE_PAGE)
        return null;
    return (_jsxs("nav", { "aria-label": label, className: "mt-2 flex items-center justify-end gap-2 text-xs text-slate-600", children: [_jsxs("span", { children: [offset + 1, "\u2013", Math.min(offset + FINANCE_PAGE, total), " of ", total] }), _jsx(Button, { size: "sm", variant: "secondary", disabled: offset === 0, onClick: () => onChange(Math.max(offset - FINANCE_PAGE, 0)), children: "Newer" }), _jsx(Button, { size: "sm", variant: "secondary", disabled: offset + FINANCE_PAGE >= total, onClick: () => onChange(offset + FINANCE_PAGE), children: "Older" })] }));
}
function ClosePanel({ nextPeriod }) {
    const { can } = useAuth();
    const [offset, setOffset] = useState(0);
    const closes = useCloses(offset);
    const prepare = usePrepareClose();
    const decide = useDecideClose();
    const [period, setPeriod] = useState(nextPeriod ?? lastMonth());
    return (_jsxs(Panel, { title: "Month-end close", subtitle: "Preparing a close checks the ledger as of the month's end (the month is over, debits equal credits, a reconciliation has passed since; ECL provisions are advisory) and measures each currency's result. Someone else closes the month, bringing income and expense to zero against retained earnings. Months close in order.", children: [can("finance:close") && (_jsxs("form", { "aria-label": "Prepare close", className: "mb-3 flex flex-wrap items-end gap-2 text-xs", onSubmit: (e) => {
                    e.preventDefault();
                    prepare.mutate(period);
                }, children: [_jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Month", _jsx("input", { "aria-label": "Close month", type: "month", className: INPUT, value: period, onChange: (e) => setPeriod(e.target.value) })] }), _jsx(Button, { size: "sm", type: "submit", disabled: prepare.isPending, children: "Prepare close" }), _jsx(ErrorMessage, { error: prepare.error })] })), _jsx(ErrorMessage, { error: closes.error ?? decide.error }), _jsx("table", { "aria-label": "Closes", className: "min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [closes.data?.items.map((c) => (_jsxs("tr", { className: "align-top", children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: c.close_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [_jsxs("div", { children: [c.period, " \u00B7", " ", c.checks.map((k) => (_jsxs("span", { title: k.detail, className: k.passed ? "text-emerald-700" : k.blocking ? "text-rose-700" : "text-amber-700", children: [CHECK_LABELS[k.check], " ", k.passed ? "✓" : "✗", " "] }, k.check)))] }), Object.entries(c.results).map(([ccy, r]) => (_jsxs("div", { children: [ccy, ": income ", formatExactMoney(r.income, ccy), ", expense ", formatExactMoney(r.expense, ccy), ", net ", formatExactMoney(r.net_income, ccy)] }, ccy))), c.note && _jsx("div", { children: c.note })] }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: TONE[c.status], label: c.status }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: c.status === "prepared" && can("finance:approve") && (_jsxs("div", { className: "flex justify-end gap-1", children: [_jsx(Button, { size: "sm", "aria-label": `Close ${c.close_number}`, onClick: () => decide.mutate({ id: c.id, approve: true }), children: "Close month" }), _jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Reject ${c.close_number}`, onClick: () => decide.mutate({ id: c.id, approve: false }), children: "Reject" })] })) })] }, c.id))), closes.data && closes.data.items.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No closes yet." }) }))] }) }), _jsx(Pager, { label: "Close pages", offset: offset, total: closes.data?.total ?? 0, onChange: setOffset })] }));
}
function ReportsPanel({ lastClosed }) {
    const { can } = useAuth();
    const [offset, setOffset] = useState(0);
    const reports = useReports(offset);
    const prepare = usePrepareReport();
    const decide = useDecideReport();
    const [type, setType] = useState("balance_sheet");
    const [period, setPeriod] = useState(lastClosed ?? lastMonth());
    const [open, setOpen] = useState(null);
    return (_jsxs(Panel, { title: "Regulatory reports", subtitle: "Extracts for a closed month: balance sheet and income statement by currency, large exposures (obligors of US$10,000 or more) and credit quality (the latest posted ECL run by stage). Someone other than the preparer submits each to the synthetic regulator; one of a type per month.", children: [can("finance:close") && (_jsxs("form", { "aria-label": "Prepare report", className: "mb-3 flex flex-wrap items-end gap-2 text-xs", onSubmit: (e) => {
                    e.preventDefault();
                    prepare.mutate({ report_type: type, period });
                }, children: [_jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Report", _jsx("select", { "aria-label": "Report type", className: INPUT, value: type, onChange: (e) => setType(e.target.value), children: Object.keys(REPORT_LABELS).map((t) => (_jsx("option", { value: t, children: REPORT_LABELS[t] }, t))) })] }), _jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Month", _jsx("input", { "aria-label": "Report month", type: "month", className: INPUT, value: period, onChange: (e) => setPeriod(e.target.value) })] }), _jsx(Button, { size: "sm", type: "submit", disabled: prepare.isPending, children: "Extract" }), _jsx(ErrorMessage, { error: prepare.error })] })), _jsx(ErrorMessage, { error: reports.error ?? decide.error }), _jsx("table", { "aria-label": "Reports", className: "min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [reports.data?.items.map((r) => (_jsxs("tr", { className: "align-top", children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: _jsx("button", { type: "button", className: "underline decoration-dotted", "aria-expanded": open === r.id, "aria-label": `Rows of ${r.report_number}`, onClick: () => setOpen(open === r.id ? null : r.id), children: r.report_number }) }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [REPORT_LABELS[r.report_type], " \u00B7 ", r.period, " \u00B7 ", r.rows.length, " rows", r.reference && ` · ${r.reference}`, open === r.id && (_jsx("table", { "aria-label": "Report rows", className: "mt-1 min-w-full", children: _jsx("tbody", { children: r.rows.map((row, i) => (_jsx("tr", { children: Object.values(row).map((v, j) => (_jsx("td", { className: "pr-3 tabular-nums", children: String(v) }, j))) }, i))) }) }))] }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: TONE[r.status], label: r.status }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: _jsxs("div", { className: "flex justify-end gap-1", children: [_jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Download ${r.report_number}`, onClick: () => void downloadReportCsv(r), children: "CSV" }), r.status === "prepared" && can("finance:approve") && (_jsxs(_Fragment, { children: [_jsx(Button, { size: "sm", "aria-label": `Submit ${r.report_number}`, onClick: () => decide.mutate({ id: r.id, submit: true }), children: "Submit" }), _jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Reject ${r.report_number}`, onClick: () => decide.mutate({ id: r.id, submit: false }), children: "Reject" })] }))] }) })] }, r.id))), reports.data && reports.data.items.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No reports yet." }) }))] }) }), _jsx(Pager, { label: "Report pages", offset: offset, total: reports.data?.total ?? 0, onChange: setOffset })] }));
}
function CostsPanel() {
    const { can } = useAuth();
    const [offset, setOffset] = useState(0);
    const allocations = useAllocations(offset);
    const expense = useRecordExpense();
    const calculate = useCalculateAllocation();
    const decide = useDecideAllocation();
    const [currency, setCurrency] = useState("USD");
    const [amount, setAmount] = useState("");
    const [description, setDescription] = useState("Office rent");
    const [period, setPeriod] = useState(thisMonth());
    return (_jsxs(Panel, { title: "Shared costs and allocation", subtitle: "Shared operating costs (rent, technology, utilities) are paid from cash into a shared pool per currency. An allocation splits a month's pool across departments by their active headcount; someone else posts it to the departments' cost centres while the month is open.", children: [can("finance:close") && (_jsxs("div", { className: "mb-3 flex flex-col gap-2 text-xs", children: [_jsxs("form", { "aria-label": "Record expense", className: "flex flex-wrap items-end gap-2", onSubmit: (e) => {
                            e.preventDefault();
                            expense.mutate({ currency, amount: toMinorUnits(Number(amount), currency), description });
                        }, children: [_jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Currency", _jsx("input", { "aria-label": "Expense currency", className: `w-16 ${INPUT}`, maxLength: 3, value: currency, onChange: (e) => setCurrency(e.target.value.toUpperCase()) })] }), _jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Amount", _jsx("input", { "aria-label": "Expense amount", type: "number", min: 0.01, step: "0.01", className: `w-28 ${INPUT}`, value: amount, onChange: (e) => setAmount(e.target.value) })] }), _jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Description", _jsx("input", { "aria-label": "Expense description", className: `w-48 ${INPUT}`, value: description, onChange: (e) => setDescription(e.target.value) })] }), _jsx(Button, { size: "sm", type: "submit", disabled: expense.isPending || !amount, children: "Record cost" }), expense.data && _jsxs("span", { role: "status", children: [expense.data.entry_number, " posted"] }), _jsx(ErrorMessage, { error: expense.error })] }), _jsxs("form", { "aria-label": "Allocate costs", className: "flex flex-wrap items-end gap-2", onSubmit: (e) => {
                            e.preventDefault();
                            calculate.mutate({ period, currency });
                        }, children: [_jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Month", _jsx("input", { "aria-label": "Allocation month", type: "month", className: INPUT, value: period, onChange: (e) => setPeriod(e.target.value) })] }), _jsxs(Button, { size: "sm", type: "submit", disabled: calculate.isPending, children: ["Split ", currency, " costs"] }), _jsx(ErrorMessage, { error: calculate.error })] })] })), _jsx(ErrorMessage, { error: allocations.error ?? decide.error }), _jsx("table", { "aria-label": "Allocations", className: "min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [allocations.data?.items.map((a) => (_jsxs("tr", { className: "align-top", children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: a.allocation_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [a.period, " \u00B7 ", formatExactMoney(a.pool, a.currency), " across ", a.lines.length, " departments by headcount", _jsxs("ul", { className: "mt-0.5", children: [a.lines.slice(0, 5).map((l) => (_jsxs("li", { children: [l.department, " (", l.headcount, "): ", formatExactMoney(l.amount, a.currency)] }, l.department_id))), a.lines.length > 5 && _jsxs("li", { children: ["and ", a.lines.length - 5, " more"] })] })] }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: TONE[a.status], label: a.status }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: a.status === "calculated" && can("finance:approve") && (_jsxs("div", { className: "flex justify-end gap-1", children: [_jsx(Button, { size: "sm", "aria-label": `Post ${a.allocation_number}`, onClick: () => decide.mutate({ id: a.id, post: true }), children: "Post" }), _jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Reject ${a.allocation_number}`, onClick: () => decide.mutate({ id: a.id, post: false }), children: "Reject" })] })) })] }, a.id))), allocations.data && allocations.data.items.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No allocations yet." }) }))] }) }), _jsx(Pager, { label: "Allocation pages", offset: offset, total: allocations.data?.total ?? 0, onChange: setOffset })] }));
}
function JournalsPanel() {
    const { can } = useAuth();
    const [offset, setOffset] = useState(0);
    const journals = useJournals(offset);
    const propose = useProposeJournal();
    const decide = useDecideJournal();
    const [form, setForm] = useState({ currency: "USD", debit: "", credit: "", amount: "", description: "" });
    const today = new Date().toISOString().slice(0, 10);
    return (_jsxs(Panel, { title: "Manual journals", subtitle: "Journals on the bank's own ledger accounts (never a customer's), debits equal to credits, posted only when someone other than the preparer approves. The approver sees the journal's size against materiality (US$100,000), the accounts it touches, how far back it is dated, and any identical journal posted recently.", children: [can("finance:close") && (_jsxs("form", { "aria-label": "Propose journal", className: "mb-3 flex flex-wrap items-end gap-2 text-xs", onSubmit: (e) => {
                    e.preventDefault();
                    const amount = toMinorUnits(Number(form.amount), form.currency);
                    propose.mutate({
                        currency: form.currency,
                        effective_date: today,
                        description: form.description,
                        lines: [
                            { account_code: form.debit, direction: "debit", amount },
                            { account_code: form.credit, direction: "credit", amount },
                        ],
                    });
                }, children: [_jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Debit account", _jsx("input", { "aria-label": "Debit account", placeholder: "FIN-SHARED-COSTS-USD", className: `w-48 ${INPUT}`, value: form.debit, onChange: (e) => setForm({ ...form, debit: e.target.value.toUpperCase() }) })] }), _jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Credit account", _jsx("input", { "aria-label": "Credit account", placeholder: "FIN-ACCRUALS-USD", className: `w-48 ${INPUT}`, value: form.credit, onChange: (e) => setForm({ ...form, credit: e.target.value.toUpperCase() }) })] }), _jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Amount (", form.currency, ")", _jsx("input", { "aria-label": "Journal amount", type: "number", min: 0.01, step: "0.01", className: `w-28 ${INPUT}`, value: form.amount, onChange: (e) => setForm({ ...form, amount: e.target.value }) })] }), _jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Description", _jsx("input", { "aria-label": "Journal description", className: `w-64 ${INPUT}`, maxLength: 300, value: form.description, onChange: (e) => setForm({ ...form, description: e.target.value }) })] }), _jsx(Button, { size: "sm", type: "submit", disabled: propose.isPending || !form.debit || !form.credit || !form.amount || !form.description, children: "Propose" }), propose.data && _jsxs("span", { role: "status", children: [propose.data.journal_number, " proposed"] }), _jsx(ErrorMessage, { error: propose.error })] })), _jsx(ErrorMessage, { error: journals.error ?? decide.error }), _jsx("table", { "aria-label": "Journals", className: "min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [journals.data?.items.map((j) => (_jsxs("tr", { className: "align-top", children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: j.journal_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [j.effective_date, " \u00B7 ", j.description, _jsx("div", { children: j.lines.map((l, i) => (_jsxs("span", { className: "mr-3", children: [l.direction === "debit" ? "Dr" : "Cr", " ", l.account_code, " ", formatExactMoney(l.amount, j.currency)] }, i))) }), j.entry_number && _jsx("div", { children: j.entry_number })] }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: formatExactMoney(j.amount, j.currency) }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: TONE[j.status], label: j.status }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: j.status === "proposed" && can("finance:approve") && (_jsxs("div", { className: "flex justify-end gap-1", children: [_jsx(Button, { size: "sm", "aria-label": `Post ${j.journal_number}`, onClick: () => decide.mutate({ id: j.id, approve: true }), children: "Post" }), _jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Reject ${j.journal_number}`, onClick: () => decide.mutate({ id: j.id, approve: false }), children: "Reject" })] })) })] }, j.id))), journals.data && journals.data.items.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No manual journals yet." }) }))] }) }), _jsx(Pager, { label: "Journal pages", offset: offset, total: journals.data?.total ?? 0, onChange: setOffset })] }));
}
/** Finance (Phase 49): month-end close, regulatory reports and cost allocation; manual journals (Phase 50). */
export function FinancePage() {
    const summary = useFinanceSummary();
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Finance", description: "The general ledger's month-end close, regulatory reporting extracts submitted to a synthetic regulator, and shared operating costs allocated to departments." }), summary.data && (_jsx("dl", { "aria-label": "Finance summary", className: "mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4", children: [
                    ["Last closed month", summary.data.last_closed_period ?? "None"],
                    ["Closes to approve", summary.data.closes_to_approve],
                    ["Reports to submit", summary.data.reports_to_submit],
                    ["Journals to approve", summary.data.journals_to_approve],
                ].map(([label, value]) => (_jsxs("div", { className: "rounded-lg border border-slate-200 bg-white p-3", children: [_jsx("dt", { className: "text-xs text-slate-500", children: label }), _jsx("dd", { className: "text-lg font-semibold text-slate-900", children: value })] }, label))) })), summary.data && (_jsxs("div", { className: "flex flex-col gap-6", children: [_jsx(ClosePanel, { nextPeriod: summary.data.next_period }), _jsx(ReportsPanel, { lastClosed: summary.data.last_closed_period }), _jsx(CostsPanel, {}), _jsx(JournalsPanel, {})] })), _jsx(ErrorMessage, { error: summary.error })] }));
}
