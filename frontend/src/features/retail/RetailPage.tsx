import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { formatExactMoney } from "@/services/format";
import {
  useCancelStandingOrder,
  useCreateStandingOrder,
  useMonthEnds,
  useRetailProducts,
  useRetailSummary,
  useRunMonthEnd,
  useStandingOrders,
  useStatement,
  useStatements,
  useUpdateProduct,
} from "@/services/retail";
import type { RetailProduct, StandingOrder } from "@/types/retail";

const percent = (bps: number) => `${(bps / 100).toFixed(2)} %`;
const usd = (cents: number) => formatExactMoney(cents, "USD");
const ORDER_TONE: Record<StandingOrder["status"], Tone> = { active: "good", cancelled: "neutral", ended: "neutral", failed: "bad" };

function ProductRow({ product, manage }: { product: RetailProduct; manage: boolean }) {
  const update = useUpdateProduct();
  const [editing, setEditing] = useState(false);
  const [credit, setCredit] = useState(String(product.credit_rate_bps));
  const [overdraft, setOverdraft] = useState(String(product.overdraft_rate_bps));
  const [fee, setFee] = useState(String(product.monthly_fee_usd_cents));
  const save = () =>
    update.mutate(
      {
        account_type: product.account_type,
        credit_rate_bps: Number(credit),
        overdraft_rate_bps: Number(overdraft),
        monthly_fee_usd_cents: Number(fee),
      },
      { onSuccess: () => setEditing(false) },
    );
  const input = (label: string, value: string, set: (v: string) => void) => (
    <input aria-label={`${label} of ${product.name}`} className="w-20 rounded border border-slate-200 px-1 py-0.5 text-xs" value={value} onChange={(e) => set(e.target.value)} />
  );
  return (
    <tr>
      <td className="px-2 py-1.5">
        <div className="font-medium text-slate-900">{product.name}</div>
        <div className="text-xs text-slate-500">{product.account_type.replace("_", " ")} accounts</div>
      </td>
      <td className="px-2 py-1.5 text-right tabular-nums">{editing ? input("Credit interest (bps)", credit, setCredit) : percent(product.credit_rate_bps)}</td>
      <td className="px-2 py-1.5 text-right tabular-nums">{editing ? input("Overdraft interest (bps)", overdraft, setOverdraft) : percent(product.overdraft_rate_bps)}</td>
      <td className="px-2 py-1.5 text-right tabular-nums">{editing ? input("Monthly fee (US cents)", fee, setFee) : usd(product.monthly_fee_usd_cents)}</td>
      <td className="px-2 py-1.5 text-right tabular-nums">{product.max_overdraft_usd ? usd(product.max_overdraft_usd * 100) : "None"}</td>
      <td className="px-2 py-1.5 text-right">
        {manage &&
          (editing ? (
            <Button size="sm" onClick={save} disabled={update.isPending}>
              Save
            </Button>
          ) : (
            <Button size="sm" variant="secondary" aria-label={`Edit ${product.name}`} onClick={() => setEditing(true)}>
              Edit
            </Button>
          ))}
        <ErrorMessage error={update.error} />
      </td>
    </tr>
  );
}

