import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { useCommercialSummary, useCovenantTests, useDecideReview, useFacilities, useFacilityAction, useProposeFacility, useReviews, useSubmitFigures, useWaiveBreach, } from "@/services/commercial";
import { formatExactMoney, humanize, toMinorUnits } from "@/services/format";
const TONE = { proposed: "warn", active: "good", frozen: "bad", declined: "neutral", terminated: "neutral" };
const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const ratio = (centi) => `${(centi / 100).toFixed(2)}×`;
const COVENANT_LABEL = { min_dscr: "DSCR at least", max_leverage: "Leverage at most" };
function Field({ label, children }) {
    return (_jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: [label, children] }));
}
function ProposeForm() {
    const propose = useProposeFacility();
    const empty = { customer: "", account: "", type: "revolving", limit: "", term: "36", purpose: "Working capital" };
    const [form, setForm] = useState(empty);
    const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });
    const onSubmit = (event) => {
        event.preventDefault();
        // The limit is entered in major units of the account's currency.
        propose.mutate({
            customer_number: form.customer.trim(),
            account_number: form.account.trim(),
            facility_type: form.type,
            credit_limit_major: Number(form.limit),
            term_months: Number(form.term),
            purpose: form.purpose,
        }, { onSuccess: () => setForm(empty) });
    };
    return (_jsxs("form", { "aria-label": "Propose a facility", onSubmit: onSubmit, className: "mb-3 flex flex-wrap items-end gap-2 text-xs", children: [_jsx(Field, { label: "Business customer", children: _jsx("input", { "aria-label": "Business customer", required: true, className: `w-32 ${INPUT}`, value: form.customer, onChange: set("customer") }) }), _jsx(Field, { label: "Business account", children: _jsx("input", { "aria-label": "Business account", required: true, className: `w-40 ${INPUT}`, value: form.account, onChange: set("account") }) }), _jsx(Field, { label: "Type", children: _jsxs("select", { "aria-label": "Facility type", className: INPUT, value: form.type, onChange: set("type"), children: [_jsx("option", { value: "revolving", children: "Revolving credit" }), _jsx("option", { value: "term_loan", children: "Term loan" })] }) }), _jsx(Field, { label: "Limit", children: _jsx("input", { "aria-label": "Credit limit", required: true, inputMode: "decimal", className: `w-28 ${INPUT}`, value: form.limit, onChange: set("limit") }) }), _jsx(Field, { label: "Months", children: _jsx("input", { "aria-label": "Term in months", required: true, inputMode: "numeric", className: `w-16 ${INPUT}`, value: form.term, onChange: set("term") }) }), _jsx(Field, { label: "Purpose", children: _jsx("input", { "aria-label": "Purpose", className: `w-36 ${INPUT}`, value: form.purpose, onChange: set("purpose") }) }), _jsx(Button, { size: "sm", type: "submit", disabled: propose.isPending, children: "Propose" }), _jsx(ErrorMessage, { error: propose.error })] }));
}
function FacilityDetail({ facility }) {
    const { can } = useAuth();
    const action = useFacilityAction();
    const figures = useSubmitFigures();
    const waive = useWaiveBreach();
    const tests = useCovenantTests(facility.id);
    const [amount, setAmount] = useState("");
    const [period, setPeriod] = useState("");
    const [ebitda, setEbitda] = useState("");
    const [service, setService] = useState("");
    const [debt, setDebt] = useState("");
    const minor = (value) => toMinorUnits(Number(value), facility.currency);
    const move = (kind) => action.mutate({ id: facility.id, action: kind, amount: minor(amount) }, { onSuccess: () => setAmount("") });
    const onFigures = (event) => {
        event.preventDefault();
        figures.mutate({ id: facility.id, period_end: period, ebitda: minor(ebitda), debt_service: minor(service), total_debt: minor(debt) });
    };
    const live = facility.status === "active" || facility.status === "frozen";
    // A terminated facility is repaid, never drawn.
    const repayable = (live || facility.status === "terminated") && facility.drawn > 0;
    return (_jsxs("section", { "aria-label": `Facility ${facility.facility_number}`, className: "mt-4 rounded-lg border border-slate-200 p-3 text-xs", children: [_jsxs("h3", { className: "mb-2 text-sm font-semibold text-slate-900", children: [facility.facility_number, " \u00B7 ", facility.customer_name] }), _jsxs("p", { className: "mb-2 text-slate-600", children: [facility.covenants.map((c) => `${COVENANT_LABEL[c.kind]} ${ratio(c.threshold_centi)}`).join(" · "), facility.matures_on && ` · matures ${facility.matures_on}`, facility.draw_block && facility.status !== "proposed" && _jsxs("span", { className: "text-rose-700", children: [" \u00B7 cannot draw: ", facility.draw_block] })] }), _jsx(ErrorMessage, { error: action.error ?? figures.error ?? waive.error ?? tests.error }), (live || repayable) && can("accounts:transact") && (_jsxs("div", { className: "flex flex-wrap items-end gap-4", children: [_jsxs("form", { "aria-label": "Draw or repay", onSubmit: (e) => e.preventDefault(), className: "flex items-end gap-2", children: [_jsx(Field, { label: `Amount (${facility.currency})`, children: _jsx("input", { "aria-label": "Amount", inputMode: "decimal", className: `w-28 ${INPUT}`, value: amount, onChange: (e) => setAmount(e.target.value) }) }), live && (_jsx(Button, { size: "sm", type: "button", disabled: !amount || action.isPending, onClick: () => move("draw"), children: "Draw" })), repayable && (_jsx(Button, { size: "sm", type: "button", variant: "secondary", disabled: !amount || action.isPending, onClick: () => move("repay"), children: "Repay" }))] }), live && (_jsxs("form", { "aria-label": "Covenant figures", onSubmit: onFigures, className: "flex flex-wrap items-end gap-2", children: [_jsx(Field, { label: "Year to", children: _jsx("input", { "aria-label": "Period end", type: "date", required: true, className: INPUT, value: period, onChange: (e) => setPeriod(e.target.value) }) }), _jsx(Field, { label: "EBITDA", children: _jsx("input", { "aria-label": "EBITDA", required: true, inputMode: "decimal", className: `w-24 ${INPUT}`, value: ebitda, onChange: (e) => setEbitda(e.target.value) }) }), _jsx(Field, { label: "Debt service", children: _jsx("input", { "aria-label": "Debt service", required: true, inputMode: "decimal", className: `w-24 ${INPUT}`, value: service, onChange: (e) => setService(e.target.value) }) }), _jsx(Field, { label: "Total debt", children: _jsx("input", { "aria-label": "Total debt", required: true, inputMode: "decimal", className: `w-24 ${INPUT}`, value: debt, onChange: (e) => setDebt(e.target.value) }) }), _jsx(Button, { size: "sm", type: "submit", disabled: figures.isPending, children: "Test covenants" })] })), live && (_jsx(Button, { size: "sm", variant: "secondary", onClick: () => action.mutate({ id: facility.id, action: "reviews" }), children: "Open review" }))] })), _jsx("table", { "aria-label": "Covenant tests", className: "mt-3 min-w-full", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: tests.data?.map((t) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1", children: t.period_end }), _jsx("td", { className: "px-2 py-1 text-slate-600", children: t.results.map((r) => `${humanize(r.kind)} ${ratio(r.actual_centi)} (${r.passed ? "met" : "breached"})`).join(" · ") }), _jsx("td", { className: "px-2 py-1", children: _jsx(StatusPill, { compact: true, tone: !t.breached ? "good" : t.waived ? "neutral" : "bad", label: !t.breached ? "met" : t.waived ? "waived" : "breached" }) }), _jsx("td", { className: "px-2 py-1 text-right", children: t.breached && !t.waived && can("loans:approve_large") && (_jsx(Button, { size: "sm", "aria-label": `Waive ${t.period_end}`, onClick: () => waive.mutate(t.id), children: "Waive" })) })] }, t.id))) }) })] }));
}
function FacilitiesPanel() {
    const { can } = useAuth();
    const facilities = useFacilities();
    const action = useFacilityAction();
    const [selected, setSelected] = useState(null);
    const items = facilities.data?.items ?? [];
    const chosen = items.find((f) => f.id === selected);
    return (_jsxs(Panel, { title: "Facilities", subtitle: "A credit approver other than the proposer approves; above US$1m the credit committee too. A covenant breach freezes the facility until the committee waives it; an overdue annual review stops drawdowns.", children: [can("accounts:transact") && _jsx(ProposeForm, {}), _jsx(ErrorMessage, { error: facilities.error ?? action.error }), _jsx("table", { "aria-label": "Facilities", className: "min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [items.map((f) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5", children: _jsx("button", { type: "button", "aria-label": `Select ${f.facility_number}`, className: "font-mono text-xs text-sky-700 underline", onClick: () => setSelected(f.id), children: f.facility_number }) }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [f.customer_name, " \u00B7 ", humanize(f.facility_type), " \u00B7 ", (f.annual_rate_bps / 100).toFixed(2), " % \u00B7 ", f.term_months, " months", f.review_due_on && ` · review ${f.review_due_on}`] }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: formatExactMoney(f.credit_limit, f.currency) }), _jsxs("td", { className: "px-2 py-1.5 text-right text-xs tabular-nums text-slate-600", children: ["drawn ", formatExactMoney(f.drawn, f.currency), " \u00B7 available ", formatExactMoney(f.available, f.currency)] }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: TONE[f.status], label: f.status === "proposed" && f.approved ? "awaiting committee" : f.status }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: f.status === "proposed" && (_jsxs("div", { className: "flex justify-end gap-1", children: [!f.approved && can("loans:approve") && (_jsx(Button, { size: "sm", "aria-label": `Approve ${f.facility_number}`, onClick: () => action.mutate({ id: f.id, action: "approve" }), children: "Approve" })), f.approved && f.needs_committee && !f.committee_approved && can("loans:approve_large") && (_jsx(Button, { size: "sm", "aria-label": `Committee approve ${f.facility_number}`, onClick: () => action.mutate({ id: f.id, action: "committee" }), children: "Committee approve" })), can("loans:approve") && (_jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Decline ${f.facility_number}`, onClick: () => action.mutate({ id: f.id, action: "decline" }), children: "Decline" }))] })) })] }, f.id))), facilities.data && items.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No facilities yet." }) }))] }) }), chosen && _jsx(FacilityDetail, { facility: chosen })] }));
}
function ReviewsPanel() {
    const { can } = useAuth();
    const reviews = useReviews();
    const facilities = useFacilities();
    const decide = useDecideReview();
    const numbers = new Map((facilities.data?.items ?? []).map((f) => [f.id, f.facility_number]));
    return (_jsxs(Panel, { title: "Annual reviews", subtitle: "Opened from 60 days before a facility's review is due. A credit approver other than the person who opened it renews the facility for a year or terminates it.", children: [_jsx(ErrorMessage, { error: reviews.error ?? decide.error }), _jsx("table", { "aria-label": "Reviews", className: "min-w-full text-sm", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: reviews.data?.map((r) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: r.review_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [numbers.get(r.facility_id) ?? "facility", " \u00B7 due ", r.due_on] }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: r.outcome === "renewed" ? "good" : r.outcome ? "neutral" : "warn", label: r.outcome ?? "open" }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: !r.outcome && can("loans:approve") && (_jsxs("div", { className: "flex justify-end gap-1", children: [_jsx(Button, { size: "sm", "aria-label": `Renew ${r.review_number}`, onClick: () => decide.mutate({ id: r.id, renew: true }), children: "Renew" }), _jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Terminate ${r.review_number}`, onClick: () => decide.mutate({ id: r.id, renew: false }), children: "Terminate" })] })) })] }, r.id))) }) })] }));
}
/** Commercial lending (Phase 35): facilities, drawdowns, covenants and annual reviews. */
export function CommercialPage() {
    const summary = useCommercialSummary();
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Commercial Lending", description: "Term loans and revolving credit for business customers: approval with four-eyes and, above US$1m, the credit committee; drawdowns and repayments through the ledger; covenant tests that freeze a facility on a breach; annual reviews." }), summary.data && (_jsx("dl", { "aria-label": "Commercial summary", className: "mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5", children: [
                    ["Proposed", summary.data.proposed],
                    ["Active", summary.data.active],
                    ["Frozen", summary.data.frozen],
                    ["Reviews due", summary.data.reviews_due],
                    ["Open reviews", summary.data.open_reviews],
                ].map(([label, value]) => (_jsxs("div", { className: "rounded-lg border border-slate-200 bg-white p-3", children: [_jsx("dt", { className: "text-xs text-slate-500", children: label }), _jsx("dd", { className: "text-lg font-semibold text-slate-900", children: value })] }, label))) })), _jsxs("div", { className: "space-y-6", children: [_jsx(FacilitiesPanel, {}), _jsx(ReviewsPanel, {})] })] }));
}
