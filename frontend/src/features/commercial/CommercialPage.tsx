import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import {
  useCommercialSummary,
  useCovenantTests,
  useDecideReview,
  useFacilities,
  useFacilityAction,
  useProposeFacility,
  useReviews,
  useSubmitFigures,
  useWaiveBreach,
} from "@/services/commercial";
import { formatExactMoney, humanize, toMinorUnits } from "@/services/format";
import type { Facility } from "@/types/commercial";

const TONE: Record<Facility["status"], Tone> = { proposed: "warn", active: "good", frozen: "bad", declined: "neutral", terminated: "neutral" };
const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const ratio = (centi: number) => `${(centi / 100).toFixed(2)}×`;
const COVENANT_LABEL = { min_dscr: "DSCR at least", max_leverage: "Leverage at most" } as const;

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-0.5 text-slate-600">
      {label}
      {children}
    </label>
  );
}

function ProposeForm() {
  const propose = useProposeFacility();
  const empty = { customer: "", account: "", type: "revolving", limit: "", term: "36", purpose: "Working capital" };
  const [form, setForm] = useState(empty);
  const set = (key: keyof typeof empty) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    // The limit is entered in major units; the API checks it against the account's currency.
    propose.mutate(
      {
        customer_number: form.customer.trim(),
        account_number: form.account.trim(),
        facility_type: form.type,
        credit_limit: Math.round(Number(form.limit) * 100),
        term_months: Number(form.term),
        purpose: form.purpose,
      },
      { onSuccess: () => setForm(empty) },
    );
  };
  return (
    <form aria-label="Propose a facility" onSubmit={onSubmit} className="mb-3 flex flex-wrap items-end gap-2 text-xs">
      <Field label="Business customer">
        <input aria-label="Business customer" required className={`w-32 ${INPUT}`} value={form.customer} onChange={set("customer")} />
      </Field>
      <Field label="Business account">
        <input aria-label="Business account" required className={`w-40 ${INPUT}`} value={form.account} onChange={set("account")} />
      </Field>
      <Field label="Type">
        <select aria-label="Facility type" className={INPUT} value={form.type} onChange={set("type")}>
          <option value="revolving">Revolving credit</option>
          <option value="term_loan">Term loan</option>
        </select>
      </Field>
      <Field label="Limit">
        <input aria-label="Credit limit" required inputMode="decimal" className={`w-28 ${INPUT}`} value={form.limit} onChange={set("limit")} />
      </Field>
      <Field label="Months">
        <input aria-label="Term in months" required inputMode="numeric" className={`w-16 ${INPUT}`} value={form.term} onChange={set("term")} />
      </Field>
      <Field label="Purpose">
        <input aria-label="Purpose" className={`w-36 ${INPUT}`} value={form.purpose} onChange={set("purpose")} />
      </Field>
      <Button size="sm" type="submit" disabled={propose.isPending}>
        Propose
      </Button>
      <ErrorMessage error={propose.error} />
    </form>
  );
}

