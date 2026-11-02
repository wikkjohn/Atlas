import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { formatExactMoney, humanize } from "@/services/format";
import { WEALTH_PAGE, useClosePortfolio, useDistribute, useDistributions, useOpenPortfolio, useOrderAction, useOrders, usePlaceOrder, usePortfolios, useRecordProfile, useSecurities, useValuation, useWealthSummary, } from "@/services/wealth";
const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const TONE = {
    placed: "warn",
    awaiting_approval: "warn",
    executed: "good",
    rejected: "neutral",
};
function Field({ label, children }) {
    return (_jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: [label, children] }));
}
/** Newer/older paging for a list served newest first, `WEALTH_PAGE` rows at a time. */
function Pager({ label, offset, total, onChange }) {
    if (total <= WEALTH_PAGE)
        return null;
    return (_jsxs("nav", { "aria-label": label, className: "mt-2 flex items-center justify-end gap-2 text-xs text-slate-600", children: [_jsxs("span", { children: [offset + 1, "\u2013", Math.min(offset + WEALTH_PAGE, total), " of ", total] }), _jsx(Button, { size: "sm", variant: "secondary", disabled: offset === 0, onClick: () => onChange(Math.max(offset - WEALTH_PAGE, 0)), children: "Newer" }), _jsx(Button, { size: "sm", variant: "secondary", disabled: offset + WEALTH_PAGE >= total, onClick: () => onChange(offset + WEALTH_PAGE), children: "Older" })] }));
}
function SecuritiesPanel() {
    const securities = useSecurities();
    return (_jsxs(Panel, { title: "Securities", subtitle: "Synthetic securities at today's price. Risk runs from 1 (lowest) to 7; complex products need an informed investor.", children: [_jsx(ErrorMessage, { error: securities.error }), _jsx("table", { "aria-label": "Securities", className: "min-w-full text-sm", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: securities.data?.map((s) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: s.code }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [s.name, " \u00B7 ", humanize(s.asset_class), s.complex && " · complex"] }), _jsxs("td", { className: "px-2 py-1.5 text-xs", children: ["Risk ", s.risk_level] }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: formatExactMoney(s.price, s.currency) }), _jsx("td", { className: "px-2 py-1.5 text-right text-xs text-slate-600", children: s.income_bps ? `${(s.income_bps / 100).toFixed(2)} % income` : "no income" })] }, s.id))) }) })] }));
}
const PROFILE = { customer_number: "", objective: "balanced", horizon_years: 10, knowledge: "basic", loss_capacity: "medium" };
function SuitabilityPanel() {
    const record = useRecordProfile();
    const [form, setForm] = useState(PROFILE);
    const onSubmit = (event) => {
        event.preventDefault();
        record.mutate({ ...form, customer_number: form.customer_number.trim().toUpperCase() });
    };
    return (_jsxs(Panel, { title: "Suitability", subtitle: "The questionnaire gives a risk profile from 1 to 7, valid for a year: the objective's level, capped by a short horizon, a limited capacity for loss and no investment knowledge.", children: [_jsxs("form", { "aria-label": "Suitability assessment", onSubmit: onSubmit, className: "flex flex-wrap items-end gap-2 text-xs", children: [_jsx(Field, { label: "Customer", children: _jsx("input", { "aria-label": "Customer number", required: true, className: `w-36 ${INPUT}`, value: form.customer_number, onChange: (e) => setForm({ ...form, customer_number: e.target.value }) }) }), _jsx(Field, { label: "Objective", children: _jsx("select", { "aria-label": "Objective", className: INPUT, value: form.objective, onChange: (e) => setForm({ ...form, objective: e.target.value }), children: ["preservation", "income", "balanced", "growth"].map((v) => (_jsx("option", { value: v, children: humanize(v) }, v))) }) }), _jsx(Field, { label: "Horizon (years)", children: _jsx("input", { "aria-label": "Horizon", type: "number", min: 0, max: 50, className: `w-20 ${INPUT}`, value: form.horizon_years, onChange: (e) => setForm({ ...form, horizon_years: Number(e.target.value) }) }) }), _jsx(Field, { label: "Knowledge", children: _jsx("select", { "aria-label": "Knowledge", className: INPUT, value: form.knowledge, onChange: (e) => setForm({ ...form, knowledge: e.target.value }), children: ["none", "basic", "informed", "expert"].map((v) => (_jsx("option", { value: v, children: humanize(v) }, v))) }) }), _jsx(Field, { label: "Capacity for loss", children: _jsx("select", { "aria-label": "Capacity for loss", className: INPUT, value: form.loss_capacity, onChange: (e) => setForm({ ...form, loss_capacity: e.target.value }), children: ["low", "medium", "high"].map((v) => (_jsx("option", { value: v, children: humanize(v) }, v))) }) }), _jsx(Button, { size: "sm", type: "submit", disabled: record.isPending, children: "Record profile" }), _jsx(ErrorMessage, { error: record.error })] }), record.data && (_jsxs("p", { role: "status", className: "mt-2 text-xs text-slate-700", children: ["Risk profile ", record.data.risk_profile, ", valid until ", record.data.expires_on, "."] }))] }));
}
function PortfoliosPanel({ selected, onSelect }) {
    const { can } = useAuth();
    const [offset, setOffset] = useState(0);
    const portfolios = usePortfolios(offset);
    const open = useOpenPortfolio();
    const close = useClosePortfolio();
    const valuation = useValuation(selected);
    const [account, setAccount] = useState("");
    const onSubmit = (event) => {
        event.preventDefault();
        open.mutate(account.trim().toUpperCase(), { onSuccess: (p) => { setAccount(""); onSelect(p.portfolio_number); } });
    };
    const v = valuation.data;
    return (_jsxs(Panel, { title: "Portfolios", subtitle: "Custody accounts. Holdings are kept off the bank's balance sheet; the linked bank account pays for purchases and receives sales and income.", children: [can("wealth:advise") && (_jsxs("form", { "aria-label": "Open a portfolio", onSubmit: onSubmit, className: "mb-3 flex flex-wrap items-end gap-2 text-xs", children: [_jsx(Field, { label: "Paid from account", children: _jsx("input", { "aria-label": "Portfolio account", required: true, className: `w-40 ${INPUT}`, value: account, onChange: (e) => setAccount(e.target.value) }) }), _jsx(Button, { size: "sm", type: "submit", disabled: open.isPending, children: "Open portfolio" }), _jsx(ErrorMessage, { error: open.error })] })), _jsx(ErrorMessage, { error: portfolios.error ?? close.error }), _jsx("table", { "aria-label": "Portfolios", className: "min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [portfolios.data?.items.map((p) => (_jsxs("tr", { className: p.portfolio_number === selected ? "bg-slate-50" : undefined, children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: p.portfolio_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [p.customer_name, " (", p.customer_number, ") \u00B7 ", p.account_number, " \u00B7 ", p.currency, " \u00B7 ", p.risk_profile ? `risk profile ${p.risk_profile}` : "no current profile"] }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: p.status === "open" ? "good" : "neutral", label: p.status }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: _jsxs("div", { className: "flex justify-end gap-1", children: [_jsx(Button, { size: "sm", variant: "secondary", "aria-label": `View ${p.portfolio_number}`, onClick: () => onSelect(p.portfolio_number), children: "View" }), p.status === "open" && can("wealth:advise") && (_jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Close ${p.portfolio_number}`, onClick: () => close.mutate(p.portfolio_number), children: "Close" }))] }) })] }, p.id))), portfolios.data && portfolios.data.items.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No portfolios yet." }) }))] }) }), _jsx(Pager, { label: "Portfolio pages", offset: offset, total: portfolios.data?.total ?? 0, onChange: setOffset }), v && (_jsxs("section", { "aria-label": `Valuation of ${v.portfolio_number}`, className: "mt-4 rounded-md border border-slate-200 p-3", children: [_jsxs("h3", { className: "text-sm font-semibold text-slate-800", children: [v.portfolio_number, " on ", v.as_of, ": ", formatExactMoney(v.value, v.currency), " (", v.gain >= 0 ? "+" : "", formatExactMoney(v.gain, v.currency), " on cost) \u00B7 cash ", formatExactMoney(v.cash, v.currency)] }), _jsx("table", { "aria-label": "Holdings", className: "mt-2 min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [v.holdings.map((h) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: h.security_code }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [h.units, " units at ", formatExactMoney(h.price, h.price_currency), " \u00B7 risk ", h.risk_level] }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: formatExactMoney(h.value, v.currency) }), _jsx("td", { className: `px-2 py-1.5 text-right text-xs tabular-nums ${h.gain >= 0 ? "text-emerald-700" : "text-rose-700"}`, children: formatExactMoney(h.gain, v.currency) })] }, h.security_code))), v.holdings.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No holdings." }) }))] }) })] }))] }));
}
function OrdersPanel({ selected }) {
    const { can } = useAuth();
    const securities = useSecurities();
    const [offset, setOffset] = useState(0);
    const orders = useOrders(offset);
    const place = usePlaceOrder();
    const action = useOrderAction();
    const [form, setForm] = useState({ portfolio: "", security: "", side: "buy", units: "" });
    const portfolio = form.portfolio || selected || "";
    const onSubmit = (event) => {
        event.preventDefault();
        place.mutate({ portfolio_number: portfolio.trim().toUpperCase(), security_code: form.security, side: form.side, units: Number(form.units) }, { onSuccess: () => setForm({ ...form, units: "" }) });
    };
    const items = orders.data?.items ?? [];
    return (_jsxs(Panel, { title: "Orders", subtitle: "A buy is checked against the customer's risk profile. A sell or a suitable buy is executed at today's price; an unsuitable one waits for someone else to approve it at the client's insistence, or reject it.", children: [can("wealth:advise") && (_jsxs("form", { "aria-label": "Place an order", onSubmit: onSubmit, className: "mb-3 flex flex-wrap items-end gap-2 text-xs", children: [_jsx(Field, { label: "Portfolio", children: _jsx("input", { "aria-label": "Order portfolio", required: true, className: `w-36 ${INPUT}`, value: portfolio, onChange: (e) => setForm({ ...form, portfolio: e.target.value }) }) }), _jsx(Field, { label: "Security", children: _jsxs("select", { "aria-label": "Security", required: true, className: INPUT, value: form.security, onChange: (e) => setForm({ ...form, security: e.target.value }), children: [_jsx("option", { value: "", children: "Choose\u2026" }), securities.data?.map((s) => (_jsxs("option", { value: s.code, children: [s.code, " \u00B7 risk ", s.risk_level] }, s.code)))] }) }), _jsx(Field, { label: "Side", children: _jsxs("select", { "aria-label": "Side", className: INPUT, value: form.side, onChange: (e) => setForm({ ...form, side: e.target.value }), children: [_jsx("option", { value: "buy", children: "Buy" }), _jsx("option", { value: "sell", children: "Sell" })] }) }), _jsx(Field, { label: "Units", children: _jsx("input", { "aria-label": "Units", required: true, inputMode: "numeric", className: `w-24 ${INPUT}`, value: form.units, onChange: (e) => setForm({ ...form, units: e.target.value }) }) }), _jsx(Button, { size: "sm", type: "submit", disabled: place.isPending, children: "Place order" }), _jsx(ErrorMessage, { error: place.error })] })), _jsx(ErrorMessage, { error: orders.error ?? action.error }), _jsx("table", { "aria-label": "Orders", className: "min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [items.map((o) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: o.order_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [o.portfolio_number, " \u00B7 ", o.side, " ", o.units, " ", o.security_code, " at ", formatExactMoney(o.price, o.price_currency), " \u00B7 fee ", formatExactMoney(o.fee, o.currency), o.reasons.length > 0 && ` · ${o.reasons.map((r) => r.message).join(" ")}`, o.note && ` · ${o.note}`] }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: formatExactMoney(o.amount, o.currency) }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: TONE[o.status], label: humanize(o.status) }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: _jsxs("div", { className: "flex justify-end gap-1", children: [(o.status === "awaiting_approval" || o.status === "placed") && can("wealth:approve") && (_jsxs(_Fragment, { children: [_jsx(Button, { size: "sm", "aria-label": `Approve ${o.order_number}`, onClick: () => action.mutate({ id: o.id, action: "approve" }), children: "Approve" }), _jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Reject ${o.order_number}`, onClick: () => action.mutate({ id: o.id, action: "reject" }), children: "Reject" })] })), o.status === "placed" && can("wealth:advise") && (_jsx(Button, { size: "sm", "aria-label": `Release ${o.order_number}`, onClick: () => action.mutate({ id: o.id, action: "release" }), children: "Release" }))] }) })] }, o.id))), orders.data && items.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No orders yet." }) }))] }) }), _jsx(Pager, { label: "Order pages", offset: offset, total: orders.data?.total ?? 0, onChange: setOffset })] }));
}
function IncomePanel() {
    const { can } = useAuth();
    const securities = useSecurities();
    const distributions = useDistributions();
    const distribute = useDistribute();
    const [code, setCode] = useState("");
    const onSubmit = (event) => {
        event.preventDefault();
        distribute.mutate(code);
    };
    return (_jsxs(Panel, { title: "Income", subtitle: "Custody pays half a year's income at today's price to every holder, into each portfolio's account in its currency; once per security and day.", children: [can("wealth:custody") && (_jsxs("form", { "aria-label": "Pay income", onSubmit: onSubmit, className: "mb-3 flex flex-wrap items-end gap-2 text-xs", children: [_jsx(Field, { label: "Security", children: _jsxs("select", { "aria-label": "Income security", required: true, className: INPUT, value: code, onChange: (e) => setCode(e.target.value), children: [_jsx("option", { value: "", children: "Choose\u2026" }), securities.data
                                    ?.filter((s) => s.income_bps > 0)
                                    .map((s) => (_jsx("option", { value: s.code, children: s.code }, s.code)))] }) }), _jsx(Button, { size: "sm", type: "submit", disabled: distribute.isPending, children: "Pay holders" }), _jsx(ErrorMessage, { error: distribute.error })] })), _jsx(ErrorMessage, { error: distributions.error }), _jsx("table", { "aria-label": "Income distributions", className: "min-w-full text-sm", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: distributions.data?.items.map((d) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: d.distribution_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [d.security_code, " on ", d.record_date, " \u00B7 ", formatExactMoney(d.income_per_unit, d.currency), " a unit"] }), _jsxs("td", { className: "px-2 py-1.5 text-right text-xs", children: [d.holders, " holders"] })] }, d.id))) }) })] }));
}
/** Wealth and investments (Phase 43): securities, suitability, portfolios, orders and income. */
export function WealthPage() {
    const summary = useWealthSummary();
    const [selected, setSelected] = useState(null);
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Wealth", description: "Synthetic securities, suitability assessments, portfolios held in custody, orders checked against the customer's risk profile, and income paid to holders." }), summary.data && (_jsx("dl", { "aria-label": "Wealth summary", className: "mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5", children: [
                    ["Open portfolios", summary.data.portfolios],
                    ["Awaiting approval", summary.data.awaiting_approval],
                    ["Waiting for release", summary.data.placed],
                    ["Executed orders", summary.data.executed],
                    ["Profiles recorded", summary.data.profiles],
                ].map(([label, value]) => (_jsxs("div", { className: "rounded-lg border border-slate-200 bg-white p-3", children: [_jsx("dt", { className: "text-xs text-slate-500", children: label }), _jsx("dd", { className: "text-lg font-semibold text-slate-900", children: value })] }, label))) })), _jsxs("div", { className: "flex flex-col gap-6", children: [_jsx(SecuritiesPanel, {}), _jsx(SuitabilityPanel, {}), _jsx(PortfoliosPanel, { selected: selected, onSelect: setSelected }), _jsx(OrdersPanel, { selected: selected }), _jsx(IncomePanel, {})] })] }));
}
