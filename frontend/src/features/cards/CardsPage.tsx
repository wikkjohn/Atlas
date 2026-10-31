import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { formatExactMoney } from "@/services/format";
import {
  useAuthorizations,
  useAuthorize,
  useCardAction,
  useCards,
  useCardSummary,
  useDecideDispute,
  useDisputes,
  useIssueCard,
  useOpenDispute,
} from "@/services/cards";
import type { Card } from "@/types/cards";

const CARD_TONE: Record<Card["status"], Tone> = { active: "good", blocked: "bad", cancelled: "neutral" };
// A few synthetic merchant categories for the terminal (ISO 18245 style codes).
const CATEGORIES: [string, string][] = [
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
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    issue.mutate({ account_number: account.trim(), product_code: product }, { onSuccess: () => setAccount("") });
  };
  return (
    <form aria-label="Issue a card" onSubmit={onSubmit} className="mb-3 flex flex-wrap items-end gap-2 text-xs">
      <label className="flex flex-col gap-0.5 text-slate-600">
        Account
        <input aria-label="Account" required className="w-44 rounded-md border border-slate-200 px-2 py-1" value={account} onChange={(e) => setAccount(e.target.value)} />
      </label>
      <label className="flex flex-col gap-0.5 text-slate-600">
        Product
        <select aria-label="Product" className="rounded-md border border-slate-200 px-2 py-1" value={product} onChange={(e) => setProduct(e.target.value)}>
          <option value="debit-standard">ATLAS Debit</option>
          <option value="debit-premium">ATLAS Debit Premium</option>
        </select>
      </label>
      <Button size="sm" type="submit" disabled={issue.isPending}>
        Issue card
      </Button>
      <ErrorMessage error={issue.error} />
    </form>
  );
}

