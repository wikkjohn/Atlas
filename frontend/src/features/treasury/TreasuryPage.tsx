import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { formatExactMoney, humanize } from "@/services/format";
import {
  TREASURY_PAGE,
  useBookDeal,
  useBookFxTrade,
  useCounterparties,
  useDealAction,
  useDeals,
  useFxDesk,
  useFxTradeAction,
  useFxTrades,
  useLiquidity,
  useSetCounterpartyLimit,
  useTreasurySummary,
} from "@/services/treasury";
import type { Counterparty, Deal } from "@/types/treasury";

const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const TONE: Record<Deal["status"], Tone> = { booked: "warn", settled: "good", matured: "neutral", cancelled: "neutral" };
const usd = (dollars: number) => formatExactMoney(dollars * 100, "USD");
const percent = (bps: number | null) => (bps === null ? "—" : `${(bps / 100).toFixed(0)} %`);

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-0.5 text-slate-600">
      {label}
      {children}
    </label>
  );
}

/** Newer/Older paging once a list has more than one page (PR #30 review). */
function Pager({ label, offset, total, onChange }: { label: string; offset: number; total: number; onChange: (offset: number) => void }) {
  if (total <= TREASURY_PAGE) return null;
  return (
    <nav aria-label={label} className="mt-2 flex items-center justify-end gap-2 text-xs text-slate-600">
      <span>
        {offset + 1}–{Math.min(offset + TREASURY_PAGE, total)} of {total}
      </span>
      <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => onChange(Math.max(offset - TREASURY_PAGE, 0))}>
        Newer
      </Button>
      <Button size="sm" variant="secondary" disabled={offset + TREASURY_PAGE >= total} onClick={() => onChange(offset + TREASURY_PAGE)}>
        Older
      </Button>
    </nav>
  );
}

function CounterpartySelect({ value, onChange, parties, label }: { value: string; onChange: (v: string) => void; parties: Counterparty[]; label: string }) {
  return (
    <select aria-label={label} required className={INPUT} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Choose…</option>
      {parties.map((p) => (
        <option key={p.code} value={p.code}>
          {p.code} ({p.rating})
        </option>
      ))}
    </select>
  );
}

const EMPTY_DEAL = { kind: "placement", counterparty: "", currency: "", principal: "", rate: "", tenor: "30" };

function BookDealForm({ parties }: { parties: Counterparty[] }) {
  const book = useBookDeal();
  const [form, setForm] = useState(EMPTY_DEAL);
  const set = (key: keyof typeof EMPTY_DEAL) => (value: string) => setForm({ ...form, [key]: value });
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    book.mutate(
      {
        kind: form.kind,
        counterparty_code: form.counterparty,
        currency: form.currency.trim(),
        principal_major: Number(form.principal),
        rate_percent: Number(form.rate),
        tenor_days: Number(form.tenor),
      },
      { onSuccess: () => setForm(EMPTY_DEAL) },
    );
  };
  return (
    <form aria-label="Book a deal" onSubmit={onSubmit} className="mb-3 flex flex-wrap items-end gap-2 text-xs">
      <Field label="Kind">
        <select aria-label="Kind" className={INPUT} value={form.kind} onChange={(e) => set("kind")(e.target.value)}>
          <option value="placement">Placement (we lend)</option>
          <option value="borrowing">Borrowing (we take)</option>
        </select>
      </Field>
      <Field label="Counterparty">
        <CounterpartySelect label="Counterparty" value={form.counterparty} onChange={set("counterparty")} parties={parties} />
      </Field>
      <Field label="Currency">
        <input aria-label="Currency" required maxLength={3} className={`w-16 ${INPUT}`} value={form.currency} onChange={(e) => set("currency")(e.target.value)} />
      </Field>
      <Field label="Principal">
        <input aria-label="Principal" required inputMode="decimal" className={`w-32 ${INPUT}`} value={form.principal} onChange={(e) => set("principal")(e.target.value)} />
      </Field>
      <Field label="Rate (% a year)">
        <input aria-label="Rate" required inputMode="decimal" className={`w-20 ${INPUT}`} value={form.rate} onChange={(e) => set("rate")(e.target.value)} />
      </Field>
      <Field label="Tenor (days)">
        <input aria-label="Tenor" required inputMode="numeric" className={`w-20 ${INPUT}`} value={form.tenor} onChange={(e) => set("tenor")(e.target.value)} />
      </Field>
      <Button size="sm" type="submit" disabled={book.isPending}>
        Book
      </Button>
      <ErrorMessage error={book.error} />
    </form>
  );
}

