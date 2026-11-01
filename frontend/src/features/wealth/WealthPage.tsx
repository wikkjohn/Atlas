import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { formatExactMoney, humanize } from "@/services/format";
import {
  WEALTH_PAGE,
  useClosePortfolio,
  useDistribute,
  useDistributions,
  useOpenPortfolio,
  useOrderAction,
  useOrders,
  usePlaceOrder,
  usePortfolios,
  useRecordProfile,
  useSecurities,
  useValuation,
  useWealthSummary,
  type ProfileRequest,
} from "@/services/wealth";
import type { InvestmentOrder } from "@/types/wealth";

const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const TONE: Record<InvestmentOrder["status"], Tone> = {
  placed: "warn",
  awaiting_approval: "warn",
  executed: "good",
  rejected: "neutral",
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-0.5 text-slate-600">
      {label}
      {children}
    </label>
  );
}

/** Newer/older paging for a list served newest first, `WEALTH_PAGE` rows at a time. */
function Pager({ label, offset, total, onChange }: { label: string; offset: number; total: number; onChange: (offset: number) => void }) {
  if (total <= WEALTH_PAGE) return null;
  return (
    <nav aria-label={label} className="mt-2 flex items-center justify-end gap-2 text-xs text-slate-600">
      <span>
        {offset + 1}–{Math.min(offset + WEALTH_PAGE, total)} of {total}
      </span>
      <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => onChange(Math.max(offset - WEALTH_PAGE, 0))}>
        Newer
      </Button>
      <Button size="sm" variant="secondary" disabled={offset + WEALTH_PAGE >= total} onClick={() => onChange(offset + WEALTH_PAGE)}>
        Older
      </Button>
    </nav>
  );
}

