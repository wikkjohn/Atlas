import { useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { useArrears, useCollect, useCollectionsSummary, useDecidePlan, useDecideRecovery, usePlans, useProposePlan, useRecordRecovery, useRecoveries, useWrittenOff } from "@/services/collections";
import { formatExactMoney, humanize, toMinorUnits } from "@/services/format";
import type { PaymentPlan, Recovery } from "@/types/collections";

const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const PLAN_TONE: Record<PaymentPlan["status"], Tone> = { proposed: "warn", active: "good", completed: "good", broken: "bad", rejected: "neutral" };
const RECOVERY_TONE: Record<Recovery["status"], Tone> = { recorded: "warn", posted: "good", rejected: "neutral" };

function ArrearsPanel() {
  const { can } = useAuth();
  const arrears = useArrears();
  const propose = useProposePlan();
  const [interval, setPlanInterval] = useState("14");
  return (
    <Panel title="Loans in arrears" subtitle="Active loans with overdue instalments, most days past due first. A payment plan spreads the arrears into catch-up payments, one per overdue instalment.">
      {can("loans:service") && (
        <label className="mb-2 flex items-center gap-2 text-xs text-slate-600">
          Plan payments every
          <input aria-label="Plan interval days" type="number" min={7} max={31} className={`w-16 ${INPUT}`} value={interval} onChange={(e) => setPlanInterval(e.target.value)} />
          days
        </label>
      )}
      <ErrorMessage error={arrears.error ?? propose.error} />
      <table aria-label="Arrears" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {arrears.data?.map((r) => (
            <tr key={r.loan_number}>
              <td className="px-2 py-1.5 font-mono text-xs">{r.loan_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {r.customer_name} ({r.customer_number}) · {r.days_past_due} days past due · {r.instalments} instalments · {humanize(r.bucket)}
                {r.plan_number && ` · ${r.plan_number} ${r.plan_status}`}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(r.amount, r.currency)}</td>
              <td className="px-2 py-1.5 text-right">
                {!r.plan_number && can("loans:service") && (
                  <Button size="sm" aria-label={`Propose plan for ${r.loan_number}`} onClick={() => propose.mutate({ loan_number: r.loan_number, interval_days: Number(interval) })}>
                    Propose plan
                  </Button>
                )}
              </td>
            </tr>
          ))}
          {arrears.data && arrears.data.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No loans in arrears.</td>
            </tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}

function PlansPanel() {
  const { can } = useAuth();
  const plans = usePlans();
  const decide = useDecidePlan();
  const collect = useCollect();
  return (
    <Panel title="Payment plans" subtitle="A plan is activated by someone other than its proposer (loans:approve). Each payment settles the oldest overdue instalment from the borrower's account; two missed payments break the plan. While a plan is active the loan cannot be written off.">
      {can("loans:service") && (
        <div className="mb-3 flex items-center gap-2 text-xs">
          <Button size="sm" variant="secondary" onClick={() => collect.mutate()} disabled={collect.isPending}>
            Take payments due
          </Button>
          {collect.data && (
            <span role="status">
              {collect.data.paid} paid, {collect.data.missed} missed, {collect.data.completed} completed, {collect.data.broken} broken (as of {collect.data.as_of})
            </span>
          )}
          <ErrorMessage error={collect.error} />
        </div>
      )}
      <ErrorMessage error={plans.error ?? decide.error} />
      <table aria-label="Plans" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {plans.data?.items.map((p) => (
            <tr key={p.id} className="align-top">
              <td className="px-2 py-1.5 font-mono text-xs">{p.plan_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {p.loan_number} · {formatExactMoney(p.arrears_amount, p.currency)} over {p.payments} payments every {p.interval_days} days
                <div>
                  {p.schedule.map((s) => (
                    <span key={s.n} className="mr-3">
                      {s.due} {s.status}
                    </span>
                  ))}
                </div>
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={PLAN_TONE[p.status]} label={p.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {p.status === "proposed" && can("loans:approve") && (
                  <div className="flex justify-end gap-1">
                    <Button size="sm" aria-label={`Approve ${p.plan_number}`} onClick={() => decide.mutate({ id: p.id, approve: true })}>
                      Approve
                    </Button>
                    <Button size="sm" variant="secondary" aria-label={`Reject ${p.plan_number}`} onClick={() => decide.mutate({ id: p.id, approve: false })}>
                      Reject
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
          {plans.data && plans.data.items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No payment plans yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}

function RecoveriesPanel() {
  const { can } = useAuth();
  const writtenOff = useWrittenOff();
  const recoveries = useRecoveries();
  const record = useRecordRecovery();
  const decide = useDecideRecovery();
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [kinds, setKinds] = useState<Record<string, string>>({});
  return (
    <Panel title="Written off and recoveries" subtitle="Money recovered on written-off loans is booked to loan loss recoveries, never more than was written off. A borrower's payment or an agency's remittance posts at once; a debt sale waits for the credit committee (loans:approve_large).">
      <ErrorMessage error={writtenOff.error ?? record.error} />
      <table aria-label="Written-off loans" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {writtenOff.data?.map((w) => (
            <tr key={w.loan_number}>
              <td className="px-2 py-1.5 font-mono text-xs">{w.loan_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {w.customer_name} · written off {w.written_off_on} · {formatExactMoney(w.written_off, w.currency)}, recovered {formatExactMoney(w.recovered, w.currency)}
              </td>
              <td className="px-2 py-1.5 text-right">
                {w.remaining > 0 && can("loans:service") && (
                  <div className="flex justify-end gap-1 text-xs">
                    <select aria-label={`Recovery kind for ${w.loan_number}`} className={INPUT} value={kinds[w.loan_number] ?? "payment"} onChange={(e) => setKinds({ ...kinds, [w.loan_number]: e.target.value })}>
                      {["payment", "agency", "debt_sale"].map((k) => (
                        <option key={k} value={k}>
                          {humanize(k)}
                        </option>
                      ))}
                    </select>
                    <input aria-label={`Recovery amount for ${w.loan_number}`} type="number" min={0.01} step="0.01" className={`w-24 ${INPUT}`} value={amounts[w.loan_number] ?? ""} onChange={(e) => setAmounts({ ...amounts, [w.loan_number]: e.target.value })} />
                    <Button
                      size="sm"
                      aria-label={`Record recovery on ${w.loan_number}`}
                      disabled={!amounts[w.loan_number]}
                      onClick={() => record.mutate({ loan_number: w.loan_number, kind: kinds[w.loan_number] ?? "payment", amount: toMinorUnits(Number(amounts[w.loan_number]), w.currency) })}
                    >
                      Record
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
          {writtenOff.data && writtenOff.data.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No written-off loans.</td>
            </tr>
          )}
        </tbody>
      </table>
      <ErrorMessage error={recoveries.error ?? decide.error} />
      <table aria-label="Recoveries" className="mt-4 min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {recoveries.data?.items.map((r) => (
            <tr key={r.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{r.recovery_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {r.loan_number} · {humanize(r.kind)}
                {r.entry_number && ` · ${r.entry_number}`}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(r.amount, r.currency)}</td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={RECOVERY_TONE[r.status]} label={r.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {r.status === "recorded" && can("loans:approve_large") && (
                  <div className="flex justify-end gap-1">
                    <Button size="sm" aria-label={`Approve ${r.recovery_number}`} onClick={() => decide.mutate({ id: r.id, approve: true })}>
                      Approve
                    </Button>
                    <Button size="sm" variant="secondary" aria-label={`Reject ${r.recovery_number}`} onClick={() => decide.mutate({ id: r.id, approve: false })}>
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

/** Collections and recoveries (Phase 53): payment plans and recoveries on written-off loans. */
export function CollectionsPage() {
  const summary = useCollectionsSummary();
  return (
    <>
      <PageHeader title="Collections" description="Loans in arrears, payment plans approved by a second person, and recoveries on written-off loans. Extends the WF-0004 collections process." />
      {summary.data && (
        <dl aria-label="Collections summary" className="mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
          {(
            [
              ["Plans to approve", summary.data.plans_proposed],
              ["Plans active", summary.data.plans_active],
              ["Plans broken", summary.data.plans_broken],
              ["Debt sales to approve", summary.data.debt_sales_to_approve],
              ["Loans written off", summary.data.loans_written_off],
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
        <ArrearsPanel />
        <PlansPanel />
        <RecoveriesPanel />
      </div>
    </>
  );
}
