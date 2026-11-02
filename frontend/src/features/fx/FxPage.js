import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { formatExactMoney } from "@/services/format";
import { useFxDeals, useFxPositions, useFxQuote, useFxRates, useFxRevaluations, useRevalue } from "@/services/fx";
const today = () => new Date().toISOString().slice(0, 10);
const MAJOR_CURRENCIES = ["EUR", "GBP", "JPY", "CHF", "SGD", "CNY", "INR", "AED", "BRL", "ZAR"];
function usd(cents) {
    return formatExactMoney(cents, "USD");
}
function RatesSection({ day }) {
    const rates = useFxRates(day);
    const [all, setAll] = useState(false);
    const shown = (rates.data ?? []).filter((r) => all || MAJOR_CURRENCIES.includes(r.currency));
    return (_jsxs("section", { "aria-label": "Exchange rates", className: "space-y-2", children: [_jsxs("div", { className: "flex items-center gap-3", children: [_jsxs("h2", { className: "text-sm font-semibold text-slate-900", children: ["Rates on ", day] }), _jsx("span", { className: "text-xs text-slate-500", children: "units per US dollar \u00B7 synthetic" }), _jsxs("label", { className: "flex items-center gap-1.5 text-xs text-slate-600", children: [_jsx("input", { type: "checkbox", checked: all, onChange: (e) => setAll(e.target.checked) }), "All ", rates.data?.length ?? "", " currencies"] })] }), _jsx(ErrorMessage, { error: rates.error }), _jsx("ul", { className: "grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4 lg:grid-cols-5", children: shown.map((r) => (_jsxs("li", { className: "flex justify-between gap-2", children: [_jsx("span", { className: "font-mono text-xs text-slate-600", children: r.currency }), _jsx("span", { className: "tabular-nums text-slate-900", children: Number(r.units_per_usd).toPrecision(6) })] }, r.currency))) })] }));
}
function QuoteSection({ day, currencies }) {
    const quote = useFxQuote();
    const [sell, setSell] = useState("USD");
    const [buy, setBuy] = useState("EUR");
    const [amount, setAmount] = useState("1000");
    const onSubmit = (event) => {
        event.preventDefault();
        // Whole units entered; the API takes minor units (assume the common two decimals for USD-like input).
        const digits = new Intl.NumberFormat("en", { style: "currency", currency: sell }).resolvedOptions().maximumFractionDigits ?? 2;
        quote.mutate({ sell_currency: sell, buy_currency: buy, sell_amount: Math.round(Number(amount) * 10 ** digits), rate_date: day });
    };
    const select = (label, value, onChange) => (_jsx("select", { "aria-label": label, className: "rounded-md border border-slate-200 px-2 py-1 text-sm", value: value, onChange: (e) => onChange(e.target.value), children: currencies.map((c) => (_jsx("option", { children: c }, c))) }));
    return (_jsxs("section", { "aria-label": "Quote", className: "space-y-2", children: [_jsx("h2", { className: "text-sm font-semibold text-slate-900", children: "Quote a conversion" }), _jsxs("form", { onSubmit: onSubmit, className: "flex flex-wrap items-center gap-2 text-sm", children: [_jsx("input", { "aria-label": "Amount", type: "number", min: "0", step: "any", className: "w-28 rounded-md border border-slate-200 px-2 py-1", value: amount, onChange: (e) => setAmount(e.target.value), required: true }), select("Sell", sell, setSell), _jsx("span", { className: "text-slate-500", children: "\u2192" }), select("Buy", buy, setBuy), _jsx(Button, { size: "sm", variant: "secondary", type: "submit", disabled: quote.isPending, children: "Quote" })] }), _jsx(ErrorMessage, { error: quote.error }), quote.data && (_jsxs("p", { role: "status", className: "text-sm text-slate-700", children: [formatExactMoney(quote.data.sell_amount, quote.data.sell_currency), " buys", " ", _jsx("strong", { children: formatExactMoney(quote.data.buy_amount, quote.data.buy_currency) }), " at", " ", Number(quote.data.customer_rate).toPrecision(6), " (mid ", Number(quote.data.mid_rate).toPrecision(6), ", margin", " ", quote.data.margin_bps / 100, " %)"] }))] }));
}
function PositionsSection({ day }) {
    const { can } = useAuth();
    const positions = useFxPositions(day);
    const runs = useFxRevaluations();
    const deals = useFxDeals();
    const revalue = useRevalue();
    const p = positions.data;
    return (_jsxs(_Fragment, { children: [_jsxs("section", { "aria-label": "Currency positions", className: "space-y-2", children: [_jsxs("div", { className: "flex flex-wrap items-center gap-3", children: [_jsx("h2", { className: "text-sm font-semibold text-slate-900", children: "Open currency positions" }), can("fx:manage") && (_jsxs(Button, { size: "sm", disabled: revalue.isPending, onClick: () => revalue.mutate(day), children: ["Revalue as of ", day] }))] }), _jsx(ErrorMessage, { error: positions.error ?? revalue.error }), p && (_jsxs(_Fragment, { children: [_jsxs("dl", { className: "grid grid-cols-3 gap-3 text-sm", children: [_jsxs("div", { children: [_jsx("dt", { className: "text-xs text-slate-500", children: "Value of positions" }), _jsx("dd", { className: "font-semibold tabular-nums", children: usd(p.total_value_usd) })] }), _jsxs("div", { children: [_jsx("dt", { className: "text-xs text-slate-500", children: "Booked by revaluation" }), _jsx("dd", { className: "tabular-nums", children: usd(p.booked_usd) })] }), _jsxs("div", { children: [_jsx("dt", { className: "text-xs text-slate-500", children: "Not yet booked" }), _jsx("dd", { role: "status", "aria-label": "Unbooked FX result", className: `tabular-nums ${p.unbooked_usd < 0 ? "text-rose-700" : "text-emerald-700"}`, children: usd(p.unbooked_usd) })] })] }), p.positions.length === 0 ? (_jsx("p", { className: "text-sm text-slate-500", children: "No conversions yet: no open positions." })) : (_jsxs("table", { "aria-label": "Positions", className: "min-w-full text-sm", children: [_jsx("thead", { className: "text-left text-xs text-slate-500", children: _jsxs("tr", { children: [_jsx("th", { className: "py-1 pr-4", children: "Currency" }), _jsx("th", { className: "py-1 pr-4 text-right", children: "Position (long +)" }), _jsx("th", { className: "py-1 pr-4 text-right", children: "Rate" }), _jsx("th", { className: "py-1 text-right", children: "Value in USD" })] }) }), _jsx("tbody", { children: p.positions.map((row) => (_jsxs("tr", { children: [_jsx("td", { className: "py-1 pr-4 font-mono text-xs", children: row.currency }), _jsx("td", { className: "py-1 pr-4 text-right tabular-nums", children: formatExactMoney(row.position, row.currency) }), _jsx("td", { className: "py-1 pr-4 text-right tabular-nums", children: Number(row.units_per_usd).toPrecision(6) }), _jsx("td", { className: "py-1 text-right tabular-nums", children: usd(row.value_usd) })] }, row.currency))) })] }))] }))] }), _jsxs("section", { "aria-label": "Revaluations", className: "space-y-1", children: [_jsx("h2", { className: "text-sm font-semibold text-slate-900", children: "Revaluations" }), _jsx(ErrorMessage, { error: runs.error }), _jsxs("ul", { className: "text-xs text-slate-600", children: [runs.data?.items.map((r) => (_jsxs("li", { children: ["#", r.run_number, " as of ", r.as_of, ": posted ", usd(r.posted), " (positions worth ", usd(r.total_value), ")"] }, r.id))), runs.data?.items.length === 0 && _jsx("li", { children: "None yet." })] })] }), _jsxs("section", { "aria-label": "Conversions", className: "space-y-1", children: [_jsx("h2", { className: "text-sm font-semibold text-slate-900", children: "Recent conversions" }), _jsx(ErrorMessage, { error: deals.error }), _jsxs("ul", { className: "text-xs text-slate-600", children: [deals.data?.items.map((d) => (_jsxs("li", { children: [_jsx("span", { className: "font-mono", children: d.deal_number }), " ", d.rate_date, ": ", formatExactMoney(d.sell_amount, d.sell_currency), " \u2192", " ", formatExactMoney(d.buy_amount, d.buy_currency), " at ", Number(d.customer_rate).toPrecision(6), " (", d.purpose, ", ", d.reference, ")"] }, d.id))), deals.data?.items.length === 0 && _jsx("li", { children: "None yet." })] })] })] }));
}
export function FxPage() {
    const { can } = useAuth();
    const [day, setDay] = useState(today);
    const rates = useFxRates(day);
    const currencies = (rates.data ?? []).map((r) => r.currency);
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Foreign Exchange", description: "Synthetic daily rates, quotes and the bank's open currency positions. Payments to an account in another currency convert at release; revaluation books the positions' value in US dollars." }), _jsxs("div", { className: "mb-4 flex items-center gap-2 text-sm", children: [_jsx("label", { htmlFor: "fx-day", className: "text-xs font-medium text-slate-600", children: "Date" }), _jsx("input", { id: "fx-day", type: "date", className: "rounded-md border border-slate-200 px-2 py-1", value: day, onChange: (e) => e.target.value && setDay(e.target.value) })] }), _jsxs("div", { className: "space-y-6", children: [_jsx(RatesSection, { day: day }), currencies.length > 0 && _jsx(QuoteSection, { day: day, currencies: currencies }), can("ledger:read") && _jsx(PositionsSection, { day: day })] })] }));
}
