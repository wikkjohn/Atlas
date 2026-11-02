import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { COMPLIANCE_PAGE, useAlertAction, useAlerts, useCaseAction, useCases, useCompleteReview, useComplianceSummary, useFileSar, useReviews, useRunMonitoring, useRuns, useSars, useScheduleReviews, } from "@/services/compliance";
import { formatExactMoney, humanize } from "@/services/format";
import { RULE_LABELS } from "@/types/compliance";
const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const ALERT_TONE = { open: "warn", in_case: "warn", dismissed: "neutral", closed: "neutral", escalated: "bad" };
const CASE_TONE = { investigating: "warn", sar_drafted: "warn", sar_filed: "bad", closed: "neutral" };
/** Newer/older paging for a list, `COMPLIANCE_PAGE` rows at a time. */
function Pager({ label, offset, total, onChange }) {
    if (total <= COMPLIANCE_PAGE)
        return null;
    return (_jsxs("nav", { "aria-label": label, className: "mt-2 flex items-center justify-end gap-2 text-xs text-slate-600", children: [_jsxs("span", { children: [offset + 1, "\u2013", Math.min(offset + COMPLIANCE_PAGE, total), " of ", total] }), _jsx(Button, { size: "sm", variant: "secondary", disabled: offset === 0, onClick: () => onChange(Math.max(offset - COMPLIANCE_PAGE, 0)), children: "Newer" }), _jsx(Button, { size: "sm", variant: "secondary", disabled: offset + COMPLIANCE_PAGE >= total, onClick: () => onChange(offset + COMPLIANCE_PAGE), children: "Older" })] }));
}
function MonitoringPanel() {
    const { can } = useAuth();
    const runs = useRuns();
    const run = useRunMonitoring();
    const [days, setDays] = useState("30");
    const [offset, setOffset] = useState(0);
    const [account, setAccount] = useState("");
    const alerts = useAlerts(offset, account.trim().toUpperCase());
    const action = useAlertAction();
    const items = alerts.data?.items ?? [];
    return (_jsxs(Panel, { title: "Transaction monitoring", subtitle: "Each run reads customer accounts' ledger activity over a window. Rules: a cash deposit at or above the reporting threshold (US$10,000 equivalent), three or more just under it within ten days, money passed straight through, and high turnover by a high-risk customer.", children: [can("compliance:monitor") && (_jsxs("form", { "aria-label": "Run monitoring", className: "mb-3 flex flex-wrap items-end gap-2 text-xs", onSubmit: (e) => {
                    e.preventDefault();
                    run.mutate(Number(days));
                }, children: [_jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Window (days)", _jsx("input", { "aria-label": "Window days", type: "number", min: 1, max: 366, className: `w-20 ${INPUT}`, value: days, onChange: (e) => setDays(e.target.value) })] }), _jsx(Button, { size: "sm", type: "submit", disabled: run.isPending, children: "Run monitoring" }), _jsx(ErrorMessage, { error: run.error })] })), runs.data && runs.data.items.length > 0 && (_jsxs("p", { className: "mb-2 text-xs text-slate-600", "aria-label": "Latest run", children: [runs.data.items[0].run_number, ": ", runs.data.items[0].window_start, " to ", runs.data.items[0].window_end, ", ", runs.data.items[0].accounts_scanned, " accounts, ", runs.data.items[0].alerts_raised, " alerts"] })), _jsxs("label", { className: "mb-2 flex items-center gap-2 text-xs text-slate-600", children: ["Account", _jsx("input", { "aria-label": "Alerts for account", placeholder: "All accounts", className: `w-44 ${INPUT}`, value: account, onChange: (e) => {
                            setAccount(e.target.value);
                            setOffset(0);
                        } })] }), _jsx(ErrorMessage, { error: alerts.error ?? action.error }), _jsx("table", { "aria-label": "Alerts", className: "min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [items.map((a) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: a.alert_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [RULE_LABELS[a.rule], " (score ", a.score, ") \u00B7 ", a.customer_name, " (", a.customer_number, ") \u00B7 ", a.account_number, a.case_number && ` · ${a.case_number}`, a.note && ` · ${a.note}`] }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: formatExactMoney(a.amount, a.currency) }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: ALERT_TONE[a.status], label: humanize(a.status) }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: a.status === "open" && can("compliance:monitor") && (_jsxs("div", { className: "flex justify-end gap-1", children: [_jsx(Button, { size: "sm", "aria-label": `Investigate ${a.alert_number}`, onClick: () => action.mutate({ id: a.id, action: "investigate" }), children: "Investigate" }), _jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Dismiss ${a.alert_number}`, onClick: () => action.mutate({ id: a.id, action: "dismiss" }), children: "Dismiss" })] })) })] }, a.id))), alerts.data && items.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No alerts." }) }))] }) }), _jsx(Pager, { label: "Alert pages", offset: offset, total: alerts.data?.total ?? 0, onChange: setOffset })] }));
}
function CasesPanel() {
    const { can } = useAuth();
    const [offset, setOffset] = useState(0);
    const cases = useCases(offset);
    const action = useCaseAction();
    const [sarOffset, setSarOffset] = useState(0);
    const sars = useSars(sarOffset);
    const file = useFileSar();
    return (_jsxs(Panel, { title: "Cases and reports", subtitle: "A case takes in all of a customer's open alerts. Closing it with no action needs a second compliance officer; escalating drafts a suspicious activity report, filed with the (synthetic) FIU by someone other than its preparer.", children: [_jsx(ErrorMessage, { error: cases.error ?? action.error }), _jsx("table", { "aria-label": "Cases", className: "min-w-full text-sm", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: cases.data?.items.map((c) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: c.case_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [c.customer_name, " (", c.customer_number, ") \u00B7 ", c.alerts.join(", "), c.sar_number && ` · ${c.sar_number}`, c.note && ` · ${c.note}`] }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: CASE_TONE[c.status], label: humanize(c.status) }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: c.status === "investigating" && can("compliance:monitor") && (_jsxs("div", { className: "flex justify-end gap-1", children: [_jsx(Button, { size: "sm", "aria-label": `Escalate ${c.case_number}`, onClick: () => action.mutate({ id: c.id, action: "sar" }), children: "Draft report" }), _jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Close ${c.case_number}`, onClick: () => action.mutate({ id: c.id, action: "close" }), children: "Close, no action" })] })) })] }, c.id))) }) }), _jsx(Pager, { label: "Case pages", offset: offset, total: cases.data?.total ?? 0, onChange: setOffset }), _jsx(ErrorMessage, { error: sars.error ?? file.error }), _jsx("table", { "aria-label": "Suspicious activity reports", className: "mt-4 min-w-full text-sm", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: sars.data?.items.map((s) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: s.sar_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [s.case_number, " \u00B7 ", s.narrative, s.filing_reference && ` · ${s.filing_reference}`] }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: s.status === "filed" ? "bad" : "warn", label: s.status }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: s.status === "draft" && can("compliance:file") && (_jsx(Button, { size: "sm", "aria-label": `File ${s.sar_number}`, onClick: () => file.mutate(s.id), children: "File" })) })] }, s.id))) }) }), _jsx(Pager, { label: "Report pages", offset: sarOffset, total: sars.data?.total ?? 0, onChange: setSarOffset })] }));
}
function ReviewsPanel() {
    const { can } = useAuth();
    const [offset, setOffset] = useState(0);
    const reviews = useReviews(offset);
    const schedule = useScheduleReviews();
    const complete = useCompleteReview();
    const [ratings, setRatings] = useState({});
    return (_jsxs(Panel, { title: "Periodic KYC reviews", subtitle: "Due every year for high-risk customers, two years for medium and three for low, from the last review (or when they joined). Completing a review confirms, raises or lowers the risk rating.", children: [can("compliance:monitor") && (_jsxs("div", { className: "mb-3 flex items-center gap-2 text-xs", children: [_jsx(Button, { size: "sm", onClick: () => schedule.mutate(30), disabled: schedule.isPending, children: "Open reviews due in 30 days" }), schedule.data && _jsxs("span", { role: "status", children: [schedule.data.opened, " opened"] }), _jsx(ErrorMessage, { error: schedule.error })] })), _jsx(ErrorMessage, { error: reviews.error ?? complete.error }), _jsx("table", { "aria-label": "KYC reviews", className: "min-w-full text-sm", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: reviews.data?.items.map((r) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: r.review_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [r.customer_name, " (", r.customer_number, ") \u00B7 due ", r.due_on, " \u00B7 rated ", r.risk_before, r.outcome && ` · ${r.outcome}${r.risk_after ? ` to ${r.risk_after}` : ""}`] }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: r.status === "due" ? "warn" : "good", label: r.status }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: r.status === "due" && can("compliance:monitor") && (_jsxs("div", { className: "flex justify-end gap-1", children: [_jsx("select", { "aria-label": `Rating for ${r.review_number}`, className: `text-xs ${INPUT}`, value: ratings[r.id] ?? r.risk_before, onChange: (e) => setRatings({ ...ratings, [r.id]: e.target.value }), children: ["low", "medium", "high"].map((v) => (_jsx("option", { value: v, children: v }, v))) }), _jsx(Button, { size: "sm", "aria-label": `Complete ${r.review_number}`, onClick: () => complete.mutate({ id: r.id, risk_rating: ratings[r.id] ?? r.risk_before }), children: "Complete" })] })) })] }, r.id))) }) }), _jsx(Pager, { label: "Review pages", offset: offset, total: reviews.data?.total ?? 0, onChange: setOffset })] }));
}
/** Compliance (Phase 45): AML monitoring, alerts, cases, reports and periodic KYC reviews. */
export function CompliancePage() {
    const summary = useComplianceSummary();
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Compliance", description: "Anti-money-laundering transaction monitoring, alert investigation, suspicious activity reports filed with a synthetic financial intelligence unit, and periodic KYC reviews." }), summary.data && (_jsx("dl", { "aria-label": "Compliance summary", className: "mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5", children: [
                    ["Open alerts", summary.data.open_alerts],
                    ["Open cases", summary.data.open_cases],
                    ["Reports to file", summary.data.draft_sars],
                    ["Reviews due", summary.data.reviews_due],
                    ["Reviews overdue", summary.data.reviews_overdue],
                ].map(([label, value]) => (_jsxs("div", { className: "rounded-lg border border-slate-200 bg-white p-3", children: [_jsx("dt", { className: "text-xs text-slate-500", children: label }), _jsx("dd", { className: "text-lg font-semibold text-slate-900", children: value })] }, label))) })), _jsxs("div", { className: "flex flex-col gap-6", children: [_jsx(MonitoringPanel, {}), _jsx(CasesPanel, {}), _jsx(ReviewsPanel, {})] })] }));
}
