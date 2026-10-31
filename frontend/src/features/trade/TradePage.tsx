import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { formatExactMoney, humanize, toMinorUnits } from "@/services/format";
import {
  INSTRUMENTS_PAGE,
  useDecideDemand,
  useDemands,
  useInstrumentAction,
  useInstruments,
  useReceiveDemand,
  useRequestInstrument,
  useTradeSummary,
} from "@/services/trade";
import { DISCREPANCIES, type TradeInstrument } from "@/types/trade";

const TONE: Record<TradeInstrument["status"], Tone> = { requested: "warn", issued: "good", declined: "neutral", paid: "neutral", expired: "neutral" };
const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const KIND = { letter_of_credit: "Letter of credit", guarantee: "Guarantee" } as const;

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-0.5 text-slate-600">
      {label}
      {children}
    </label>
  );
}

const EMPTY = { kind: "letter_of_credit", customer: "", account: "", beneficiary: "", country: "", amount: "", expires: "", purpose: "" };

function RequestForm() {
  const request = useRequestInstrument();
  const [form, setForm] = useState(EMPTY);
  const set = (key: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    request.mutate(
      {
        kind: form.kind,
        customer_number: form.customer.trim(),
        account_number: form.account.trim(),
        beneficiary_name: form.beneficiary,
        beneficiary_country: form.country.trim().toUpperCase(),
        amount_major: Number(form.amount),
        expires_on: form.expires,
        purpose: form.purpose || "Trade",
      },
      { onSuccess: () => setForm(EMPTY) },
    );
  };
  return (
    <form aria-label="Request an instrument" onSubmit={onSubmit} className="mb-3 flex flex-wrap items-end gap-2 text-xs">
      <Field label="Kind">
        <select aria-label="Kind" className={INPUT} value={form.kind} onChange={set("kind")}>
          <option value="letter_of_credit">Letter of credit</option>
          <option value="guarantee">Guarantee</option>
        </select>
      </Field>
      <Field label="Business customer">
        <input aria-label="Business customer" required className={`w-32 ${INPUT}`} value={form.customer} onChange={set("customer")} />
      </Field>
      <Field label="Business account">
        <input aria-label="Business account" required className={`w-40 ${INPUT}`} value={form.account} onChange={set("account")} />
      </Field>
      <Field label="Beneficiary">
        <input aria-label="Beneficiary" required className={`w-44 ${INPUT}`} value={form.beneficiary} onChange={set("beneficiary")} />
      </Field>
      <Field label="Country">
        <input aria-label="Beneficiary country" required maxLength={2} className={`w-14 ${INPUT}`} value={form.country} onChange={set("country")} />
      </Field>
      <Field label="Amount">
        <input aria-label="Amount" required inputMode="decimal" className={`w-28 ${INPUT}`} value={form.amount} onChange={set("amount")} />
      </Field>
      <Field label="Expires">
        <input aria-label="Expires on" type="date" required className={INPUT} value={form.expires} onChange={set("expires")} />
      </Field>
      <Field label="Purpose">
        <input aria-label="Purpose" className={`w-40 ${INPUT}`} value={form.purpose} onChange={set("purpose")} />
      </Field>
      <Button size="sm" type="submit" disabled={request.isPending}>
        Request
      </Button>
      <ErrorMessage error={request.error} />
    </form>
  );
}

