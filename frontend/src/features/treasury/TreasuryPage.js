import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { formatExactMoney, humanize } from "@/services/format";
import { TREASURY_PAGE, useBookDeal, useBookFxTrade, useCounterparties, useDealAction, useDeals, useFxDesk, useFxTradeAction, useFxTrades, useLiquidity, useSetCounterpartyLimit, useTreasurySummary, } from "@/services/treasury";
const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const TONE = { booked: "warn", settled: "good", matured: "neutral", cancelled: "neutral" };
const usd = (dollars) => formatExactMoney(dollars * 100, "USD");
const percent = (bps) => (bps === null ? "—" : `${(bps / 100).toFixed(0)} %`);
function Field({ label, children }) {
    return (_jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: [label, children] }));
}
/** Newer/Older paging once a list has more than one page (PR #30 review). */
function Pager({ label, offset, total, onChange }) {
    if (total <= TREASURY_PAGE)
        return null;
    return (_jsxs("nav", { "aria-label": label, className: "mt-2 flex items-center justify-end gap-2 text-xs text-slate-600", children: [_jsxs("span", { children: [offset + 1, "\u2013", Math.min(offset + TREASURY_PAGE, total), " of ", total] }), _jsx(Button, { size: "sm", variant: "secondary", disabled: offset === 0, onClick: () => onChange(Math.max(offset - TREASURY_PAGE, 0)), children: "Newer" }), _jsx(Button, { size: "sm", variant: "secondary", disabled: offset + TREASURY_PAGE >= total, onClick: () => onChange(offset + TREASURY_PAGE), children: "Older" })] }));
}
function CounterpartySelect({ value, onChange, parties, label }) {
    return (_jsxs("select", { "aria-label": label, required: true, className: INPUT, value: value, onChange: (e) => onChange(e.target.value), children: [_jsx("option", { value: "", children: "Choose\u2026" }), parties.map((p) => (_jsxs("option", { value: p.code, children: [p.code, " (", p.rating, ")"] }, p.code)))] }));
}
const EMPTY_DEAL = { kind: "placement", counterparty: "", currency: "", principal: "", rate: "", tenor: "30" };
function BookDealForm({ parties }) {
    const book = useBookDeal();
    const [form, setForm] = useState(EMPTY_DEAL);
    const set = (key) => (value) => setForm({ ...form, [key]: value });
    const onSubmit = (event) => {
        event.preventDefault();
        book.mutate({
            kind: form.kind,
            counterparty_code: form.counterparty,
            currency: form.currency.trim(),
            principal_major: Number(form.principal),
            rate_percent: Number(form.rate),
            tenor_days: Number(form.tenor),
        }, { onSuccess: () => setForm(EMPTY_DEAL) });
    };
    return (_jsxs("form", { "aria-label": "Book a deal", onSubmit: onSubmit, className: "mb-3 flex flex-wrap items-end gap-2 text-xs", children: [_jsx(Field, { label: "Kind", children: _jsxs("select", { "aria-label": "Kind", className: INPUT, value: form.kind, onChange: (e) => set("kind")(e.target.value), children: [_jsx("option", { value: "placement", children: "Placement (we lend)" }), _jsx("option", { value: "borrowing", children: "Borrowing (we take)" })] }) }), _jsx(Field, { label: "Counterparty", children: _jsx(CounterpartySelect, { label: "Counterparty", value: form.counterparty, onChange: set("counterparty"), parties: parties }) }), _jsx(Field, { label: "Currency", children: _jsx("input", { "aria-label": "Currency", required: true, maxLength: 3, className: `w-16 ${INPUT}`, value: form.currency, onChange: (e) => set("currency")(e.target.value) }) }), _jsx(Field, { label: "Principal", children: _jsx("input", { "aria-label": "Principal", required: true, inputMode: "decimal", className: `w-32 ${INPUT}`, value: form.principal, onChange: (e) => set("principal")(e.target.value) }) }), _jsx(Field, { label: "Rate (% a year)", children: _jsx("input", { "aria-label": "Rate", required: true, inputMode: "decimal", className: `w-20 ${INPUT}`, value: form.rate, onChange: (e) => set("rate")(e.target.value) }) }), _jsx(Field, { label: "Tenor (days)", children: _jsx("input", { "aria-label": "Tenor", required: true, inputMode: "numeric", className: `w-20 ${INPUT}`, value: form.tenor, onChange: (e) => set("tenor")(e.target.value) }) }), _jsx(Button, { size: "sm", type: "submit", disabled: book.isPending, children: "Book" }), _jsx(ErrorMessage, { error: book.error })] }));
}
function DealsPanel({ parties }) {
    const { can } = useAuth();
    const [offset, setOffset] = useState(0);
    const deals = useDeals(offset);
    const action = useDealAction();
    const today = new Date().toISOString().slice(0, 10);
    const items = deals.data?.items ?? [];
    return (_jsxs(Panel, { title: "Money-market deals", subtitle: "Placements need an investment-grade counterparty (BBB- or better) within its limit, and must leave the currency's 30-day liquidity coverage at 100 % or more. Back office, not the dealer, confirms and settles.", children: [can("treasury:deal") && _jsx(BookDealForm, { parties: parties }), _jsx(ErrorMessage, { error: deals.error ?? action.error }), _jsx("table", { "aria-label": "Deals", className: "min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [items.map((d) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: d.deal_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [humanize(d.kind), " \u00B7 ", d.counterparty_code, " \u00B7 ", (d.rate_bps / 100).toFixed(2), " % ACT/", d.day_basis, " \u00B7 matures ", d.maturity_date] }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: formatExactMoney(d.principal, d.currency) }), _jsxs("td", { className: "px-2 py-1.5 text-right text-xs tabular-nums text-slate-600", children: ["interest ", formatExactMoney(d.interest, d.currency)] }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: TONE[d.status], label: d.status }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: _jsxs("div", { className: "flex justify-end gap-1", children: [d.status === "booked" && can("treasury:confirm") && (_jsx(Button, { size: "sm", "aria-label": `Confirm ${d.deal_number}`, onClick: () => action.mutate({ id: d.id, action: "confirm" }), children: "Confirm" })), d.status === "booked" && can("treasury:deal") && (_jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Cancel ${d.deal_number}`, onClick: () => action.mutate({ id: d.id, action: "cancel" }), children: "Cancel" })), d.status === "settled" && d.maturity_date <= today && can("treasury:confirm") && (_jsx(Button, { size: "sm", "aria-label": `Mature ${d.deal_number}`, onClick: () => action.mutate({ id: d.id, action: "mature" }), children: "Settle maturity" }))] }) })] }, d.id))), deals.data && items.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No deals yet." }) }))] }) }), _jsx(Pager, { label: "Deal pages", offset: offset, total: deals.data?.total ?? 0, onChange: setOffset })] }));
}
function CounterpartiesPanel({ parties }) {
    const { can } = useAuth();
    const setLimit = useSetCounterpartyLimit();
    const [code, setCode] = useState("");
    const [limit, setLimitValue] = useState("");
    const onSubmit = (event) => {
        event.preventDefault();
        setLimit.mutate({ code, limit_usd: Math.round(Number(limit)) }, { onSuccess: () => setLimitValue("") });
    };
    return (_jsxs(Panel, { title: "Counterparties", subtitle: "Synthetic banks. Exposure is outstanding placements at today's rates.", children: [_jsx("table", { "aria-label": "Counterparties", className: "min-w-full text-sm", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: parties.map((p) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: p.code }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [p.name, " \u00B7 ", p.country_code, " \u00B7 ", p.rating, !p.investment_grade && " (borrowing only)"] }), _jsxs("td", { className: "px-2 py-1.5 text-right text-xs tabular-nums", children: [usd(p.exposure_usd), " of ", usd(p.limit_usd)] })] }, p.code))) }) }), can("treasury:limits") && (_jsxs("form", { "aria-label": "Counterparty limit", onSubmit: onSubmit, className: "mt-3 flex flex-wrap items-end gap-2 text-xs", children: [_jsx(Field, { label: "Counterparty", children: _jsx(CounterpartySelect, { label: "Limit counterparty", value: code, onChange: setCode, parties: parties }) }), _jsx(Field, { label: "Limit (US$)", children: _jsx("input", { "aria-label": "Limit", required: true, inputMode: "numeric", className: `w-32 ${INPUT}`, value: limit, onChange: (e) => setLimitValue(e.target.value) }) }), _jsx(Button, { size: "sm", type: "submit", disabled: setLimit.isPending, children: "Set limit" }), _jsx(ErrorMessage, { error: setLimit.error })] }))] }));
}
function LiquidityPanel() {
    const liquidity = useLiquidity();
    const data = liquidity.data;
    return (_jsxs(Panel, { title: "Liquidity", subtitle: data ? `Next ${data.horizon_days} days: cash and placements coming back, against borrowings falling due and a ${data.run_off_bps / 100} % run-off of customer deposits. Minimum ${data.minimum_bps / 100} %.` : undefined, children: [_jsx(ErrorMessage, { error: liquidity.error }), _jsxs("table", { "aria-label": "Liquidity", className: "min-w-full text-sm", children: [_jsx("thead", { children: _jsxs("tr", { className: "text-left text-xs text-slate-500", children: [_jsx("th", { className: "px-2 py-1", children: "Currency" }), _jsx("th", { className: "px-2 py-1 text-right", children: "Liquid" }), _jsx("th", { className: "px-2 py-1 text-right", children: "Stressed outflow" }), _jsx("th", { className: "px-2 py-1 text-right", children: "Coverage" })] }) }), _jsx("tbody", { className: "divide-y divide-slate-100", children: data?.currencies.map((r) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: r.currency }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: formatExactMoney(r.liquid, r.currency) }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: formatExactMoney(r.stressed_outflow, r.currency) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: _jsx(StatusPill, { compact: true, tone: r.below_minimum ? "bad" : "good", label: percent(r.coverage_bps) }) })] }, r.currency))) })] })] }));
}
function FxDeskPanel({ parties }) {
    const { can } = useAuth();
    const desk = useFxDesk();
    const [tradeOffset, setTradeOffset] = useState(0);
    const trades = useFxTrades(tradeOffset);
    const book = useBookFxTrade();
    const action = useFxTradeAction();
    const [form, setForm] = useState({ counterparty: "", sell: "", buy: "USD", amount: "" });
    const onSubmit = (event) => {
        event.preventDefault();
        book.mutate({ counterparty_code: form.counterparty, sell_currency: form.sell.trim(), buy_currency: form.buy.trim(), sell_major: Number(form.amount) }, { onSuccess: () => setForm({ ...form, amount: "" }) });
    };
    return (_jsxs(Panel, { title: "FX desk", subtitle: "Open positions against their net open position limits. A spot trade at the day's mid rate may only reduce a long position.", children: [_jsx(ErrorMessage, { error: desk.error ?? trades.error ?? action.error }), _jsx("table", { "aria-label": "Positions", className: "min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [desk.data?.positions.map((p) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: p.currency }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: formatExactMoney(p.position, p.currency) }), _jsxs("td", { className: "px-2 py-1.5 text-right text-xs tabular-nums text-slate-600", children: [formatExactMoney(p.value_usd, "USD"), " of ", usd(p.limit_usd)] }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: p.over_limit ? "bad" : "good", label: p.over_limit ? "over limit" : "within" }) })] }, p.currency))), desk.data && desk.data.positions.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No open positions." }) }))] }) }), can("treasury:deal") && (_jsxs("form", { "aria-label": "Square a position", onSubmit: onSubmit, className: "mt-3 flex flex-wrap items-end gap-2 text-xs", children: [_jsx(Field, { label: "Counterparty", children: _jsx(CounterpartySelect, { label: "Trade counterparty", value: form.counterparty, onChange: (v) => setForm({ ...form, counterparty: v }), parties: parties }) }), _jsx(Field, { label: "Sell", children: _jsx("input", { "aria-label": "Sell currency", required: true, maxLength: 3, className: `w-16 ${INPUT}`, value: form.sell, onChange: (e) => setForm({ ...form, sell: e.target.value }) }) }), _jsx(Field, { label: "Buy", children: _jsx("input", { "aria-label": "Buy currency", required: true, maxLength: 3, className: `w-16 ${INPUT}`, value: form.buy, onChange: (e) => setForm({ ...form, buy: e.target.value }) }) }), _jsx(Field, { label: "Amount sold", children: _jsx("input", { "aria-label": "Amount sold", required: true, inputMode: "decimal", className: `w-32 ${INPUT}`, value: form.amount, onChange: (e) => setForm({ ...form, amount: e.target.value }) }) }), _jsx(Button, { size: "sm", type: "submit", disabled: book.isPending, children: "Book trade" }), _jsx(ErrorMessage, { error: book.error })] })), _jsx("table", { "aria-label": "FX trades", className: "mt-3 min-w-full text-sm", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: trades.data?.items.map((t) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: t.trade_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: ["sold ", formatExactMoney(t.sell_amount, t.sell_currency), " for ", formatExactMoney(t.buy_amount, t.buy_currency), " \u00B7 ", t.counterparty_code, " \u00B7 mid ", t.mid_rate] }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: t.status === "settled" ? "good" : t.status === "booked" ? "warn" : "neutral", label: t.status }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: t.status === "booked" && (_jsxs("div", { className: "flex justify-end gap-1", children: [can("treasury:confirm") && (_jsx(Button, { size: "sm", "aria-label": `Confirm ${t.trade_number}`, onClick: () => action.mutate({ id: t.id, action: "confirm" }), children: "Confirm" })), can("treasury:deal") && (_jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Cancel ${t.trade_number}`, onClick: () => action.mutate({ id: t.id, action: "cancel" }), children: "Cancel" }))] })) })] }, t.id))) }) }), _jsx(Pager, { label: "FX trade pages", offset: tradeOffset, total: trades.data?.total ?? 0, onChange: setTradeOffset })] }));
}
/** Treasury and markets (Phase 39): interbank deals, counterparties, liquidity and the FX desk. */
export function TreasuryPage() {
    const summary = useTreasurySummary();
    const counterparties = useCounterparties();
    const parties = counterparties.data ?? [];
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Treasury", description: "Interbank placements and borrowings with synthetic counterparty banks, booked by a dealer and settled by back office; the bank's 30-day liquidity by currency; and the FX desk's open positions against their limits." }), summary.data && (_jsx("dl", { "aria-label": "Treasury summary", className: "mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4", children: [
                    ["Deals to confirm", summary.data.booked],
                    ["Placements out", summary.data.placements],
                    ["Borrowings in", summary.data.borrowings],
                    ["FX trades to confirm", summary.data.fx_trades_booked],
                ].map(([label, value]) => (_jsxs("div", { className: "rounded-lg border border-slate-200 bg-white p-3", children: [_jsx("dt", { className: "text-xs text-slate-500", children: label }), _jsx("dd", { className: "text-lg font-semibold text-slate-900", children: value })] }, label))) })), _jsx(ErrorMessage, { error: counterparties.error }), _jsxs("div", { className: "flex flex-col gap-6", children: [_jsx(DealsPanel, { parties: parties }), _jsx(LiquidityPanel, {}), _jsx(FxDeskPanel, { parties: parties }), _jsx(CounterpartiesPanel, { parties: parties })] })] }));
}