function Terminal({ cards }: { cards: Card[] }) {
  const authorize = useAuthorize();
  const [cardId, setCardId] = useState("");
  const [merchant, setMerchant] = useState("Corner Grocer");
  const [category, setCategory] = useState("5411");
  const [country, setCountry] = useState("GB");
  const [amount, setAmount] = useState("25.00");
  const card = cards.find((c) => c.id === cardId) ?? cards[0];
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!card) return;
    authorize.mutate({
      cardId: card.id,
      merchant_name: merchant,
      merchant_category: category,
      merchant_country: country.toUpperCase(),
      amount: Math.round(Number(amount) * 100),
    });
  };
  const result = authorize.data;
  return (
    <Panel title="Merchant terminal" subtitle="A synthetic point of sale. Checks: card status and expiry, the daily limit, funds (with any arranged overdraft), then the fraud rules — a score of 70 or more declines the purchase and blocks the card.">
      <form aria-label="Merchant terminal" onSubmit={onSubmit} className="flex flex-wrap items-end gap-2 text-xs">
        <label className="flex flex-col gap-0.5 text-slate-600">
          Card
          <select aria-label="Card" className="rounded-md border border-slate-200 px-2 py-1" value={card?.id ?? ""} onChange={(e) => setCardId(e.target.value)}>
            {cards.map((c) => (
              <option key={c.id} value={c.id}>
                {c.card_number} ({c.currency})
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-0.5 text-slate-600">
          Merchant
          <input aria-label="Merchant" className="w-36 rounded-md border border-slate-200 px-2 py-1" value={merchant} onChange={(e) => setMerchant(e.target.value)} />
        </label>
        <label className="flex flex-col gap-0.5 text-slate-600">
          Category
          <select aria-label="Category" className="rounded-md border border-slate-200 px-2 py-1" value={category} onChange={(e) => setCategory(e.target.value)}>
            {CATEGORIES.map(([code, label]) => (
              <option key={code} value={code}>
                {code} {label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-0.5 text-slate-600">
          Country
          <input aria-label="Merchant country" maxLength={2} className="w-14 rounded-md border border-slate-200 px-2 py-1" value={country} onChange={(e) => setCountry(e.target.value)} />
        </label>
        <label className="flex flex-col gap-0.5 text-slate-600">
          Amount
          <input aria-label="Amount" className="w-24 rounded-md border border-slate-200 px-2 py-1" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </label>
        <Button size="sm" type="submit" disabled={authorize.isPending || !card}>
          Pay
        </Button>
      </form>
      <ErrorMessage error={authorize.error} />
      {result && (
        <p role="status" className={`mt-2 text-sm ${result.status === "approved" ? "text-emerald-700" : "text-rose-700"}`}>
          {result.auth_code}: {result.status}
          {result.decline_reason && ` (${result.decline_reason.replace("_", " ")})`} · fraud score {result.fraud_score}
          {result.fraud_signals.length > 0 && ` · ${result.fraud_signals.join(", ")}`}
        </p>
      )}
    </Panel>
  );
}

function DisputesPanel() {
  const { can } = useAuth();
  const disputes = useDisputes();
  const open = useOpenDispute();
  const decide = useDecideDispute();
  const [code, setCode] = useState("");
  const [reason, setReason] = useState("not_recognised");
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    open.mutate({ auth_code: code.trim(), reason }, { onSuccess: () => setCode("") });
  };
  return (
    <Panel title="Disputes and chargebacks" subtitle="Someone other than the person who opened a dispute decides it. Upheld, the amount is charged back to the account through card settlement.">
      {can("accounts:transact") && (
        <form aria-label="Open a dispute" onSubmit={onSubmit} className="mb-3 flex flex-wrap items-end gap-2 text-xs">
          <label className="flex flex-col gap-0.5 text-slate-600">
            Purchase
            <input aria-label="Authorisation code" required placeholder="AUTH-00000001" className="w-36 rounded-md border border-slate-200 px-2 py-1" value={code} onChange={(e) => setCode(e.target.value)} />
          </label>
          <label className="flex flex-col gap-0.5 text-slate-600">
            Reason
            <select aria-label="Reason" className="rounded-md border border-slate-200 px-2 py-1" value={reason} onChange={(e) => setReason(e.target.value)}>
              <option value="not_recognised">Not recognised</option>
              <option value="not_received">Not received</option>
              <option value="duplicate">Duplicate</option>
              <option value="wrong_amount">Wrong amount</option>
            </select>
          </label>
          <Button size="sm" type="submit" disabled={open.isPending}>
            Open dispute
          </Button>
        </form>
      )}
      <ErrorMessage error={open.error ?? decide.error ?? disputes.error} />
      <table aria-label="Disputes" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {disputes.data?.items.map((d) => (
            <tr key={d.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{d.dispute_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {d.auth_code} · {d.reason.replace("_", " ")}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(d.amount, d.currency)}</td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={d.status === "refunded" ? "good" : d.status === "open" ? "warn" : "neutral"} label={d.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {can("cards:manage") && d.status === "open" && (
                  <div className="flex justify-end gap-1">
                    <Button size="sm" aria-label={`Charge back ${d.dispute_number}`} onClick={() => decide.mutate({ id: d.id, refund: true })}>
                      Charge back
                    </Button>
                    <Button size="sm" variant="secondary" aria-label={`Reject ${d.dispute_number}`} onClick={() => decide.mutate({ id: d.id, refund: false })}>
                      Reject
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

/** Cards (Phase 31): issuing, the merchant terminal, fraud blocks and disputes. */
export function CardsPage() {
  const { can } = useAuth();
  const summary = useCardSummary();
  const cards = useCards();
  const authorizations = useAuthorizations();
  const action = useCardAction();
  const live = (cards.data?.items ?? []).filter((c) => c.status !== "cancelled");
  return (
    <>
      <PageHeader title="Cards" description="Debit cards on current accounts, purchases from a synthetic merchant terminal with fraud rules, blocks and their release, disputes and chargebacks — every amount through the ledger." />
      {summary.data && (
        <dl aria-label="Card summary" className="mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
          {(
            [
              ["Active cards", summary.data.active_cards],
              ["Blocked", summary.data.blocked_cards],
              ["Purchases", summary.data.authorizations],
              ["Declined", summary.data.declined],
              ["Open disputes", summary.data.open_disputes],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="rounded-lg border border-slate-200 bg-white p-3">
              <dt className="text-xs text-slate-500">{label}</dt>
              <dd className="text-lg font-semibold text-slate-900">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="space-y-6">
        <Panel title="Cards" subtitle="Card numbers are synthetic (prefix 9999, Luhn check digit) and shown masked.">
          {can("accounts:transact") && <IssueForm />}
          <ErrorMessage error={cards.error ?? action.error} />
          <table aria-label="Cards" className="min-w-full text-sm">
            <tbody className="divide-y divide-slate-100">
              {cards.data?.items.map((c) => (
                <tr key={c.id}>
                  <td className="px-2 py-1.5 font-mono text-xs">{c.card_number}</td>
                  <td className="px-2 py-1.5 text-xs text-slate-600">
                    {c.account_number} · {c.product_code} · limit {formatExactMoney(c.daily_limit, c.currency)} a day
                    {c.blocked_reason && <span className="text-rose-700"> · {c.blocked_reason.replace("_", " ")}</span>}
                  </td>
                  <td className="px-2 py-1.5">
                    <StatusPill compact tone={CARD_TONE[c.status]} label={c.status} />
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    {c.status === "active" && can("accounts:transact") && (
                      <Button size="sm" variant="secondary" aria-label={`Block card ${c.last4}`} onClick={() => action.mutate({ id: c.id, action: "block", reason: "customer_request" })}>
                        Block
                      </Button>
                    )}
                    {c.status === "blocked" && can("cards:manage") && (
                      <Button size="sm" aria-label={`Release card ${c.last4}`} onClick={() => action.mutate({ id: c.id, action: "unblock" })}>
                        Release block
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
              {cards.data?.items.length === 0 && (
                <tr>
                  <td className="px-2 py-3 text-center text-xs text-slate-500">No cards issued yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </Panel>
        {can("accounts:transact") && live.length > 0 && <Terminal cards={live} />}
        <Panel title="Recent purchases">
          <ErrorMessage error={authorizations.error} />
          <table aria-label="Purchases" className="min-w-full text-sm">
            <tbody className="divide-y divide-slate-100">
              {authorizations.data?.items.map((a) => (
                <tr key={a.id}>
                  <td className="px-2 py-1.5 font-mono text-xs">{a.auth_code}</td>
                  <td className="px-2 py-1.5 text-xs text-slate-600">
                    •••• {a.card_last4} · {a.merchant_name} ({a.merchant_category}, {a.merchant_country})
                    {a.decline_reason && <span className="text-rose-700"> · {a.decline_reason.replace("_", " ")}</span>}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(a.amount, a.currency)}</td>
                  <td className="px-2 py-1.5 text-right text-xs text-slate-500">score {a.fraud_score}</td>
                  <td className="px-2 py-1.5">
                    <StatusPill compact tone={a.status === "approved" ? "good" : "bad"} label={a.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <DisputesPanel />
      </div>
    </>
  );
}
