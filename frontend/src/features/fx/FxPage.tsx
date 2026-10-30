import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { formatExactMoney } from "@/services/format";
import { useFxDeals, useFxPositions, useFxQuote, useFxRates, useFxRevaluations, useRevalue } from "@/services/fx";

const today = () => new Date().toISOString().slice(0, 10);
const MAJOR_CURRENCIES = ["EUR", "GBP", "JPY", "CHF", "SGD", "CNY", "INR", "AED", "BRL", "ZAR"];

function usd(cents: number): string {
  return formatExactMoney(cents, "USD");
}

function RatesSection({ day }: { day: string }) {
  const rates = useFxRates(day);
  const [all, setAll] = useState(false);
  const shown = (rates.data ?? []).filter((r) => all || MAJOR_CURRENCIES.includes(r.currency));
  return (
    <section aria-label="Exchange rates" className="space-y-2">
      <div className="flex items-center gap-3">
        <h2 className="text-sm font-semibold text-slate-900">Rates on {day}</h2>
        <span className="text-xs text-slate-500">units per US dollar · synthetic</span>
        <label className="flex items-center gap-1.5 text-xs text-slate-600">
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />
          All {rates.data?.length ?? ""} currencies
        </label>
      </div>
      <ErrorMessage error={rates.error} />
      <ul className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4 lg:grid-cols-5">
        {shown.map((r) => (
          <li key={r.currency} className="flex justify-between gap-2">
            <span className="font-mono text-xs text-slate-600">{r.currency}</span>
            <span className="tabular-nums text-slate-900">{Number(r.units_per_usd).toPrecision(6)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function QuoteSection({ day, currencies }: { day: string; currencies: string[] }) {
  const quote = useFxQuote();
  const [sell, setSell] = useState("USD");
  const [buy, setBuy] = useState("EUR");
  const [amount, setAmount] = useState("1000");
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    // Whole units entered; the API takes minor units (assume the common two decimals for USD-like input).
    const digits = new Intl.NumberFormat("en", { style: "currency", currency: sell }).resolvedOptions().maximumFractionDigits ?? 2;
    quote.mutate({ sell_currency: sell, buy_currency: buy, sell_amount: Math.round(Number(amount) * 10 ** digits), rate_date: day });
  };
  const select = (label: string, value: string, onChange: (v: string) => void) => (
    <select aria-label={label} className="rounded-md border border-slate-200 px-2 py-1 text-sm" value={value} onChange={(e) => onChange(e.target.value)}>
      {currencies.map((c) => (
        <option key={c}>{c}</option>
      ))}
    </select>
  );
  return (
    <section aria-label="Quote" className="space-y-2">
      <h2 className="text-sm font-semibold text-slate-900">Quote a conversion</h2>
      <form onSubmit={onSubmit} className="flex flex-wrap items-center gap-2 text-sm">
        <input aria-label="Amount" type="number" min="0" step="any" className="w-28 rounded-md border border-slate-200 px-2 py-1" value={amount} onChange={(e) => setAmount(e.target.value)} required />
        {select("Sell", sell, setSell)}
        <span className="text-slate-500">→</span>
        {select("Buy", buy, setBuy)}
        <Button size="sm" variant="secondary" type="submit" disabled={quote.isPending}>
          Quote
        </Button>
      </form>
      <ErrorMessage error={quote.error} />
      {quote.data && (
        <p role="status" className="text-sm text-slate-700">
          {formatExactMoney(quote.data.sell_amount, quote.data.sell_currency)} buys{" "}
          <strong>{formatExactMoney(quote.data.buy_amount, quote.data.buy_currency)}</strong> at{" "}
          {Number(quote.data.customer_rate).toPrecision(6)} (mid {Number(quote.data.mid_rate).toPrecision(6)}, margin{" "}
          {quote.data.margin_bps / 100} %)
        </p>
      )}
    </section>
  );
}

function PositionsSection({ day }: { day: string }) {
  const { can } = useAuth();
  const positions = useFxPositions(day);
  const runs = useFxRevaluations();
  const deals = useFxDeals();
  const revalue = useRevalue();
  const p = positions.data;
  return (
    <>
      <section aria-label="Currency positions" className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-sm font-semibold text-slate-900">Open currency positions</h2>
          {can("fx:manage") && (
            <Button size="sm" disabled={revalue.isPending} onClick={() => revalue.mutate(day)}>
              Revalue as of {day}
            </Button>
          )}
        </div>
        <ErrorMessage error={positions.error ?? revalue.error} />
        {p && (
          <>
            <dl className="grid grid-cols-3 gap-3 text-sm">
              <div>
                <dt className="text-xs text-slate-500">Value of positions</dt>
                <dd className="font-semibold tabular-nums">{usd(p.total_value_usd)}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">Booked by revaluation</dt>
                <dd className="tabular-nums">{usd(p.booked_usd)}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">Not yet booked</dt>
                <dd role="status" aria-label="Unbooked FX result" className={`tabular-nums ${p.unbooked_usd < 0 ? "text-rose-700" : "text-emerald-700"}`}>
                  {usd(p.unbooked_usd)}
                </dd>
              </div>
            </dl>
            {p.positions.length === 0 ? (
              <p className="text-sm text-slate-500">No conversions yet: no open positions.</p>
            ) : (
              <table aria-label="Positions" className="min-w-full text-sm">
                <thead className="text-left text-xs text-slate-500">
                  <tr>
                    <th className="py-1 pr-4">Currency</th>
                    <th className="py-1 pr-4 text-right">Position (long +)</th>
                    <th className="py-1 pr-4 text-right">Rate</th>
                    <th className="py-1 text-right">Value in USD</th>
                  </tr>
                </thead>
                <tbody>
                  {p.positions.map((row) => (
                    <tr key={row.currency}>
                      <td className="py-1 pr-4 font-mono text-xs">{row.currency}</td>
                      <td className="py-1 pr-4 text-right tabular-nums">{formatExactMoney(row.position, row.currency)}</td>
                      <td className="py-1 pr-4 text-right tabular-nums">{Number(row.units_per_usd).toPrecision(6)}</td>
                      <td className="py-1 text-right tabular-nums">{usd(row.value_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </section>
      <section aria-label="Revaluations" className="space-y-1">
        <h2 className="text-sm font-semibold text-slate-900">Revaluations</h2>
        <ErrorMessage error={runs.error} />
        <ul className="text-xs text-slate-600">
          {runs.data?.items.map((r) => (
            <li key={r.id}>
              #{r.run_number} as of {r.as_of}: posted {usd(r.posted)} (positions worth {usd(r.total_value)})
            </li>
          ))}
          {runs.data?.items.length === 0 && <li>None yet.</li>}
        </ul>
      </section>
      <section aria-label="Conversions" className="space-y-1">
        <h2 className="text-sm font-semibold text-slate-900">Recent conversions</h2>
        <ErrorMessage error={deals.error} />
        <ul className="text-xs text-slate-600">
          {deals.data?.items.map((d) => (
            <li key={d.id}>
              <span className="font-mono">{d.deal_number}</span> {d.rate_date}: {formatExactMoney(d.sell_amount, d.sell_currency)} →{" "}
              {formatExactMoney(d.buy_amount, d.buy_currency)} at {Number(d.customer_rate).toPrecision(6)} ({d.purpose}, {d.reference})
            </li>
          ))}
          {deals.data?.items.length === 0 && <li>None yet.</li>}
        </ul>
      </section>
    </>
  );
}

export function FxPage() {
  const { can } = useAuth();
  const [day, setDay] = useState(today);
  const rates = useFxRates(day);
  const currencies = (rates.data ?? []).map((r) => r.currency);
  return (
    <>
      <PageHeader
        title="Foreign Exchange"
        description="Synthetic daily rates, quotes and the bank's open currency positions. Payments to an account in another currency convert at release; revaluation books the positions' value in US dollars."
      />
      <div className="mb-4 flex items-center gap-2 text-sm">
        <label htmlFor="fx-day" className="text-xs font-medium text-slate-600">
          Date
        </label>
        <input id="fx-day" type="date" className="rounded-md border border-slate-200 px-2 py-1" value={day} onChange={(e) => e.target.value && setDay(e.target.value)} />
      </div>
      <div className="space-y-6">
        <RatesSection day={day} />
        {currencies.length > 0 && <QuoteSection day={day} currencies={currencies} />}
        {can("ledger:read") && <PositionsSection day={day} />}
      </div>
    </>
  );
}