function DealsPanel({ parties }: { parties: Counterparty[] }) {
  const { can } = useAuth();
  const [offset, setOffset] = useState(0);
  const deals = useDeals(offset);
  const action = useDealAction();
  const today = new Date().toISOString().slice(0, 10);
  const items = deals.data?.items ?? [];
  return (
    <Panel title="Money-market deals" subtitle="Placements need an investment-grade counterparty (BBB- or better) within its limit, and must leave the currency's 30-day liquidity coverage at 100 % or more. Back office, not the dealer, confirms and settles.">
      {can("treasury:deal") && <BookDealForm parties={parties} />}
      <ErrorMessage error={deals.error ?? action.error} />
      <table aria-label="Deals" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {items.map((d) => (
            <tr key={d.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{d.deal_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {humanize(d.kind)} · {d.counterparty_code} · {(d.rate_bps / 100).toFixed(2)} % ACT/{d.day_basis} · matures {d.maturity_date}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(d.principal, d.currency)}</td>
              <td className="px-2 py-1.5 text-right text-xs tabular-nums text-slate-600">interest {formatExactMoney(d.interest, d.currency)}</td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={TONE[d.status]} label={d.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                <div className="flex justify-end gap-1">
                  {d.status === "booked" && can("treasury:confirm") && (
                    <Button size="sm" aria-label={`Confirm ${d.deal_number}`} onClick={() => action.mutate({ id: d.id, action: "confirm" })}>
                      Confirm
                    </Button>
                  )}
                  {d.status === "booked" && can("treasury:deal") && (
                    <Button size="sm" variant="secondary" aria-label={`Cancel ${d.deal_number}`} onClick={() => action.mutate({ id: d.id, action: "cancel" })}>
                      Cancel
                    </Button>
                  )}
                  {d.status === "settled" && d.maturity_date <= today && can("treasury:confirm") && (
                    <Button size="sm" aria-label={`Mature ${d.deal_number}`} onClick={() => action.mutate({ id: d.id, action: "mature" })}>
                      Settle maturity
                    </Button>
                  )}
                </div>
              </td>
            </tr>
          ))}
          {deals.data && items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No deals yet.</td>
            </tr>
          )}
        </tbody>
      </table>
      <Pager label="Deal pages" offset={offset} total={deals.data?.total ?? 0} onChange={setOffset} />
    </Panel>
  );
}

function CounterpartiesPanel({ parties }: { parties: Counterparty[] }) {
  const { can } = useAuth();
  const setLimit = useSetCounterpartyLimit();
  const [code, setCode] = useState("");
  const [limit, setLimitValue] = useState("");
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    setLimit.mutate({ code, limit_usd: Math.round(Number(limit)) }, { onSuccess: () => setLimitValue("") });
  };
  return (
    <Panel title="Counterparties" subtitle="Synthetic banks. Exposure is outstanding placements at today's rates.">
      <table aria-label="Counterparties" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {parties.map((p) => (
            <tr key={p.code}>
              <td className="px-2 py-1.5 font-mono text-xs">{p.code}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {p.name} · {p.country_code} · {p.rating}
                {!p.investment_grade && " (borrowing only)"}
              </td>
              <td className="px-2 py-1.5 text-right text-xs tabular-nums">
                {usd(p.exposure_usd)} of {usd(p.limit_usd)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {can("treasury:limits") && (
        <form aria-label="Counterparty limit" onSubmit={onSubmit} className="mt-3 flex flex-wrap items-end gap-2 text-xs">
          <Field label="Counterparty">
            <CounterpartySelect label="Limit counterparty" value={code} onChange={setCode} parties={parties} />
          </Field>
          <Field label="Limit (US$)">
            <input aria-label="Limit" required inputMode="numeric" className={`w-32 ${INPUT}`} value={limit} onChange={(e) => setLimitValue(e.target.value)} />
          </Field>
          <Button size="sm" type="submit" disabled={setLimit.isPending}>
            Set limit
          </Button>
          <ErrorMessage error={setLimit.error} />
        </form>
      )}
    </Panel>
  );
}

function LiquidityPanel() {
  const liquidity = useLiquidity();
  const data = liquidity.data;
  return (
    <Panel
      title="Liquidity"
      subtitle={data ? `Next ${data.horizon_days} days: cash and placements coming back, against borrowings falling due and a ${data.run_off_bps / 100} % run-off of customer deposits. Minimum ${data.minimum_bps / 100} %.` : undefined}
    >
      <ErrorMessage error={liquidity.error} />
      <table aria-label="Liquidity" className="min-w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-500">
            <th className="px-2 py-1">Currency</th>
            <th className="px-2 py-1 text-right">Liquid</th>
            <th className="px-2 py-1 text-right">Stressed outflow</th>
            <th className="px-2 py-1 text-right">Coverage</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {data?.currencies.map((r) => (
            <tr key={r.currency}>
              <td className="px-2 py-1.5 font-mono text-xs">{r.currency}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(r.liquid, r.currency)}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(r.stressed_outflow, r.currency)}</td>
              <td className="px-2 py-1.5 text-right">
                <StatusPill compact tone={r.below_minimum ? "bad" : "good"} label={percent(r.coverage_bps)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function FxDeskPanel({ parties }: { parties: Counterparty[] }) {
  const { can } = useAuth();
  const desk = useFxDesk();
  const [tradeOffset, setTradeOffset] = useState(0);
  const trades = useFxTrades(tradeOffset);
  const book = useBookFxTrade();
  const action = useFxTradeAction();
  const [form, setForm] = useState({ counterparty: "", sell: "", buy: "USD", amount: "" });
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    book.mutate(
      { counterparty_code: form.counterparty, sell_currency: form.sell.trim(), buy_currency: form.buy.trim(), sell_major: Number(form.amount) },
      { onSuccess: () => setForm({ ...form, amount: "" }) },
    );
  };
  return (
    <Panel title="FX desk" subtitle="Open positions against their net open position limits. A spot trade at the day's mid rate may only reduce a long position.">
      <ErrorMessage error={desk.error ?? trades.error ?? action.error} />
      <table aria-label="Positions" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {desk.data?.positions.map((p) => (
            <tr key={p.currency}>
              <td className="px-2 py-1.5 font-mono text-xs">{p.currency}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(p.position, p.currency)}</td>
              <td className="px-2 py-1.5 text-right text-xs tabular-nums text-slate-600">
                {formatExactMoney(p.value_usd, "USD")} of {usd(p.limit_usd)}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={p.over_limit ? "bad" : "good"} label={p.over_limit ? "over limit" : "within"} />
              </td>
            </tr>
          ))}
          {desk.data && desk.data.positions.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No open positions.</td>
            </tr>
          )}
        </tbody>
      </table>
      {can("treasury:deal") && (
        <form aria-label="Square a position" onSubmit={onSubmit} className="mt-3 flex flex-wrap items-end gap-2 text-xs">
          <Field label="Counterparty">
            <CounterpartySelect label="Trade counterparty" value={form.counterparty} onChange={(v) => setForm({ ...form, counterparty: v })} parties={parties} />
          </Field>
          <Field label="Sell">
            <input aria-label="Sell currency" required maxLength={3} className={`w-16 ${INPUT}`} value={form.sell} onChange={(e) => setForm({ ...form, sell: e.target.value })} />
          </Field>
          <Field label="Buy">
            <input aria-label="Buy currency" required maxLength={3} className={`w-16 ${INPUT}`} value={form.buy} onChange={(e) => setForm({ ...form, buy: e.target.value })} />
          </Field>
          <Field label="Amount sold">
            <input aria-label="Amount sold" required inputMode="decimal" className={`w-32 ${INPUT}`} value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          </Field>
          <Button size="sm" type="submit" disabled={book.isPending}>
            Book trade
          </Button>
          <ErrorMessage error={book.error} />
        </form>
      )}
      <table aria-label="FX trades" className="mt-3 min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {trades.data?.items.map((t) => (
            <tr key={t.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{t.trade_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                sold {formatExactMoney(t.sell_amount, t.sell_currency)} for {formatExactMoney(t.buy_amount, t.buy_currency)} · {t.counterparty_code} · mid {t.mid_rate}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={t.status === "settled" ? "good" : t.status === "booked" ? "warn" : "neutral"} label={t.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {t.status === "booked" && (
                  <div className="flex justify-end gap-1">
                    {can("treasury:confirm") && (
                      <Button size="sm" aria-label={`Confirm ${t.trade_number}`} onClick={() => action.mutate({ id: t.id, action: "confirm" })}>
                        Confirm
                      </Button>
                    )}
                    {can("treasury:deal") && (
                      <Button size="sm" variant="secondary" aria-label={`Cancel ${t.trade_number}`} onClick={() => action.mutate({ id: t.id, action: "cancel" })}>
                        Cancel
                      </Button>
                    )}
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Pager label="FX trade pages" offset={tradeOffset} total={trades.data?.total ?? 0} onChange={setTradeOffset} />
    </Panel>
  );
}

/** Treasury and markets (Phase 39): interbank deals, counterparties, liquidity and the FX desk. */
export function TreasuryPage() {
  const summary = useTreasurySummary();
  const counterparties = useCounterparties();
  const parties = counterparties.data ?? [];
  return (
    <>
      <PageHeader title="Treasury" description="Interbank placements and borrowings with synthetic counterparty banks, booked by a dealer and settled by back office; the bank's 30-day liquidity by currency; and the FX desk's open positions against their limits." />
      {summary.data && (
        <dl aria-label="Treasury summary" className="mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          {(
            [
              ["Deals to confirm", summary.data.booked],
              ["Placements out", summary.data.placements],
              ["Borrowings in", summary.data.borrowings],
              ["FX trades to confirm", summary.data.fx_trades_booked],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="rounded-lg border border-slate-200 bg-white p-3">
              <dt className="text-xs text-slate-500">{label}</dt>
              <dd className="text-lg font-semibold text-slate-900">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <ErrorMessage error={counterparties.error} />
      <div className="flex flex-col gap-6">
        <DealsPanel parties={parties} />
        <LiquidityPanel />
        <FxDeskPanel parties={parties} />
        <CounterpartiesPanel parties={parties} />
      </div>
    </>
  );
}
