import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { formatExactMoney, humanize } from "@/services/format";
import {
  OPS_PAGE,
  useBanks,
  useBatches,
  useBulkFiles,
  useCreateOutgoing,
  useDecideBulk,
  useDecideOutgoing,
  useOutgoing,
  usePaymentOpsSummary,
  useReceiveBulk,
  useRecallAction,
  useRecalls,
  useRequestRecall,
  useRunCycle,
} from "@/services/paymentOps";
import { type OutgoingPayment, RECALL_REASONS } from "@/types/paymentOps";

const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const TONE: Record<OutgoingPayment["status"], Tone> = {
  awaiting_approval: "warn",
  pending: "warn",
  in_clearing: "warn",
  settled: "good",
  returned: "bad",
  rejected: "neutral",
  recalled: "neutral",
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-0.5 text-slate-600">
      {label}
      {children}
    </label>
  );
}

const EMPTY = { account: "", name: "", bank: "", beneficiary: "", amount: "", reference: "" };

function OutgoingForm() {
  const banks = useBanks();
  const create = useCreateOutgoing();
  const [form, setForm] = useState(EMPTY);
  const set = (key: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate(
      {
        account_number: form.account.trim(),
        beneficiary_name: form.name,
        beneficiary_bank: form.bank,
        beneficiary_account: form.beneficiary.trim(),
        amount_major: Number(form.amount),
        reference: form.reference,
      },
      { onSuccess: () => setForm(EMPTY) },
    );
  };
  return (
    <form aria-label="Pay another bank" onSubmit={onSubmit} className="mb-3 flex flex-wrap items-end gap-2 text-xs">
      <Field label="From account">
        <input aria-label="From account" required className={`w-40 ${INPUT}`} value={form.account} onChange={set("account")} />
      </Field>
      <Field label="Beneficiary">
        <input aria-label="Beneficiary name" required className={`w-40 ${INPUT}`} value={form.name} onChange={set("name")} />
      </Field>
      <Field label="Bank">
        <select aria-label="Beneficiary bank" required className={INPUT} value={form.bank} onChange={set("bank")}>
          <option value="">Choose…</option>
          {banks.data?.map((b) => (
            <option key={b.code} value={b.code}>
              {b.code} · {b.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Account (14 digits)">
        <input aria-label="Beneficiary account" required inputMode="numeric" className={`w-36 ${INPUT}`} value={form.beneficiary} onChange={set("beneficiary")} />
      </Field>
      <Field label="Amount">
        <input aria-label="Amount" required inputMode="decimal" className={`w-28 ${INPUT}`} value={form.amount} onChange={set("amount")} />
      </Field>
      <Field label="Reference">
        <input aria-label="Reference" className={`w-32 ${INPUT}`} value={form.reference} onChange={set("reference")} />
      </Field>
      <Button size="sm" type="submit" disabled={create.isPending}>
        Send
      </Button>
      <ErrorMessage error={create.error} />
    </form>
  );
}

/** Newer/older paging for a list served newest first, `OPS_PAGE` rows at a time. */
function Pager({ label, offset, total, onChange }: { label: string; offset: number; total: number; onChange: (offset: number) => void }) {
  if (total <= OPS_PAGE) return null;
  return (
    <nav aria-label={label} className="mt-2 flex items-center justify-end gap-2 text-xs text-slate-600">
      <span>
        {offset + 1}–{Math.min(offset + OPS_PAGE, total)} of {total}
      </span>
      <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => onChange(Math.max(offset - OPS_PAGE, 0))}>
        Newer
      </Button>
      <Button size="sm" variant="secondary" disabled={offset + OPS_PAGE >= total} onClick={() => onChange(offset + OPS_PAGE)}>
        Older
      </Button>
    </nav>
  );
}

function OutgoingPanel() {
  const { can } = useAuth();
  const [offset, setOffset] = useState(0);
  const outgoing = useOutgoing(offset);
  const decide = useDecideOutgoing();
  const items = outgoing.data?.items ?? [];
  const total = outgoing.data?.total ?? 0;
  return (
    <Panel title="Outgoing payments" subtitle="Payments to other (synthetic) banks. High value waits for someone else's approval; every payment then waits for the next clearing cycle.">
      {can("accounts:transact") && <OutgoingForm />}
      <ErrorMessage error={outgoing.error ?? decide.error} />
      <table aria-label="Outgoing payments" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {items.map((p) => (
            <tr key={p.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{p.payment_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {p.account_number} → {p.beneficiary_name} ({p.beneficiary_bank} {p.beneficiary_account}) · {p.reference}
                {p.return_code && ` · ${p.return_code}: ${p.reason}`}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(p.amount, p.currency)}</td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={TONE[p.status]} label={humanize(p.status)} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {p.status === "awaiting_approval" && can("payments:approve") && (
                  <div className="flex justify-end gap-1">
                    <Button size="sm" aria-label={`Approve ${p.payment_number}`} onClick={() => decide.mutate({ id: p.id, approve: true })}>
                      Approve
                    </Button>
                    <Button size="sm" variant="secondary" aria-label={`Reject ${p.payment_number}`} onClick={() => decide.mutate({ id: p.id, approve: false })}>
                      Reject
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
          {outgoing.data && items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No outgoing payments yet.</td>
            </tr>
          )}
        </tbody>
      </table>
      <Pager label="Payment pages" offset={offset} total={total} onChange={setOffset} />
    </Panel>
  );
}

function ClearingPanel() {
  const { can } = useAuth();
  const batches = useBatches();
  const run = useRunCycle();
  const [currency, setCurrency] = useState("");
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    run.mutate(currency.trim());
  };
  return (
    <Panel title="Clearing" subtitle="A cycle puts a currency's pending payments in a batch, debits each payer into clearing suspense, then settles: payments to accounts the beneficiary bank has closed come back (AC04), the rest are paid out of the bank's cash.">
      {can("payments:operate") && (
        <form aria-label="Run a clearing cycle" onSubmit={onSubmit} className="mb-3 flex items-end gap-2 text-xs">
          <Field label="Currency">
            <input aria-label="Cycle currency" required maxLength={3} className={`w-16 ${INPUT}`} value={currency} onChange={(e) => setCurrency(e.target.value)} />
          </Field>
          <Button size="sm" type="submit" disabled={run.isPending}>
            Run cycle
          </Button>
          {run.data && !run.data.batch && <span className="text-slate-500">Nothing pending in that currency.</span>}
          <ErrorMessage error={run.error} />
        </form>
      )}
      <ErrorMessage error={batches.error} />
      <table aria-label="Clearing batches" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {batches.data?.items.map((b) => (
            <tr key={b.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{b.batch_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {b.business_date} · {b.payments} payments · {b.settled_count} settled, {b.returned_count} returned
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(b.total, b.currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function BulkPanel() {
  const { can } = useAuth();
  const [offset, setOffset] = useState(0);
  const files = useBulkFiles(offset);
  const receive = useReceiveBulk();
  const decide = useDecideBulk();
  const [form, setForm] = useState({ account: "", name: "", text: "" });
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    receive.mutate({ account_number: form.account.trim(), file_name: form.name || "bulk", text: form.text }, { onSuccess: () => setForm({ account: "", name: "", text: "" }) });
  };
  return (
    <Panel title="Bulk files" subtitle="Many payments from one account. Every line is checked; someone other than the receiver releases the file.">
      {can("accounts:transact") && (
        <form aria-label="Bulk file" onSubmit={onSubmit} className="mb-3 flex flex-wrap items-end gap-2 text-xs">
          <Field label="Account">
            <input aria-label="Bulk account" required className={`w-40 ${INPUT}`} value={form.account} onChange={(e) => setForm({ ...form, account: e.target.value })} />
          </Field>
          <Field label="File name">
            <input aria-label="File name" className={`w-36 ${INPUT}`} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label="Lines: name, bank, account, amount, reference">
            <textarea aria-label="Lines" required rows={3} className={`w-96 font-mono ${INPUT}`} value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} />
          </Field>
          <Button size="sm" type="submit" disabled={receive.isPending}>
            Receive file
          </Button>
          <ErrorMessage error={receive.error} />
        </form>
      )}
      <ErrorMessage error={files.error ?? decide.error} />
      <table aria-label="Bulk files" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {files.data?.items.map((f) => (
            <tr key={f.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{f.file_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {f.file_name} · {f.account_number} · {f.valid_count} valid, {f.invalid_count} invalid
                {f.lines.find((l) => l.error) && ` (line ${f.lines.find((l) => l.error)?.line}: ${f.lines.find((l) => l.error)?.error})`}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(f.valid_total, f.currency)}</td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={f.status === "released" ? "good" : f.status === "received" ? "warn" : "neutral"} label={f.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {f.status === "received" && can("payments:approve") && (
                  <div className="flex justify-end gap-1">
                    <Button size="sm" aria-label={`Release ${f.file_number}`} onClick={() => decide.mutate({ id: f.id, release: true })}>
                      Release
                    </Button>
                    <Button size="sm" variant="secondary" aria-label={`Reject ${f.file_number}`} onClick={() => decide.mutate({ id: f.id, release: false })}>
                      Reject
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Pager label="Bulk file pages" offset={offset} total={files.data?.total ?? 0} onChange={setOffset} />
    </Panel>
  );
}

function RecallsPanel() {
  const { can } = useAuth();
  const [offset, setOffset] = useState(0);
  const recalls = useRecalls(offset);
  const request = useRequestRecall();
  const action = useRecallAction();
  const [form, setForm] = useState({ payment: "", reason: "DUPL" });
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    request.mutate({ payment_number: form.payment.trim().toUpperCase(), reason_code: form.reason }, { onSuccess: () => setForm({ ...form, payment: "" }) });
  };
  return (
    <Panel title="Recalls" subtitle="Someone other than the requester approves. A payment not yet cleared is cancelled; a settled one is asked back, and the beneficiary's bank returns it within 10 days (duplicates, technical errors), 5 (customer requests) or 3 (fraud) of settlement.">
      {can("accounts:transact") && (
        <form aria-label="Recall a payment" onSubmit={onSubmit} className="mb-3 flex flex-wrap items-end gap-2 text-xs">
          <Field label="Payment">
            <input aria-label="Payment number" required className={`w-36 ${INPUT}`} value={form.payment} onChange={(e) => setForm({ ...form, payment: e.target.value })} />
          </Field>
          <Field label="Reason">
            <select aria-label="Reason" className={INPUT} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })}>
              {Object.entries(RECALL_REASONS).map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          <Button size="sm" type="submit" disabled={request.isPending}>
            Request recall
          </Button>
          <ErrorMessage error={request.error} />
        </form>
      )}
      <ErrorMessage error={recalls.error ?? action.error} />
      <table aria-label="Recalls" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {recalls.data?.items.map((r) => (
            <tr key={r.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{r.recall_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {r.payment_number} · {RECALL_REASONS[r.reason_code]}
                {r.outcome_note && ` · ${r.outcome_note}`}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={r.status === "accepted" ? "good" : r.status === "refused" ? "bad" : r.status === "withdrawn" ? "neutral" : "warn"} label={r.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                <div className="flex justify-end gap-1">
                  {r.status === "requested" && can("payments:approve") && (
                    <>
                      <Button size="sm" aria-label={`Approve ${r.recall_number}`} onClick={() => action.mutate({ id: r.id, action: "approve" })}>
                        Approve
                      </Button>
                      <Button size="sm" variant="secondary" aria-label={`Withdraw ${r.recall_number}`} onClick={() => action.mutate({ id: r.id, action: "withdraw" })}>
                        Withdraw
                      </Button>
                    </>
                  )}
                  {r.status === "sent" && can("payments:operate") && (
                    <Button size="sm" aria-label={`Record answer ${r.recall_number}`} onClick={() => action.mutate({ id: r.id, action: "resolve" })}>
                      Record answer
                    </Button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Pager label="Recall pages" offset={offset} total={recalls.data?.total ?? 0} onChange={setOffset} />
    </Panel>
  );
}

/** Payments operations (Phase 41): payments to other banks, clearing, bulk files and recalls. */
export function PaymentOpsPage() {
  const summary = usePaymentOpsSummary();
  return (
    <>
      <PageHeader title="Payments Operations" description="Payments to accounts at other (synthetic) banks through a simulated clearing system: approvals for high value, clearing cycles with returns, bulk payment files and recalls." />
      {summary.data && (
        <dl aria-label="Payments operations summary" className="mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
          {(
            [
              ["Awaiting approval", summary.data.awaiting_approval],
              ["Waiting for clearing", summary.data.pending],
              ["Returned", summary.data.returned],
              ["Bulk files to release", summary.data.bulk_received],
              ["Open recalls", summary.data.open_recalls],
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
        <OutgoingPanel />
        <ClearingPanel />
        <BulkPanel />
        <RecallsPanel />
      </div>
    </>
  );
}
