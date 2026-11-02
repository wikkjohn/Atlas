import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Modal } from "@/components/Modal";
import { StatusPill } from "@/components/StatusPill";
import { formatTimestamp } from "@/features/dashboard/format";
import { useLoan, useLoanSchedule, usePayOffLoan, usePayoffQuote, useRepayArrears } from "@/services/banking";
import { formatExactMoney, humanize } from "@/services/format";
import { useExecutions } from "@/services/workflows";
export const LOAN_TONE = { active: "neutral", repaid: "good", written_off: "bad" };
export const BUCKET_TONE = {
    current: "good",
    "1-29": "warn",
    "30-59": "warn",
    "60-89": "bad",
    "90+": "bad",
};
const INSTALMENT_TONE = {
    scheduled: "neutral",
    due: "bad",
    paid: "good",
    prepaid: "good",
    written_off: "bad",
};
function Fact({ label, children }) {
    return (_jsxs("div", { children: [_jsx("dt", { className: "text-xs text-slate-500", children: label }), _jsx("dd", { className: "mt-0.5 text-sm text-slate-900 tabular-nums", children: children })] }));
}
function Actions({ loan }) {
    const [confirmPayoff, setConfirmPayoff] = useState(false);
    const repay = useRepayArrears();
    const payoff = usePayOffLoan();
    const quote = usePayoffQuote(loan.id, confirmPayoff);
    const money = (amount) => formatExactMoney(amount, loan.currency);
    return (_jsxs("div", { className: "space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3", children: [_jsxs("div", { className: "flex flex-wrap items-center gap-2", children: [loan.arrears_amount > 0 && (_jsxs(Button, { size: "sm", disabled: repay.isPending, onClick: () => repay.mutate({ id: loan.id, body: {} }), children: ["Repay arrears (", money(loan.arrears_amount), ")"] })), !confirmPayoff && (_jsx(Button, { size: "sm", variant: "secondary", onClick: () => setConfirmPayoff(true), children: "Pay off early\u2026" }))] }), confirmPayoff && (_jsxs("div", { className: "space-y-2 text-sm", "aria-label": "Payoff quote", children: [quote.data && (_jsxs("p", { className: "text-slate-700", children: ["Outstanding principal ", money(quote.data.principal), " plus accrued interest", " ", money(quote.data.accrued_interest), ": ", _jsx("strong", { children: money(quote.data.total) }), " from", " ", loan.disbursement_account_number, ", booked ", quote.data.as_of, "."] })), _jsxs("div", { className: "flex gap-2", children: [_jsx(Button, { size: "sm", variant: "danger", disabled: !quote.data || payoff.isPending, onClick: () => payoff.mutate({ id: loan.id, body: {} }, { onSuccess: () => setConfirmPayoff(false) }), children: "Confirm payoff" }), _jsx(Button, { size: "sm", variant: "ghost", onClick: () => setConfirmPayoff(false), children: "Cancel" })] }), _jsx(ErrorMessage, { error: quote.error })] })), _jsx(ErrorMessage, { error: repay.error ?? payoff.error })] }));
}
/** The loan's WF-0004 collections cases (the case's business key is the loan id). */
function CollectionsCases({ loanId }) {
    const cases = useExecutions({ workflow_id: "WF-0004", business_key: loanId, limit: 5 });
    if (!cases.data?.items.length)
        return null;
    return (_jsxs("div", { "aria-label": "Collections cases", className: "text-sm", children: [_jsx("div", { className: "text-xs font-medium tracking-wide text-slate-500 uppercase", children: "Collections cases (WF-0004)" }), _jsx("ul", { className: "mt-1 space-y-1", children: cases.data.items.map((c) => (_jsxs("li", { className: "flex items-center gap-2", children: [_jsxs(Link, { className: "text-navy-700 underline", to: `/workflows?tab=executions&execution=${c.id}`, children: ["Opened ", formatTimestamp(c.started_at)] }), _jsx("span", { className: "text-slate-600", children: c.outcome ? humanize(c.outcome) : humanize(c.current_steps[0] ?? c.status) })] }, c.id))) })] }));
}
export function LoanDetail({ loanId, onClose }) {
    const { can } = useAuth();
    const loan = useLoan(loanId);
    const schedule = useLoanSchedule(loanId);
    const l = loan.data;
    const money = (amount) => (l ? formatExactMoney(amount, l.currency) : "");
    return (_jsxs(Modal, { title: l ? `Loan ${l.loan_number}` : "Loan", onClose: onClose, wide: true, children: [_jsx(ErrorMessage, { error: loan.error ?? schedule.error }), l && (_jsxs("div", { className: "space-y-4", children: [_jsxs("div", { className: "flex flex-wrap items-center gap-2", children: [_jsx(StatusPill, { tone: LOAN_TONE[l.status], label: humanize(l.status) }), l.status === "active" && (_jsx(StatusPill, { tone: BUCKET_TONE[l.arrears_bucket], label: l.days_past_due ? `${l.days_past_due} days past due` : "Up to date" })), _jsxs("span", { className: "text-sm text-slate-600", children: [l.customer_name, " \u00B7 ", l.disbursement_account_number] })] }), _jsxs("dl", { className: "grid grid-cols-2 gap-3 sm:grid-cols-4", children: [_jsx(Fact, { label: "Principal", children: money(l.principal) }), _jsx(Fact, { label: "Outstanding", children: money(l.outstanding) }), _jsxs(Fact, { label: "Instalments paid", children: [l.instalments_paid, " of ", l.instalments_total] }), _jsx(Fact, { label: "Monthly", children: money(l.monthly_payment) }), _jsx(Fact, { label: "Next due", children: l.next_due_date ? `${l.next_due_date} · ${money(l.next_due_amount ?? 0)}` : "—" }), _jsx(Fact, { label: "In arrears", children: l.arrears_amount ? money(l.arrears_amount) : "—" }), _jsx(Fact, { label: "Closed", children: l.closed_on ?? "—" }), l.written_off_by_username && _jsx(Fact, { label: "Written off by", children: l.written_off_by_username })] }), l.status === "active" && can("loans:repay") && _jsx(Actions, { loan: l }), can("workflows:read") && _jsx(CollectionsCases, { loanId: l.id }), _jsx("div", { className: "max-h-80 overflow-y-auto rounded-lg border border-slate-200", children: _jsxs("table", { "aria-label": "Repayment schedule", className: "min-w-full text-sm", children: [_jsx("thead", { className: "sticky top-0 bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-3 py-1.5", children: "#" }), _jsx("th", { className: "px-3 py-1.5", children: "Due" }), _jsx("th", { className: "px-3 py-1.5 text-right", children: "Principal" }), _jsx("th", { className: "px-3 py-1.5 text-right", children: "Interest" }), _jsx("th", { className: "px-3 py-1.5 text-right", children: "Instalment" }), _jsx("th", { className: "px-3 py-1.5", children: "Status" })] }) }), _jsx("tbody", { className: "divide-y divide-slate-100", children: schedule.data?.map((i) => (_jsxs("tr", { children: [_jsx("td", { className: "px-3 py-1.5 tabular-nums", children: i.number }), _jsx("td", { className: "px-3 py-1.5 tabular-nums", children: i.due_date }), _jsx("td", { className: "px-3 py-1.5 text-right tabular-nums", children: money(i.principal) }), _jsx("td", { className: "px-3 py-1.5 text-right tabular-nums", children: money(i.interest) }), _jsx("td", { className: "px-3 py-1.5 text-right tabular-nums", children: money(i.amount) }), _jsxs("td", { className: "px-3 py-1.5", children: [_jsx(StatusPill, { compact: true, tone: INSTALMENT_TONE[i.status], label: humanize(i.status) }), i.paid_on && _jsx("span", { className: "ml-2 text-[11px] text-slate-400", children: i.paid_on })] })] }, i.number))) })] }) })] }))] }));
}
