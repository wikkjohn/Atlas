import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { CalendarClock } from "lucide-react";
import { useState } from "react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Panel } from "@/components/Panel";
import { formatTimestamp } from "@/features/dashboard/format";
import { useRunServicing, useServicingRuns } from "@/services/banking";
import { formatExactMoney } from "@/services/format";
const BUCKETS = ["current", "1-29", "30-59", "60-89", "90+"];
function isoDate(date) {
    return date.toISOString().slice(0, 10);
}
/** The next date to service to: a month after the business date, or today. */
export function suggestedDate(businessDate, today = new Date()) {
    if (!businessDate)
        return isoDate(today);
    const next = new Date(`${businessDate}T00:00:00Z`);
    next.setUTCMonth(next.getUTCMonth() + 1);
    return isoDate(next);
}
function arrearsTotal(run) {
    const parts = Object.entries(run.summary.arrears_amount).map(([currency, amount]) => formatExactMoney(amount, currency));
    return parts.length ? parts.join(" · ") : "—";
}
export function ServicingPanel() {
    const { can } = useAuth();
    const runs = useServicingRuns({ limit: 5 });
    const latest = runs.data?.items[0] ?? null;
    const businessDate = latest?.as_of ?? null;
    const [asOf, setAsOf] = useState(null);
    const start = useRunServicing();
    const target = asOf ?? suggestedDate(businessDate);
    const submit = (event) => {
        event.preventDefault();
        start.mutate(target, { onSuccess: () => setAsOf(null) });
    };
    return (_jsx(Panel, { title: "Loan servicing", subtitle: "A servicing run accrues interest and collects every instalment due up to its business date, oldest first, from the borrower's account. Instalments it cannot collect stay due: the loan is in arrears. At 30 days past due WF-0004 opens a collections case.", children: _jsxs("div", { className: "grid gap-5 lg:grid-cols-[minmax(0,18rem)_1fr]", children: [_jsxs("div", { className: "space-y-3", children: [_jsxs("div", { children: [_jsx("div", { className: "text-xs font-medium tracking-wide text-slate-500 uppercase", children: "Business date" }), _jsxs("div", { className: "mt-0.5 flex items-center gap-2 text-lg font-semibold text-slate-900", "data-testid": "business-date", children: [_jsx(CalendarClock, { "aria-hidden": true, className: "h-4 w-4 text-slate-400" }), runs.isPending ? "…" : (businessDate ?? "Not serviced yet")] })] }), can("loans:service") && (_jsxs("form", { onSubmit: submit, className: "flex flex-wrap items-end gap-2", children: [_jsxs("label", { className: "text-xs font-medium text-slate-700", children: ["Service to", _jsx("input", { type: "date", "aria-label": "Service to", required: true, min: businessDate ?? undefined, value: target, onChange: (e) => setAsOf(e.target.value), className: "mt-1 block rounded-lg border border-slate-200 px-2 py-1 text-sm" })] }), _jsx(Button, { type: "submit", size: "sm", disabled: start.isPending, children: start.isPending ? "Servicing…" : "Run servicing" })] })), _jsx(ErrorMessage, { error: start.error ?? runs.error })] }), _jsx("div", { className: "overflow-x-auto", children: _jsxs("table", { "aria-label": "Servicing runs", className: "min-w-full text-sm", children: [_jsx("thead", { className: "text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-2 py-1", children: "Run" }), _jsx("th", { className: "px-2 py-1", children: "As of" }), _jsx("th", { className: "px-2 py-1 text-right", children: "Loans" }), _jsx("th", { className: "px-2 py-1 text-right", children: "Collected" }), _jsx("th", { className: "px-2 py-1 text-right", children: "Missed" }), _jsx("th", { className: "px-2 py-1 text-right", children: "Repaid" }), _jsx("th", { className: "px-2 py-1", children: "Arrears" }), _jsx("th", { className: "px-2 py-1", children: "Buckets" })] }) }), _jsxs("tbody", { className: "divide-y divide-slate-100", children: [runs.data?.items.map((run) => (_jsxs("tr", { children: [_jsxs("td", { className: "px-2 py-1.5", children: [_jsxs("div", { className: "font-mono text-xs", children: ["#", run.run_number] }), _jsxs("div", { className: "text-[11px] text-slate-400", children: [run.started_by_username, " \u00B7 ", formatTimestamp(run.created_at)] })] }), _jsx("td", { className: "px-2 py-1.5 tabular-nums", children: run.as_of }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: run.summary.loans }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: run.summary.collected }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: run.summary.missed }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: run.summary.repaid }), _jsx("td", { className: "px-2 py-1.5 tabular-nums", children: arrearsTotal(run) }), _jsx("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: BUCKETS.filter((b) => run.summary.buckets[b])
                                                    .map((b) => `${b}: ${run.summary.buckets[b]}`)
                                                    .join(" · ") || "—" })] }, run.id))), runs.data?.items.length === 0 && (_jsx("tr", { children: _jsx("td", { colSpan: 8, className: "px-2 py-4 text-center text-xs text-slate-500", children: "No servicing runs yet: no instalment has been accrued or collected." }) }))] })] }) })] }) }));
}