function InstrumentDetail({ instrument }: { instrument: TradeInstrument }) {
  const { can } = useAuth();
  const demands = useDemands(instrument.id);
  const receive = useReceiveDemand();
  const decide = useDecideDemand();
  const action = useInstrumentAction();
  const [amount, setAmount] = useState("");
  const [presented, setPresented] = useState("");
  const [discrepancy, setDiscrepancy] = useState("none");
  const isLc = instrument.kind === "letter_of_credit";
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    receive.mutate(
      {
        id: instrument.id,
        amount: toMinorUnits(Number(amount), instrument.currency),
        presented_on: presented,
        discrepancies: isLc && discrepancy !== "none" ? [discrepancy] : [],
      },
      { onSuccess: () => setAmount("") },
    );
  };
  const today = new Date().toISOString().slice(0, 10);
  return (
    <section aria-label={`Instrument ${instrument.instrument_number}`} className="mt-4 rounded-lg border border-slate-200 p-3 text-xs">
      <h3 className="mb-2 text-sm font-semibold text-slate-900">
        {instrument.instrument_number} · {KIND[instrument.kind]} for {instrument.beneficiary_name}
      </h3>
      <p className="mb-2 text-slate-600">
        Margin held {formatExactMoney(instrument.margin, instrument.currency)} ({instrument.margin_bps / 100} %) · beneficiary screened against{" "}
        {instrument.screening_list ? "the synthetic sanctions lists" : "no list"}: clear · expires {instrument.expires_on}
      </p>
      <ErrorMessage error={receive.error ?? decide.error ?? action.error ?? demands.error} />
      {instrument.status === "issued" && can("accounts:transact") && (
        <form aria-label={isLc ? "Present documents" : "Make a claim"} onSubmit={onSubmit} className="flex flex-wrap items-end gap-2">
          <Field label={`Amount (${instrument.currency})`}>
            <input aria-label="Demand amount" required inputMode="decimal" className={`w-28 ${INPUT}`} value={amount} onChange={(e) => setAmount(e.target.value)} />
          </Field>
          <Field label="Presented on">
            <input aria-label="Presented on" type="date" required className={INPUT} value={presented} onChange={(e) => setPresented(e.target.value)} />
          </Field>
          {isLc && (
            <Field label="Discrepancy found">
              <select aria-label="Discrepancy" className={INPUT} value={discrepancy} onChange={(e) => setDiscrepancy(e.target.value)}>
                <option value="none">None: complying</option>
                {DISCREPANCIES.map((d) => (
                  <option key={d} value={d}>
                    {humanize(d)}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Button size="sm" type="submit" disabled={receive.isPending}>
            {isLc ? "Present documents" : "Make claim"}
          </Button>
        </form>
      )}
      {instrument.status === "issued" && instrument.expires_on < today && can("trade:manage") && (
        <Button size="sm" variant="secondary" onClick={() => action.mutate({ id: instrument.id, action: "expire" })}>
          Close as expired
        </Button>
      )}
      <table aria-label="Demands" className="mt-3 min-w-full">
        <tbody className="divide-y divide-slate-100">
          {demands.data?.map((d) => (
            <tr key={d.id}>
              <td className="px-2 py-1 font-mono">{d.demand_number}</td>
              <td className="px-2 py-1 text-slate-600">
                {d.presented_on} · {d.discrepancies.length ? d.discrepancies.map(humanize).join(", ") : "complying"}
                {d.decision_note && ` · ${d.decision_note}`}
              </td>
              <td className="px-2 py-1 text-right tabular-nums">{formatExactMoney(d.amount, instrument.currency)}</td>
              <td className="px-2 py-1">
                <StatusPill compact tone={d.status === "paid" ? "good" : d.status === "pending" ? "warn" : "neutral"} label={d.status} />
              </td>
              <td className="px-2 py-1 text-right">
                {d.status === "pending" && can("trade:manage") && (
                  <div className="flex justify-end gap-1">
                    <Button size="sm" aria-label={`Pay ${d.demand_number}`} onClick={() => decide.mutate({ id: d.id, pay: true })}>
                      {d.discrepancies.length ? "Pay (waived)" : "Pay"}
                    </Button>
                    <Button size="sm" variant="secondary" aria-label={`Reject ${d.demand_number}`} onClick={() => decide.mutate({ id: d.id, pay: false })}>
                      Reject
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

/** Trade finance (Phase 37): letters of credit, guarantees, presentations and claims. */
export function TradePage() {
  const { can } = useAuth();
  const summary = useTradeSummary();
  const [offset, setOffset] = useState(0);
  const instruments = useInstruments(offset);
  const action = useInstrumentAction();
  const [selected, setSelected] = useState<string | null>(null);
  const items = instruments.data?.items ?? [];
  const total = instruments.data?.total ?? 0;
  const chosen = items.find((i) => i.id === selected);
  return (
    <>
      <PageHeader title="Trade Finance" description="Letters of credit and bank guarantees for business customers: beneficiaries screened against the sanctions lists, approval with four-eyes and above US$1m the credit committee, a cash margin held while live, documents checked for discrepancies and claims paid through the ledger." />
      {summary.data && (
        <dl aria-label="Trade summary" className="mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
          {(
            [
              ["Requested", summary.data.requested],
              ["Issued", summary.data.issued],
              ["Demands to check", summary.data.pending_demands],
              ["Paid", summary.data.paid],
              ["Expired", summary.data.expired],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="rounded-lg border border-slate-200 bg-white p-3">
              <dt className="text-xs text-slate-500">{label}</dt>
              <dd className="text-lg font-semibold text-slate-900">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <Panel title="Instruments" subtitle="A credit approver other than the requester approves; above US$1m the credit committee too. Issuing takes the cash margin (20 % for letters of credit, 10 % for guarantees); payment releases it in proportion, expiry releases the rest.">
        {can("accounts:transact") && <RequestForm />}
        <ErrorMessage error={instruments.error ?? action.error} />
        <table aria-label="Instruments" className="min-w-full text-sm">
          <tbody className="divide-y divide-slate-100">
            {items.map((i) => (
              <tr key={i.id}>
                <td className="px-2 py-1.5">
                  <button type="button" aria-label={`Select ${i.instrument_number}`} className="font-mono text-xs text-sky-700 underline" onClick={() => setSelected(i.id)}>
                    {i.instrument_number}
                  </button>
                </td>
                <td className="px-2 py-1.5 text-xs text-slate-600">
                  {i.customer_name} → {i.beneficiary_name} ({i.beneficiary_country}) · {i.purpose} · expires {i.expires_on}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(i.amount, i.currency)}</td>
                <td className="px-2 py-1.5 text-right text-xs tabular-nums text-slate-600">drawn {formatExactMoney(i.drawn, i.currency)}</td>
                <td className="px-2 py-1.5">
                  <StatusPill compact tone={TONE[i.status]} label={i.status === "requested" && i.approved ? "awaiting committee" : i.status} />
                </td>
                <td className="px-2 py-1.5 text-right">
                  {i.status === "requested" && (
                    <div className="flex justify-end gap-1">
                      {!i.approved && can("loans:approve") && (
                        <Button size="sm" aria-label={`Approve ${i.instrument_number}`} onClick={() => action.mutate({ id: i.id, action: "approve" })}>
                          Approve
                        </Button>
                      )}
                      {i.approved && i.needs_committee && !i.committee_approved && can("loans:approve_large") && (
                        <Button size="sm" aria-label={`Committee approve ${i.instrument_number}`} onClick={() => action.mutate({ id: i.id, action: "committee" })}>
                          Committee approve
                        </Button>
                      )}
                      {can("loans:approve") && (
                        <Button size="sm" variant="secondary" aria-label={`Decline ${i.instrument_number}`} onClick={() => action.mutate({ id: i.id, action: "decline" })}>
                          Decline
                        </Button>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {instruments.data && items.length === 0 && (
              <tr>
                <td className="px-2 py-3 text-center text-xs text-slate-500">No instruments yet.</td>
              </tr>
            )}
          </tbody>
        </table>
        {total > INSTRUMENTS_PAGE && (
          <nav aria-label="Instrument pages" className="mt-2 flex items-center justify-end gap-2 text-xs text-slate-600">
            <span>
              {offset + 1}–{Math.min(offset + INSTRUMENTS_PAGE, total)} of {total}
            </span>
            <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(offset - INSTRUMENTS_PAGE, 0))}>
              Newer
            </Button>
            <Button size="sm" variant="secondary" disabled={offset + INSTRUMENTS_PAGE >= total} onClick={() => setOffset(offset + INSTRUMENTS_PAGE)}>
              Older
            </Button>
          </nav>
        )}
        {chosen && <InstrumentDetail instrument={chosen} />}
      </Panel>
    </>
  );
}
