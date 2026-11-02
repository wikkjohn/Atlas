import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { RISK_PAGE, useBreaches, useCalculate, useDecideRating, useDecideRun, useObligor, useProvisionLines, useProvisionRuns, useRate, useRatings, useRiskSummary, useSetLimit, } from "@/services/risk";
import { formatExactMoney } from "@/services/format";
import { bps } from "@/types/risk";
const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const RATING_TONE = { pending: "warn", approved: "good", rejected: "neutral" };
const RUN_TONE = { calculated: "warn", posted: "good", rejected: "neutral" };
const usd = (dollars) => formatExactMoney(dollars * 100, "USD");
/** Newer/older paging, `RISK_PAGE` rows at a time. */
function Pager({ label, offset, total, onChange }) {
    if (total <= RISK_PAGE)
        return null;
    return (_jsxs("nav", { "aria-label": label, className: "mt-2 flex items-center justify-end gap-2 text-xs text-slate-600", children: [_jsxs("span", { children: [offset + 1, "\u2013", Math.min(offset + RISK_PAGE, total), " of ", total] }), _jsx(Button, { size: "sm", variant: "secondary", disabled: offset === 0, onClick: () => onChange(Math.max(offset - RISK_PAGE, 0)), children: "Newer" }), _jsx(Button, { size: "sm", variant: "secondary", disabled: offset + RISK_PAGE >= total, onClick: () => onChange(offset + RISK_PAGE), children: "Older" })] }));
}
function ObligorActions({ obligor }) {
    const { can } = useAuth();
    const rate = useRate();
    const limit = useSetLimit();
    const [grade, setGrade] = useState("model");
    const [rationale, setRationale] = useState("");
    const [limitUsd, setLimitUsd] = useState(String(obligor.limit_usd));
    return (_jsxs("div", { className: "mt-3 flex flex-col gap-3 text-xs", children: [can("risk:rate") && (_jsxs("form", { "aria-label": "Rate obligor", className: "flex flex-wrap items-end gap-2", onSubmit: (e) => {
                    e.preventDefault();
                    rate.mutate({ customer_number: obligor.customer_number, grade: grade === "model" ? null : Number(grade), rationale });
                }, children: [_jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Grade", _jsxs("select", { "aria-label": "Grade", className: INPUT, value: grade, onChange: (e) => setGrade(e.target.value), children: [_jsx("option", { value: "model", children: "The model's" }), Array.from({ length: 10 }, (_, i) => i + 1).map((g) => (_jsx("option", { value: g, children: g }, g)))] })] }), _jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Rationale (needed to depart from the model)", _jsx("input", { "aria-label": "Rationale", className: `w-72 ${INPUT}`, maxLength: 300, value: rationale, onChange: (e) => setRationale(e.target.value) })] }), _jsx(Button, { size: "sm", type: "submit", disabled: rate.isPending, children: "Rate" }), rate.data && (_jsxs("span", { role: "status", children: [rate.data.rating_number, ": grade ", rate.data.grade, ", ", rate.data.status] })), _jsx(ErrorMessage, { error: rate.error })] })), can("risk:approve") && (_jsxs("form", { "aria-label": "Set limit", className: "flex flex-wrap items-end gap-2", onSubmit: (e) => {
                    e.preventDefault();
                    limit.mutate({ customer_number: obligor.customer_number, limit_usd: Number(limitUsd), note: "Set on the risk page" });
                }, children: [_jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Limit (US$)", _jsx("input", { "aria-label": "Limit in US dollars", type: "number", min: 0, className: `w-36 ${INPUT}`, value: limitUsd, onChange: (e) => setLimitUsd(e.target.value) })] }), _jsx(Button, { size: "sm", type: "submit", disabled: limit.isPending, children: "Set limit" }), _jsx(ErrorMessage, { error: limit.error })] }))] }));
}
function ObligorPanel() {
    const [input, setInput] = useState("");
    const [number, setNumber] = useState("");
    const obligor = useObligor(number);
    const breaches = useBreaches();
    const view = obligor.data;
    return (_jsxs(Panel, { title: "Obligors", subtitle: "Each customer has an internal grade from 1 (strongest) to 10 (in default), each with a one-year probability of default. The model starts from the KYC rating and worsens it for arrears and frozen facilities; a grade departing from it needs a second person's approval. Exposure (loans, mortgages, drawn facilities plus half the undrawn headroom, overdrafts) is measured in US dollars against the obligor's limit.", children: [_jsxs("form", { "aria-label": "Look up obligor", className: "mb-3 flex items-end gap-2 text-xs", onSubmit: (e) => {
                    e.preventDefault();
                    setNumber(input.trim().toUpperCase());
                }, children: [_jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Customer number", _jsx("input", { "aria-label": "Customer number", placeholder: "CUS-0000001", className: `w-40 ${INPUT}`, value: input, onChange: (e) => setInput(e.target.value) })] }), _jsx(Button, { size: "sm", type: "submit", children: "Look up" })] }), _jsx(ErrorMessage, { error: obligor.error }), view && (_jsxs("section", { "aria-label": "Obligor", className: "mb-4 rounded-md border border-slate-200 p-3 text-sm", children: [_jsxs("p", { className: "font-medium text-slate-900", children: [view.name, " (", view.customer_number, ")"] }), _jsxs("p", { className: "text-xs text-slate-600", "aria-label": "Obligor grade", children: ["Grade ", view.grade, " (PD ", bps(view.pd_bps), ") \u00B7 limit ", usd(view.limit_usd), " (", view.limit_source === "set" ? "set" : "by grade", ") \u00B7 exposure ", usd(view.exposure_usd), view.excess_usd > 0 && ` · ${usd(view.excess_usd)} over the limit`] }), _jsx("table", { "aria-label": "Exposures", className: "mt-2 min-w-full text-xs", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [view.exposures.map((e) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1 font-mono", children: e.reference }), _jsxs("td", { className: "px-2 py-1 text-slate-600", children: [e.type, e.days_past_due > 0 && ` · ${e.days_past_due} days past due`] }), _jsx("td", { className: "px-2 py-1 text-right tabular-nums", children: formatExactMoney(e.ead, e.currency) })] }, `${e.type}-${e.reference}`))), view.exposures.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-2 text-center text-slate-500", children: "No credit exposure." }) }))] }) }), _jsx(ObligorActions, { obligor: view }, view.customer_number)] })), _jsx("h3", { className: "mb-1 text-xs font-semibold text-slate-700", children: "Limit breaches" }), _jsx(ErrorMessage, { error: breaches.error }), _jsx("table", { "aria-label": "Limit breaches", className: "min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [breaches.data?.map((b) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: b.customer_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [b.name, " \u00B7 grade ", b.grade, " \u00B7 limit ", usd(b.limit_usd)] }), _jsxs("td", { className: "px-2 py-1.5 text-right text-xs tabular-nums", children: [usd(b.excess_usd), " over"] })] }, b.customer_number))), breaches.data && breaches.data.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No obligor is over their limit." }) }))] }) })] }));
}
function RatingsPanel() {
    const { can } = useAuth();
    const [offset, setOffset] = useState(0);
    const ratings = useRatings(offset);
    const decide = useDecideRating();
    return (_jsxs(Panel, { title: "Ratings", subtitle: "A rating lasts a year. One that departs from the model's grade waits for someone other than its rater.", children: [_jsx(ErrorMessage, { error: ratings.error ?? decide.error }), _jsx("table", { "aria-label": "Ratings", className: "min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [ratings.data?.items.map((r) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: r.rating_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [r.customer_name, " (", r.customer_number, ") \u00B7 grade ", r.grade, r.grade !== r.suggested_grade && ` (model ${r.suggested_grade})`, " \u00B7 ", r.rationale] }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: RATING_TONE[r.status], label: r.status }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: r.status === "pending" && can("risk:approve") && (_jsxs("div", { className: "flex justify-end gap-1", children: [_jsx(Button, { size: "sm", "aria-label": `Approve ${r.rating_number}`, onClick: () => decide.mutate({ id: r.id, approve: true }), children: "Approve" }), _jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Reject ${r.rating_number}`, onClick: () => decide.mutate({ id: r.id, approve: false }), children: "Reject" })] })) })] }, r.id))), ratings.data && ratings.data.items.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No ratings yet." }) }))] }) }), _jsx(Pager, { label: "Rating pages", offset: offset, total: ratings.data?.total ?? 0, onChange: setOffset })] }));
}
function RunLines({ runId }) {
    const lines = useProvisionLines(runId);
    return (_jsxs(_Fragment, { children: [_jsx(ErrorMessage, { error: lines.error }), _jsx("table", { "aria-label": "Provision lines", className: "mt-2 min-w-full text-xs", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: lines.data?.items.map((l) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1 font-mono", children: l.reference }), _jsxs("td", { className: "px-2 py-1 text-slate-600", children: [l.exposure_type, " \u00B7 stage ", l.stage, " \u00B7 grade ", l.grade, " \u00B7 PD ", bps(l.pd_bps), " \u00B7 LGD ", bps(l.lgd_bps), l.days_past_due > 0 && ` · ${l.days_past_due} days past due`] }), _jsx("td", { className: "px-2 py-1 text-right tabular-nums", children: formatExactMoney(l.ecl, l.currency) })] }, `${l.exposure_type}-${l.reference}`))) }) })] }));
}
function ProvisionsPanel() {
    const { can } = useAuth();
    const [offset, setOffset] = useState(0);
    const runs = useProvisionRuns(offset);
    const calculate = useCalculate();
    const decide = useDecideRun();
    const [open, setOpen] = useState(null);
    return (_jsxs(Panel, { title: "Expected credit loss", subtitle: "A run measures the loan book's ECL as EAD \u00D7 PD \u00D7 LGD per exposure: stage 1 a year's PD, stage 2 (30+ days past due, grade 8 or worse, or a frozen facility) the lifetime PD over the remaining term, stage 3 (90+ days or in default) certain default. Posting books the change in the allowance against impairment expense, by someone other than the calculator.", children: [can("risk:rate") && (_jsxs("div", { className: "mb-3 flex items-center gap-2 text-xs", children: [_jsx(Button, { size: "sm", onClick: () => calculate.mutate(), disabled: calculate.isPending, children: "Calculate ECL" }), _jsx(ErrorMessage, { error: calculate.error })] })), _jsx(ErrorMessage, { error: runs.error ?? decide.error }), _jsx("table", { "aria-label": "Provision runs", className: "min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [runs.data?.items.map((run) => (_jsxs("tr", { className: "align-top", children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: _jsx("button", { type: "button", className: "underline decoration-dotted", "aria-expanded": open === run.id, "aria-label": `Lines of ${run.run_number}`, onClick: () => setOpen(open === run.id ? null : run.id), children: run.run_number }) }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: ["as of ", run.as_of, " \u00B7 ", run.exposures, " exposures", Object.entries(run.totals).map(([ccy, t]) => (_jsxs("div", { children: [ccy, ": ECL ", formatExactMoney(t.ecl, ccy), " (stage 1 ", formatExactMoney(t.stage_1, ccy), ", 2 ", formatExactMoney(t.stage_2, ccy), ", 3 ", formatExactMoney(t.stage_3, ccy), ") \u00B7 change ", formatExactMoney(t.change, ccy)] }, ccy))), open === run.id && _jsx(RunLines, { runId: run.id })] }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: RUN_TONE[run.status], label: run.status }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: run.status === "calculated" && can("risk:approve") && (_jsxs("div", { className: "flex justify-end gap-1", children: [_jsx(Button, { size: "sm", "aria-label": `Post ${run.run_number}`, onClick: () => decide.mutate({ id: run.id, post: true }), children: "Post" }), _jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Reject ${run.run_number}`, onClick: () => decide.mutate({ id: run.id, post: false }), children: "Reject" })] })) })] }, run.id))), runs.data && runs.data.items.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No provision runs yet." }) }))] }) }), _jsx(Pager, { label: "Run pages", offset: offset, total: runs.data?.total ?? 0, onChange: setOffset })] }));
}
/** Risk (Phase 47): internal credit ratings, obligor limits and ECL provisioning. */
export function RiskPage() {
    const summary = useRiskSummary();
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Risk", description: "Internal credit ratings with a model and four-eyes overrides, obligor limits against measured exposure, and IFRS 9 expected-credit-loss provisioning posted to the ledger." }), summary.data && (_jsx("dl", { "aria-label": "Risk summary", className: "mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4", children: [
                    ["Approved ratings", summary.data.ratings],
                    ["Ratings to approve", summary.data.ratings_pending],
                    ["Runs to post", summary.data.runs_to_approve],
                    ["Last posted run", summary.data.last_posted_run ? `${summary.data.last_posted_run} (${summary.data.last_posted_as_of})` : "None"],
                ].map(([label, value]) => (_jsxs("div", { className: "rounded-lg border border-slate-200 bg-white p-3", children: [_jsx("dt", { className: "text-xs text-slate-500", children: label }), _jsx("dd", { className: "text-lg font-semibold text-slate-900", children: value })] }, label))) })), _jsxs("div", { className: "flex flex-col gap-6", children: [_jsx(ObligorPanel, {}), _jsx(RatingsPanel, {}), _jsx(ProvisionsPanel, {})] })] }));
}