function SecuritiesPanel() {
  const securities = useSecurities();
  return (
    <Panel title="Securities" subtitle="Synthetic securities at today's price. Risk runs from 1 (lowest) to 7; complex products need an informed investor.">
      <ErrorMessage error={securities.error} />
      <table aria-label="Securities" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {securities.data?.map((s) => (
            <tr key={s.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{s.code}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {s.name} · {humanize(s.asset_class)}
                {s.complex && " · complex"}
              </td>
              <td className="px-2 py-1.5 text-xs">Risk {s.risk_level}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(s.price, s.currency)}</td>
              <td className="px-2 py-1.5 text-right text-xs text-slate-600">{s.income_bps ? `${(s.income_bps / 100).toFixed(2)} % income` : "no income"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

const PROFILE: ProfileRequest = { customer_number: "", objective: "balanced", horizon_years: 10, knowledge: "basic", loss_capacity: "medium" };

function SuitabilityPanel() {
  const record = useRecordProfile();
  const [form, setForm] = useState(PROFILE);
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    record.mutate({ ...form, customer_number: form.customer_number.trim().toUpperCase() });
  };
  return (
    <Panel title="Suitability" subtitle="The questionnaire gives a risk profile from 1 to 7, valid for a year: the objective's level, capped by a short horizon, a limited capacity for loss and no investment knowledge.">
      <form aria-label="Suitability assessment" onSubmit={onSubmit} className="flex flex-wrap items-end gap-2 text-xs">
        <Field label="Customer">
          <input aria-label="Customer number" required className={`w-36 ${INPUT}`} value={form.customer_number} onChange={(e) => setForm({ ...form, customer_number: e.target.value })} />
        </Field>
        <Field label="Objective">
          <select aria-label="Objective" className={INPUT} value={form.objective} onChange={(e) => setForm({ ...form, objective: e.target.value as ProfileRequest["objective"] })}>
            {["preservation", "income", "balanced", "growth"].map((v) => (
              <option key={v} value={v}>
                {humanize(v)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Horizon (years)">
          <input aria-label="Horizon" type="number" min={0} max={50} className={`w-20 ${INPUT}`} value={form.horizon_years} onChange={(e) => setForm({ ...form, horizon_years: Number(e.target.value) })} />
        </Field>
        <Field label="Knowledge">
          <select aria-label="Knowledge" className={INPUT} value={form.knowledge} onChange={(e) => setForm({ ...form, knowledge: e.target.value as ProfileRequest["knowledge"] })}>
            {["none", "basic", "informed", "expert"].map((v) => (
              <option key={v} value={v}>
                {humanize(v)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Capacity for loss">
          <select aria-label="Capacity for loss" className={INPUT} value={form.loss_capacity} onChange={(e) => setForm({ ...form, loss_capacity: e.target.value as ProfileRequest["loss_capacity"] })}>
            {["low", "medium", "high"].map((v) => (
              <option key={v} value={v}>
                {humanize(v)}
              </option>
            ))}
          </select>
        </Field>
        <Button size="sm" type="submit" disabled={record.isPending}>
          Record profile
        </Button>
        <ErrorMessage error={record.error} />
      </form>
      {record.data && (
        <p role="status" className="mt-2 text-xs text-slate-700">
          Risk profile {record.data.risk_profile}, valid until {record.data.expires_on}.
        </p>
      )}
    </Panel>
  );
}

function PortfoliosPanel({ selected, onSelect }: { selected: string | null; onSelect: (number: string) => void }) {
  const { can } = useAuth();
  const [offset, setOffset] = useState(0);
  const portfolios = usePortfolios(offset);
  const open = useOpenPortfolio();
  const close = useClosePortfolio();
  const valuation = useValuation(selected);
  const [account, setAccount] = useState("");
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    open.mutate(account.trim().toUpperCase(), { onSuccess: (p) => { setAccount(""); onSelect(p.portfolio_number); } });
  };
  const v = valuation.data;
  return (
    <Panel title="Portfolios" subtitle="Custody accounts. Holdings are kept off the bank's balance sheet; the linked bank account pays for purchases and receives sales and income.">
      {can("wealth:advise") && (
        <form aria-label="Open a portfolio" onSubmit={onSubmit} className="mb-3 flex flex-wrap items-end gap-2 text-xs">
          <Field label="Paid from account">
            <input aria-label="Portfolio account" required className={`w-40 ${INPUT}`} value={account} onChange={(e) => setAccount(e.target.value)} />
          </Field>
          <Button size="sm" type="submit" disabled={open.isPending}>
            Open portfolio
          </Button>
          <ErrorMessage error={open.error} />
        </form>
      )}
      <ErrorMessage error={portfolios.error ?? close.error} />
      <table aria-label="Portfolios" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {portfolios.data?.items.map((p) => (
            <tr key={p.id} className={p.portfolio_number === selected ? "bg-slate-50" : undefined}>
              <td className="px-2 py-1.5 font-mono text-xs">{p.portfolio_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {p.customer_name} ({p.customer_number}) · {p.account_number} · {p.currency} · {p.risk_profile ? `risk profile ${p.risk_profile}` : "no current profile"}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={p.status === "open" ? "good" : "neutral"} label={p.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                <div className="flex justify-end gap-1">
                  <Button size="sm" variant="secondary" aria-label={`View ${p.portfolio_number}`} onClick={() => onSelect(p.portfolio_number)}>
                    View
                  </Button>
                  {p.status === "open" && can("wealth:advise") && (
                    <Button size="sm" variant="secondary" aria-label={`Close ${p.portfolio_number}`} onClick={() => close.mutate(p.portfolio_number)}>
                      Close
                    </Button>
                  )}
                </div>
              </td>
            </tr>
          ))}
          {portfolios.data && portfolios.data.items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No portfolios yet.</td>
            </tr>
          )}
        </tbody>
      </table>
      <Pager label="Portfolio pages" offset={offset} total={portfolios.data?.total ?? 0} onChange={setOffset} />
      {v && (
        <section aria-label={`Valuation of ${v.portfolio_number}`} className="mt-4 rounded-md border border-slate-200 p-3">
          <h3 className="text-sm font-semibold text-slate-800">
            {v.portfolio_number} on {v.as_of}: {formatExactMoney(v.value, v.currency)} ({v.gain >= 0 ? "+" : ""}
            {formatExactMoney(v.gain, v.currency)} on cost) · cash {formatExactMoney(v.cash, v.currency)}
          </h3>
          <table aria-label="Holdings" className="mt-2 min-w-full text-sm">
            <tbody className="divide-y divide-slate-100">
              {v.holdings.map((h) => (
                <tr key={h.security_code}>
                  <td className="px-2 py-1.5 font-mono text-xs">{h.security_code}</td>
                  <td className="px-2 py-1.5 text-xs text-slate-600">
                    {h.units} units at {formatExactMoney(h.price, h.price_currency)} · risk {h.risk_level}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(h.value, v.currency)}</td>
                  <td className={`px-2 py-1.5 text-right text-xs tabular-nums ${h.gain >= 0 ? "text-emerald-700" : "text-rose-700"}`}>{formatExactMoney(h.gain, v.currency)}</td>
                </tr>
              ))}
              {v.holdings.length === 0 && (
                <tr>
                  <td className="px-2 py-3 text-center text-xs text-slate-500">No holdings.</td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      )}
    </Panel>
  );
}

function OrdersPanel({ selected }: { selected: string | null }) {
  const { can } = useAuth();
  const securities = useSecurities();
  const [offset, setOffset] = useState(0);
  const orders = useOrders(offset);
  const place = usePlaceOrder();
  const action = useOrderAction();
  const [form, setForm] = useState({ portfolio: "", security: "", side: "buy" as "buy" | "sell", units: "" });
  const portfolio = form.portfolio || selected || "";
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    place.mutate(
      { portfolio_number: portfolio.trim().toUpperCase(), security_code: form.security, side: form.side, units: Number(form.units) },
      { onSuccess: () => setForm({ ...form, units: "" }) },
    );
  };
  const items = orders.data?.items ?? [];
  return (
    <Panel title="Orders" subtitle="A buy is checked against the customer's risk profile. A sell or a suitable buy is executed at today's price; an unsuitable one waits for someone else to approve it at the client's insistence, or reject it.">
      {can("wealth:advise") && (
        <form aria-label="Place an order" onSubmit={onSubmit} className="mb-3 flex flex-wrap items-end gap-2 text-xs">
          <Field label="Portfolio">
            <input aria-label="Order portfolio" required className={`w-36 ${INPUT}`} value={portfolio} onChange={(e) => setForm({ ...form, portfolio: e.target.value })} />
          </Field>
          <Field label="Security">
            <select aria-label="Security" required className={INPUT} value={form.security} onChange={(e) => setForm({ ...form, security: e.target.value })}>
              <option value="">Choose…</option>
              {securities.data?.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.code} · risk {s.risk_level}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Side">
            <select aria-label="Side" className={INPUT} value={form.side} onChange={(e) => setForm({ ...form, side: e.target.value as "buy" | "sell" })}>
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
            </select>
          </Field>
          <Field label="Units">
            <input aria-label="Units" required inputMode="numeric" className={`w-24 ${INPUT}`} value={form.units} onChange={(e) => setForm({ ...form, units: e.target.value })} />
          </Field>
          <Button size="sm" type="submit" disabled={place.isPending}>
            Place order
          </Button>
          <ErrorMessage error={place.error} />
        </form>
      )}
      <ErrorMessage error={orders.error ?? action.error} />
      <table aria-label="Orders" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {items.map((o) => (
            <tr key={o.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{o.order_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {o.portfolio_number} · {o.side} {o.units} {o.security_code} at {formatExactMoney(o.price, o.price_currency)} · fee {formatExactMoney(o.fee, o.currency)}
                {o.reasons.length > 0 && ` · ${o.reasons.map((r) => r.message).join(" ")}`}
                {o.note && ` · ${o.note}`}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(o.amount, o.currency)}</td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={TONE[o.status]} label={humanize(o.status)} />
              </td>
              <td className="px-2 py-1.5 text-right">
                <div className="flex justify-end gap-1">
                  {o.status === "awaiting_approval" && can("wealth:approve") && (
                    <>
                      <Button size="sm" aria-label={`Approve ${o.order_number}`} onClick={() => action.mutate({ id: o.id, action: "approve" })}>
                        Approve
                      </Button>
                      <Button size="sm" variant="secondary" aria-label={`Reject ${o.order_number}`} onClick={() => action.mutate({ id: o.id, action: "reject" })}>
                        Reject
                      </Button>
                    </>
                  )}
                  {o.status === "placed" && can("wealth:advise") && (
                    <Button size="sm" aria-label={`Release ${o.order_number}`} onClick={() => action.mutate({ id: o.id, action: "release" })}>
                      Release
                    </Button>
                  )}
                </div>
              </td>
            </tr>
          ))}
          {orders.data && items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No orders yet.</td>
            </tr>
          )}
        </tbody>
      </table>
      <Pager label="Order pages" offset={offset} total={orders.data?.total ?? 0} onChange={setOffset} />
    </Panel>
  );
}

function IncomePanel() {
  const { can } = useAuth();
  const securities = useSecurities();
  const distributions = useDistributions();
  const distribute = useDistribute();
  const [code, setCode] = useState("");
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    distribute.mutate(code);
  };
  return (
    <Panel title="Income" subtitle="Custody pays half a year's income at today's price to every holder, into each portfolio's account in its currency; once per security and day.">
      {can("wealth:custody") && (
        <form aria-label="Pay income" onSubmit={onSubmit} className="mb-3 flex flex-wrap items-end gap-2 text-xs">
          <Field label="Security">
            <select aria-label="Income security" required className={INPUT} value={code} onChange={(e) => setCode(e.target.value)}>
              <option value="">Choose…</option>
              {securities.data
                ?.filter((s) => s.income_bps > 0)
                .map((s) => (
                  <option key={s.code} value={s.code}>
                    {s.code}
                  </option>
                ))}
            </select>
          </Field>
          <Button size="sm" type="submit" disabled={distribute.isPending}>
            Pay holders
          </Button>
          <ErrorMessage error={distribute.error} />
        </form>
      )}
      <ErrorMessage error={distributions.error} />
      <table aria-label="Income distributions" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {distributions.data?.items.map((d) => (
            <tr key={d.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{d.distribution_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {d.security_code} on {d.record_date} · {formatExactMoney(d.income_per_unit, d.currency)} a unit
              </td>
              <td className="px-2 py-1.5 text-right text-xs">{d.holders} holders</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

/** Wealth and investments (Phase 43): securities, suitability, portfolios, orders and income. */
export function WealthPage() {
  const summary = useWealthSummary();
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="Wealth" description="Synthetic securities, suitability assessments, portfolios held in custody, orders checked against the customer's risk profile, and income paid to holders." />
      {summary.data && (
        <dl aria-label="Wealth summary" className="mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
          {(
            [
              ["Open portfolios", summary.data.portfolios],
              ["Awaiting approval", summary.data.awaiting_approval],
              ["Waiting for release", summary.data.placed],
              ["Executed orders", summary.data.executed],
              ["Profiles recorded", summary.data.profiles],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="rounded-lg border border-slate-200 bg-white p-3">
              <dt className="text-xs text-slate-500">{label}</dt>
              <dd className="text-lg font-semibold text-slate-900">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="flex flex-col gap-6">
        <SecuritiesPanel />
        <SuitabilityPanel />
        <PortfoliosPanel selected={selected} onSelect={setSelected} />
        <OrdersPanel selected={selected} />
        <IncomePanel />
      </div>
    </>
  );
}