function FacilityDetail({ facility }: { facility: Facility }) {
  const { can } = useAuth();
  const action = useFacilityAction();
  const figures = useSubmitFigures();
  const waive = useWaiveBreach();
  const tests = useCovenantTests(facility.id);
  const [amount, setAmount] = useState("");
  const [period, setPeriod] = useState("");
  const [ebitda, setEbitda] = useState("");
  const [service, setService] = useState("");
  const [debt, setDebt] = useState("");
  const minor = (value: string) => toMinorUnits(Number(value), facility.currency);
  const move = (kind: "draw" | "repay") => action.mutate({ id: facility.id, action: kind, amount: minor(amount) }, { onSuccess: () => setAmount("") });
  const onFigures = (event: FormEvent) => {
    event.preventDefault();
    figures.mutate({ id: facility.id, period_end: period, ebitda: minor(ebitda), debt_service: minor(service), total_debt: minor(debt) });
  };
  const live = facility.status === "active" || facility.status === "frozen";
  return (
    <section aria-label={`Facility ${facility.facility_number}`} className="mt-4 rounded-lg border border-slate-200 p-3 text-xs">
      <h3 className="mb-2 text-sm font-semibold text-slate-900">
        {facility.facility_number} · {facility.customer_name}
      </h3>
      <p className="mb-2 text-slate-600">
        {facility.covenants.map((c) => `${COVENANT_LABEL[c.kind]} ${ratio(c.threshold_centi)}`).join(" · ")}
        {facility.matures_on && ` · matures ${facility.matures_on}`}
        {facility.draw_block && facility.status !== "proposed" && <span className="text-rose-700"> · cannot draw: {facility.draw_block}</span>}
      </p>
      <ErrorMessage error={action.error ?? figures.error ?? waive.error ?? tests.error} />
      {live && can("accounts:transact") && (
        <div className="flex flex-wrap items-end gap-4">
          <form aria-label="Draw or repay" onSubmit={(e) => e.preventDefault()} className="flex items-end gap-2">
            <Field label={`Amount (${facility.currency})`}>
              <input aria-label="Amount" inputMode="decimal" className={`w-28 ${INPUT}`} value={amount} onChange={(e) => setAmount(e.target.value)} />
            </Field>
            <Button size="sm" type="button" disabled={!amount || action.isPending} onClick={() => move("draw")}>
              Draw
            </Button>
            <Button size="sm" type="button" variant="secondary" disabled={!amount || action.isPending} onClick={() => move("repay")}>
              Repay
            </Button>
          </form>
          <form aria-label="Covenant figures" onSubmit={onFigures} className="flex flex-wrap items-end gap-2">
            <Field label="Year to">
              <input aria-label="Period end" type="date" required className={INPUT} value={period} onChange={(e) => setPeriod(e.target.value)} />
            </Field>
            <Field label="EBITDA">
              <input aria-label="EBITDA" required inputMode="decimal" className={`w-24 ${INPUT}`} value={ebitda} onChange={(e) => setEbitda(e.target.value)} />
            </Field>
            <Field label="Debt service">
              <input aria-label="Debt service" required inputMode="decimal" className={`w-24 ${INPUT}`} value={service} onChange={(e) => setService(e.target.value)} />
            </Field>
            <Field label="Total debt">
              <input aria-label="Total debt" required inputMode="decimal" className={`w-24 ${INPUT}`} value={debt} onChange={(e) => setDebt(e.target.value)} />
            </Field>
            <Button size="sm" type="submit" disabled={figures.isPending}>
              Test covenants
            </Button>
          </form>
          <Button size="sm" variant="secondary" onClick={() => action.mutate({ id: facility.id, action: "reviews" })}>
            Open review
          </Button>
        </div>
      )}
      <table aria-label="Covenant tests" className="mt-3 min-w-full">
        <tbody className="divide-y divide-slate-100">
          {tests.data?.map((t) => (
            <tr key={t.id}>
              <td className="px-2 py-1">{t.period_end}</td>
              <td className="px-2 py-1 text-slate-600">
                {t.results.map((r) => `${humanize(r.kind)} ${ratio(r.actual_centi)} (${r.passed ? "met" : "breached"})`).join(" · ")}
              </td>
              <td className="px-2 py-1">
                <StatusPill compact tone={!t.breached ? "good" : t.waived ? "neutral" : "bad"} label={!t.breached ? "met" : t.waived ? "waived" : "breached"} />
              </td>
              <td className="px-2 py-1 text-right">
                {t.breached && !t.waived && can("loans:approve_large") && (
                  <Button size="sm" aria-label={`Waive ${t.period_end}`} onClick={() => waive.mutate(t.id)}>
                    Waive
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function FacilitiesPanel() {
  const { can } = useAuth();
  const facilities = useFacilities();
  const action = useFacilityAction();
  const [selected, setSelected] = useState<string | null>(null);
  const items = facilities.data?.items ?? [];
  const chosen = items.find((f) => f.id === selected);
  return (
    <Panel title="Facilities" subtitle="A credit approver other than the proposer approves; above US$1m the credit committee too. A covenant breach freezes the facility until the committee waives it; an overdue annual review stops drawdowns.">
      {can("accounts:transact") && <ProposeForm />}
      <ErrorMessage error={facilities.error ?? action.error} />
      <table aria-label="Facilities" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {items.map((f) => (
            <tr key={f.id}>
              <td className="px-2 py-1.5">
                <button type="button" aria-label={`Select ${f.facility_number}`} className="font-mono text-xs text-sky-700 underline" onClick={() => setSelected(f.id)}>
                  {f.facility_number}
                </button>
              </td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {f.customer_name} · {humanize(f.facility_type)} · {(f.annual_rate_bps / 100).toFixed(2)} % · {f.term_months} months
                {f.review_due_on && ` · review ${f.review_due_on}`}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(f.credit_limit, f.currency)}</td>
              <td className="px-2 py-1.5 text-right text-xs tabular-nums text-slate-600">
                drawn {formatExactMoney(f.drawn, f.currency)} · available {formatExactMoney(f.available, f.currency)}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={TONE[f.status]} label={f.status === "proposed" && f.approved ? "awaiting committee" : f.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {f.status === "proposed" && (
                  <div className="flex justify-end gap-1">
                    {!f.approved && can("loans:approve") && (
                      <Button size="sm" aria-label={`Approve ${f.facility_number}`} onClick={() => action.mutate({ id: f.id, action: "approve" })}>
                        Approve
                      </Button>
                    )}
                    {f.approved && f.needs_committee && !f.committee_approved && can("loans:approve_large") && (
                      <Button size="sm" aria-label={`Committee approve ${f.facility_number}`} onClick={() => action.mutate({ id: f.id, action: "committee" })}>
                        Committee approve
                      </Button>
                    )}
                    {can("loans:approve") && (
                      <Button size="sm" variant="secondary" aria-label={`Decline ${f.facility_number}`} onClick={() => action.mutate({ id: f.id, action: "decline" })}>
                        Decline
                      </Button>
                    )}
                  </div>
                )}
              </td>
            </tr>
          ))}
          {facilities.data && items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No facilities yet.</td>
            </tr>
          )}
        </tbody>
      </table>
      {chosen && <FacilityDetail facility={chosen} />}
    </Panel>
  );
}

function ReviewsPanel() {
  const { can } = useAuth();
  const reviews = useReviews();
  const facilities = useFacilities();
  const decide = useDecideReview();
  const numbers = new Map((facilities.data?.items ?? []).map((f) => [f.id, f.facility_number]));
  return (
    <Panel title="Annual reviews" subtitle="Opened from 60 days before a facility's review is due. A credit approver other than the person who opened it renews the facility for a year or terminates it.">
      <ErrorMessage error={reviews.error ?? decide.error} />
      <table aria-label="Reviews" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {reviews.data?.map((r) => (
            <tr key={r.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{r.review_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {numbers.get(r.facility_id) ?? "facility"} · due {r.due_on}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={r.outcome === "renewed" ? "good" : r.outcome ? "neutral" : "warn"} label={r.outcome ?? "open"} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {!r.outcome && can("loans:approve") && (
                  <div className="flex justify-end gap-1">
                    <Button size="sm" aria-label={`Renew ${r.review_number}`} onClick={() => decide.mutate({ id: r.id, renew: true })}>
                      Renew
                    </Button>
                    <Button size="sm" variant="secondary" aria-label={`Terminate ${r.review_number}`} onClick={() => decide.mutate({ id: r.id, renew: false })}>
                      Terminate
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

/** Commercial lending (Phase 35): facilities, drawdowns, covenants and annual reviews. */
export function CommercialPage() {
  const summary = useCommercialSummary();
  return (
    <>
      <PageHeader title="Commercial Lending" description="Term loans and revolving credit for business customers: approval with four-eyes and, above US$1m, the credit committee; drawdowns and repayments through the ledger; covenant tests that freeze a facility on a breach; annual reviews." />
      {summary.data && (
        <dl aria-label="Commercial summary" className="mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
          {(
            [
              ["Proposed", summary.data.proposed],
              ["Active", summary.data.active],
              ["Frozen", summary.data.frozen],
              ["Reviews due", summary.data.reviews_due],
              ["Open reviews", summary.data.open_reviews],
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
        <FacilitiesPanel />
        <ReviewsPanel />
      </div>
    </>
  );
}
