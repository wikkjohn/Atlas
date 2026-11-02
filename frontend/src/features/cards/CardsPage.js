import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { formatExactMoney } from "@/services/format";
import { useAuthorizations, useAuthorize, useCardAction, useCards, useCardSummary, useDecideDispute, useDisputes, useIssueCard, useOpenDispute, } from "@/services/cards";
const CARD_TONE = { active: "good", blocked: "bad", cancelled: "neutral" };
// A few synthetic merchant categories for the terminal (ISO 18245 style codes).
const CATEGORIES = [
    ["5411", "Groceries"],
    ["5812", "Restaurants"],
    ["5942", "Books"],
    ["4111", "Transport"],
    ["7995", "Gambling (high risk)"],
    ["6051", "Crypto (high risk)"],
];
function IssueForm() {
    const issue = useIssueCard();
    const [account, setAccount] = useState("");
    const [product, setProduct] = useState("debit-standard");
    const onSubmit = (event) => {
        event.preventDefault();
        issue.mutate({ account_number: account.trim(), product_code: product }, { onSuccess: () => setAccount("") });
    };
    return (_jsxs("form", { "aria-label": "Issue a card", onSubmit: onSubmit, className: "mb-3 flex flex-wrap items-end gap-2 text-xs", children: [_jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Account", _jsx("input", { "aria-label": "Account", required: true, className: "w-44 rounded-md border border-slate-200 px-2 py-1", value: account, onChange: (e) => setAccount(e.target.value) })] }), _jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Product", _jsxs("select", { "aria-label": "Product", className: "rounded-md border border-slate-200 px-2 py-1", value: product, onChange: (e) => setProduct(e.target.value), children: [_jsx("option", { value: "debit-standard", children: "ATLAS Debit" }), _jsx("option", { value: "debit-premium", children: "ATLAS Debit Premium" })] })] }), _jsx(Button, { size: "sm", type: "submit", disabled: issue.isPending, children: "Issue card" }), _jsx(ErrorMessage, { error: issue.error })] }));
}
function Terminal({ cards }) {
    const authorize = useAuthorize();
    const [cardId, setCardId] = useState("");
    const [merchant, setMerchant] = useState("Corner Grocer");
    const [category, setCategory] = useState("5411");
    const [country, setCountry] = useState("GB");
    const [amount, setAmount] = useState("25.00");
    const card = cards.find((c) => c.id === cardId) ?? cards[0];
    const onSubmit = (event) => {
        event.preventDefault();
        if (!card)
            return;
        authorize.mutate({
            cardId: card.id,
            merchant_name: merchant,
            merchant_category: category,
            merchant_country: country.toUpperCase(),
            amount: Math.round(Number(amount) * 100),
        });
    };
    const result = authorize.data;
    return (_jsxs(Panel, { title: "Merchant terminal", subtitle: "A synthetic point of sale. Checks: card status and expiry, the daily limit, funds (with any arranged overdraft), then the fraud rules \u2014 a score of 70 or more declines the purchase and blocks the card.", children: [_jsxs("form", { "aria-label": "Merchant terminal", onSubmit: onSubmit, className: "flex flex-wrap items-end gap-2 text-xs", children: [_jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Card", _jsx("select", { "aria-label": "Card", className: "rounded-md border border-slate-200 px-2 py-1", value: card?.id ?? "", onChange: (e) => setCardId(e.target.value), children: cards.map((c) => (_jsxs("option", { value: c.id, children: [c.card_number, " (", c.currency, ")"] }, c.id))) })] }), _jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Merchant", _jsx("input", { "aria-label": "Merchant", className: "w-36 rounded-md border border-slate-200 px-2 py-1", value: merchant, onChange: (e) => setMerchant(e.target.value) })] }), _jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Category", _jsx("select", { "aria-label": "Category", className: "rounded-md border border-slate-200 px-2 py-1", value: category, onChange: (e) => setCategory(e.target.value), children: CATEGORIES.map(([code, label]) => (_jsxs("option", { value: code, children: [code, " ", label] }, code))) })] }), _jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Country", _jsx("input", { "aria-label": "Merchant country", maxLength: 2, className: "w-14 rounded-md border border-slate-200 px-2 py-1", value: country, onChange: (e) => setCountry(e.target.value) })] }), _jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Amount", _jsx("input", { "aria-label": "Amount", className: "w-24 rounded-md border border-slate-200 px-2 py-1", value: amount, onChange: (e) => setAmount(e.target.value) })] }), _jsx(Button, { size: "sm", type: "submit", disabled: authorize.isPending || !card, children: "Pay" })] }), _jsx(ErrorMessage, { error: authorize.error }), result && (_jsxs("p", { role: "status", className: `mt-2 text-sm ${result.status === "approved" ? "text-emerald-700" : "text-rose-700"}`, children: [result.auth_code, ": ", result.status, result.decline_reason && ` (${result.decline_reason.replace("_", " ")})`, " \u00B7 fraud score ", result.fraud_score, result.fraud_signals.length > 0 && ` · ${result.fraud_signals.join(", ")}`] }))] }));
}
function DisputesPanel() {
    const { can } = useAuth();
    const disputes = useDisputes();
    const open = useOpenDispute();
    const decide = useDecideDispute();
    const [code, setCode] = useState("");
    const [reason, setReason] = useState("not_recognised");
    const onSubmit = (event) => {
        event.preventDefault();
        open.mutate({ auth_code: code.trim(), reason }, { onSuccess: () => setCode("") });
    };
    return (_jsxs(Panel, { title: "Disputes and chargebacks", subtitle: "Someone other than the person who opened a dispute decides it. Upheld, the amount is charged back to the account through card settlement.", children: [can("accounts:transact") && (_jsxs("form", { "aria-label": "Open a dispute", onSubmit: onSubmit, className: "mb-3 flex flex-wrap items-end gap-2 text-xs", children: [_jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Purchase", _jsx("input", { "aria-label": "Authorisation code", required: true, placeholder: "AUTH-00000001", className: "w-36 rounded-md border border-slate-200 px-2 py-1", value: code, onChange: (e) => setCode(e.target.value) })] }), _jsxs("label", { className: "flex flex-col gap-0.5 text-slate-600", children: ["Reason", _jsxs("select", { "aria-label": "Reason", className: "rounded-md border border-slate-200 px-2 py-1", value: reason, onChange: (e) => setReason(e.target.value), children: [_jsx("option", { value: "not_recognised", children: "Not recognised" }), _jsx("option", { value: "not_received", children: "Not received" }), _jsx("option", { value: "duplicate", children: "Duplicate" }), _jsx("option", { value: "wrong_amount", children: "Wrong amount" })] })] }), _jsx(Button, { size: "sm", type: "submit", disabled: open.isPending, children: "Open dispute" })] })), _jsx(ErrorMessage, { error: open.error ?? decide.error ?? disputes.error }), _jsx("table", { "aria-label": "Disputes", className: "min-w-full text-sm", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: disputes.data?.items.map((d) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: d.dispute_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [d.auth_code, " \u00B7 ", d.reason.replace("_", " ")] }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: formatExactMoney(d.amount, d.currency) }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: d.status === "refunded" ? "good" : d.status === "open" ? "warn" : "neutral", label: d.status }) }), _jsx("td", { className: "px-2 py-1.5 text-right", children: can("cards:manage") && d.status === "open" && (_jsxs("div", { className: "flex justify-end gap-1", children: [_jsx(Button, { size: "sm", "aria-label": `Charge back ${d.dispute_number}`, onClick: () => decide.mutate({ id: d.id, refund: true }), children: "Charge back" }), _jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Reject ${d.dispute_number}`, onClick: () => decide.mutate({ id: d.id, refund: false }), children: "Reject" })] })) })] }, d.id))) }) })] }));
}
/** Cards (Phase 31): issuing, the merchant terminal, fraud blocks and disputes. */
export function CardsPage() {
    const { can } = useAuth();
    const summary = useCardSummary();
    const cards = useCards();
    const authorizations = useAuthorizations();
    const action = useCardAction();
    const live = (cards.data?.items ?? []).filter((c) => c.status !== "cancelled");
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Cards", description: "Debit cards on current accounts, purchases from a synthetic merchant terminal with fraud rules, blocks and their release, disputes and chargebacks \u2014 every amount through the ledger." }), summary.data && (_jsx("dl", { "aria-label": "Card summary", className: "mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5", children: [
                    ["Active cards", summary.data.active_cards],
                    ["Blocked", summary.data.blocked_cards],
                    ["Purchases", summary.data.authorizations],
                    ["Declined", summary.data.declined],
                    ["Open disputes", summary.data.open_disputes],
                ].map(([label, value]) => (_jsxs("div", { className: "rounded-lg border border-slate-200 bg-white p-3", children: [_jsx("dt", { className: "text-xs text-slate-500", children: label }), _jsx("dd", { className: "text-lg font-semibold text-slate-900", children: value })] }, label))) })), _jsxs("div", { className: "space-y-6", children: [_jsxs(Panel, { title: "Cards", subtitle: "Card numbers are synthetic (prefix 9999, Luhn check digit) and shown masked.", children: [can("accounts:transact") && _jsx(IssueForm, {}), _jsx(ErrorMessage, { error: cards.error ?? action.error }), _jsx("table", { "aria-label": "Cards", className: "min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [cards.data?.items.map((c) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: c.card_number }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: [c.account_number, " \u00B7 ", c.product_code, " \u00B7 limit ", formatExactMoney(c.daily_limit, c.currency), " a day", c.blocked_reason && _jsxs("span", { className: "text-rose-700", children: [" \u00B7 ", c.blocked_reason.replace("_", " ")] })] }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: CARD_TONE[c.status], label: c.status }) }), _jsxs("td", { className: "px-2 py-1.5 text-right", children: [c.status === "active" && can("accounts:transact") && (_jsx(Button, { size: "sm", variant: "secondary", "aria-label": `Block card ${c.last4}`, onClick: () => action.mutate({ id: c.id, action: "block", reason: "customer_request" }), children: "Block" })), c.status === "blocked" && can("cards:manage") && (_jsx(Button, { size: "sm", "aria-label": `Release card ${c.last4}`, onClick: () => action.mutate({ id: c.id, action: "unblock" }), children: "Release block" }))] })] }, c.id))), cards.data?.items.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No cards issued yet." }) }))] }) })] }), can("accounts:transact") && live.length > 0 && _jsx(Terminal, { cards: live }), _jsxs(Panel, { title: "Recent purchases", children: [_jsx(ErrorMessage, { error: authorizations.error }), _jsx("table", { "aria-label": "Purchases", className: "min-w-full text-sm", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: authorizations.data?.items.map((a) => (_jsxs("tr", { children: [_jsx("td", { className: "px-2 py-1.5 font-mono text-xs", children: a.auth_code }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: ["\u2022\u2022\u2022\u2022 ", a.card_last4, " \u00B7 ", a.merchant_name, " (", a.merchant_category, ", ", a.merchant_country, ")", a.decline_reason && _jsxs("span", { className: "text-rose-700", children: [" \u00B7 ", a.decline_reason.replace("_", " ")] })] }), _jsx("td", { className: "px-2 py-1.5 text-right tabular-nums", children: formatExactMoney(a.amount, a.currency) }), _jsxs("td", { className: "px-2 py-1.5 text-right text-xs text-slate-500", children: ["score ", a.fraud_score] }), _jsx("td", { className: "px-2 py-1.5", children: _jsx(StatusPill, { compact: true, tone: a.status === "approved" ? "good" : "bad", label: a.status }) })] }, a.id))) }) })] }), _jsx(DisputesPanel, {})] })] }));
}