function ProductsPanel() {
  const { can } = useAuth();
  const products = useRetailProducts();
  return (
    <Panel
      title="Products"
      subtitle="Interest a year on credit and overdrawn balances, the monthly fee and the largest arranged overdraft. Dollar amounts are converted to each account's currency at the synthetic FX anchor rates."
    >
      <ErrorMessage error={products.error} />
      <table aria-label="Retail products" className="min-w-full text-sm">
        <thead className="text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
          <tr>
            <th className="px-2 py-1">Product</th>
            <th className="px-2 py-1 text-right">Credit interest</th>
            <th className="px-2 py-1 text-right">Overdraft interest</th>
            <th className="px-2 py-1 text-right">Monthly fee</th>
            <th className="px-2 py-1 text-right">Overdraft up to</th>
            <th className="px-2 py-1" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {products.data?.map((p) => (
            <ProductRow key={p.account_type} product={p} manage={can("retail:manage")} />
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function StandingOrdersPanel() {
  const { can } = useAuth();
  const orders = useStandingOrders();
  const create = useCreateStandingOrder();
  const cancel = useCancelStandingOrder();
  const [payer, setPayer] = useState("");
  const [payee, setPayee] = useState("");
  const [amount, setAmount] = useState("");
  const [frequency, setFrequency] = useState<"weekly" | "monthly">("monthly");
  const [first, setFirst] = useState("");
  const [reference, setReference] = useState("");
  const transact = can("accounts:transact");
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate(
      {
        debtor_account_number: payer.trim(),
        creditor_account_number: payee.trim(),
        amount: Math.round(Number(amount) * 100),
        frequency,
        first_date: first,
        reference,
      },
      { onSuccess: () => setAmount("") },
    );
  };
  return (
    <Panel title="Standing orders" subtitle="Paid by the daily standing-order job on business days of the payer's country; three missed payments in a row stop an order.">
      {transact && (
        <form aria-label="New standing order" onSubmit={onSubmit} className="mb-3 flex flex-wrap items-end gap-2 text-xs">
          {(
            [
              ["Payer account", payer, setPayer, "w-40"],
              ["Payee account", payee, setPayee, "w-40"],
              ["Amount", amount, setAmount, "w-24"],
              ["Reference", reference, setReference, "w-32"],
            ] as const
          ).map(([label, value, set, width]) => (
            <label key={label} className="flex flex-col gap-0.5 text-slate-600">
              {label}
              <input aria-label={label} required className={`${width} rounded-md border border-slate-200 px-2 py-1`} value={value} onChange={(e) => set(e.target.value)} />
            </label>
          ))}
          <label className="flex flex-col gap-0.5 text-slate-600">
            Frequency
            <select aria-label="Frequency" className="rounded-md border border-slate-200 px-2 py-1" value={frequency} onChange={(e) => setFrequency(e.target.value as "weekly" | "monthly")}>
              <option value="monthly">Monthly</option>
              <option value="weekly">Weekly</option>
            </select>
          </label>
          <label className="flex flex-col gap-0.5 text-slate-600">
            First payment
            <input aria-label="First payment" type="date" required className="rounded-md border border-slate-200 px-2 py-1" value={first} onChange={(e) => setFirst(e.target.value)} />
          </label>
          <Button size="sm" type="submit" disabled={create.isPending}>
            Set up
          </Button>
        </form>
      )}
      <ErrorMessage error={create.error ?? cancel.error ?? orders.error} />
      <table aria-label="Standing orders" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {orders.data?.items.map((o) => (
            <tr key={o.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{o.order_number}</td>
              <td className="px-2 py-1.5 text-xs">
                <div className="text-slate-900">
                  {o.debtor_account_number} → {o.creditor_account_number}
                </div>
                <div className="text-slate-500">
                  {o.reference} · {o.frequency} · next {o.next_date} · {o.payments_made} paid
                  {o.last_error && <span className="text-rose-700"> · {o.last_error}</span>}
                </div>
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(o.amount, o.currency)}</td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={ORDER_TONE[o.status]} label={o.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {transact && o.status === "active" && (
                  <Button size="sm" variant="secondary" aria-label={`Cancel ${o.order_number}`} disabled={cancel.isPending} onClick={() => cancel.mutate(o.id)}>
                    Cancel
                  </Button>
                )}
              </td>
            </tr>
          ))}
          {orders.data?.items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No standing orders yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}

function StatementView({ id, onClose }: { id: string; onClose: () => void }) {
  const statement = useStatement(id);
  const s = statement.data;
  return (
    <Modal wide title={s ? `Statement ${s.statement_number}` : "Statement"} onClose={onClose}>
      <ErrorMessage error={statement.error} />
      {s && (
        <div className="space-y-3 text-sm">
          <p className="text-slate-600">
            Account {s.account_number} · {s.period_start} to {s.period_end} · opening {formatExactMoney(s.opening_balance, s.currency)} · closing{" "}
            {formatExactMoney(s.closing_balance, s.currency)}
          </p>
          <table aria-label="Statement entries" className="min-w-full text-xs">
            <tbody className="divide-y divide-slate-100">
              {s.entries.map((e) => (
                <tr key={e.entry_number}>
                  <td className="py-1 pr-3 font-mono text-slate-500">{e.date}</td>
                  <td className="py-1 pr-3 text-slate-900">{e.description}</td>
                  <td className={`py-1 pr-3 text-right tabular-nums ${e.amount < 0 ? "text-rose-700" : "text-emerald-700"}`}>{formatExactMoney(e.amount, s.currency)}</td>
                  <td className="py-1 text-right tabular-nums text-slate-600">{formatExactMoney(e.balance, s.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
}

function MonthEndPanel() {
  const { can } = useAuth();
  const runs = useMonthEnds();
  const run = useRunMonthEnd();
  const statements = useStatements();
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Panel title="Month end and statements" subtitle="Month end posts credit interest, overdraft interest and monthly fees on the last day of the month, then issues each account's statement. It runs once per month.">
      {can("retail:manage") && (
        <div className="mb-3 flex items-center gap-2">
          <Button size="sm" onClick={() => run.mutate(null)} disabled={run.isPending}>
            Run month end
          </Button>
          {run.data && <span role="status" className="text-xs text-slate-600">Job #{run.data.job_number} queued for the last complete month.</span>}
        </div>
      )}
      <ErrorMessage error={run.error ?? runs.error ?? statements.error} />
      <table aria-label="Month-end runs" className="mb-4 min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {runs.data?.map((r) => (
            <tr key={r.id}>
              <td className="px-2 py-1.5 font-medium text-slate-900">{r.period_start.slice(0, 7)}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {r.accounts} accounts · {r.entries} postings · {r.statements} statements
              </td>
              <td className="px-2 py-1.5 text-xs text-slate-500">
                {Object.entries(r.totals)
                  .slice(0, 4)
                  .map(([ccy, t]) => `${ccy}: interest ${formatExactMoney(t.interest_paid, ccy)} paid, ${formatExactMoney(t.interest_charged, ccy)} charged, fees ${formatExactMoney(t.fees, ccy)}`)
                  .join(" · ")}
              </td>
            </tr>
          ))}
          {runs.data?.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No month end has run yet.</td>
            </tr>
          )}
        </tbody>
      </table>
      <h3 className="mb-1 text-xs font-medium tracking-wide text-slate-500 uppercase">Recent statements</h3>
      <ul aria-label="Recent statements" className="divide-y divide-slate-100 text-sm">
        {statements.data?.items.map((s) => (
          <li key={s.id} className="flex items-center justify-between gap-3 py-1.5">
            <button type="button" className="font-mono text-xs text-navy-700 hover:underline" onClick={() => setOpen(s.id)}>
              {s.statement_number}
            </button>
            <span className="text-xs text-slate-600">
              {s.account_number} · {s.period_start.slice(0, 7)} · {s.lines} entries
            </span>
            <span className="tabular-nums">{formatExactMoney(s.closing_balance, s.currency)}</span>
          </li>
        ))}
      </ul>
      {open && <StatementView id={open} onClose={() => setOpen(null)} />}
    </Panel>
  );
}

/** Retail banking (Phase 29): products, standing orders, month end and statements. */
export function RetailPage() {
  const summary = useRetailSummary();
  return (
    <>
      <PageHeader
        title="Retail Banking"
        description="Deposit products and their terms, arranged overdrafts, standing orders, and the month end that pays interest, charges fees and issues statements — every amount through the ledger."
      />
      {summary.data && (
        <dl aria-label="Retail summary" className="mb-6 grid grid-cols-3 gap-3 text-sm">
          {(
            [
              ["Arranged overdrafts", summary.data.overdrafts],
              ["Active standing orders", summary.data.active_standing_orders],
              ["Statements issued", summary.data.statements],
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
        <ProductsPanel />
        <StandingOrdersPanel />
        <MonthEndPanel />
      </div>
    </>
  );
}
