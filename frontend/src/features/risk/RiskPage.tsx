import { useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import {
  RISK_PAGE,
  useBreaches,
  useCalculate,
  useDecideRating,
  useDecideRun,
  useObligor,
  useProvisionLines,
  useProvisionRuns,
  useRate,
  useRatings,
  useRiskSummary,
  useSetLimit,
} from "@/services/risk";
import { formatExactMoney } from "@/services/format";
import { bps, type CreditRating, type Obligor, type ProvisionRun } from "@/types/risk";

const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const RATING_TONE: Record<CreditRating["status"], Tone> = { pending: "warn", approved: "good", rejected: "neutral" };
const RUN_TONE: Record<ProvisionRun["status"], Tone> = { calculated: "warn", posted: "good", rejected: "neutral" };
const usd = (dollars: number) => formatExactMoney(dollars * 100, "USD");

/** Newer/older paging, `RISK_PAGE` rows at a time. */
function Pager({ label, offset, total, onChange }: { label: string; offset: number; total: number; onChange: (offset: number) => void }) {
  if (total <= RISK_PAGE) return null;
  return (
    <nav aria-label={label} className="mt-2 flex items-center justify-end gap-2 text-xs text-slate-600">
      <span>
        {offset + 1}–{Math.min(offset + RISK_PAGE, total)} of {total}
      </span>
      <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => onChange(Math.max(offset - RISK_PAGE, 0))}>
        Newer
      </Button>
      <Button size="sm" variant="secondary" disabled={offset + RISK_PAGE >= total} onClick={() => onChange(offset + RISK_PAGE)}>
        Older
      </Button>
    </nav>
  );
}

function ObligorActions({ obligor }: { obligor: Obligor }) {
  const { can } = useAuth();
  const rate = useRate();
  const limit = useSetLimit();
  const [grade, setGrade] = useState("model");
  const [rationale, setRationale] = useState("");
  const [limitUsd, setLimitUsd] = useState(String(obligor.limit_usd));
  return (
    <div className="mt-3 flex flex-col gap-3 text-xs">
      {can("risk:rate") && (
        <form
          aria-label="Rate obligor"
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            rate.mutate({ customer_number: obligor.customer_number, grade: grade === "model" ? null : Number(grade), rationale });
          }}
        >
          <label className="flex flex-col gap-0.5 text-slate-600">
            Grade
            <select aria-label="Grade" className={INPUT} value={grade} onChange={(e) => setGrade(e.target.value)}>
              <option value="model">The model's</option>
              {Array.from({ length: 10 }, (_, i) => i + 1).map((g) => (
                <option key={g} value={g}>
                  {g}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-0.5 text-slate-600">
            Rationale (needed to depart from the model)
            <input aria-label="Rationale" className={`w-72 ${INPUT}`} maxLength={300} value={rationale} onChange={(e) => setRationale(e.target.value)} />
          </label>
          <Button size="sm" type="submit" disabled={rate.isPending}>
            Rate
          </Button>
          {rate.data && (
            <span role="status">
              {rate.data.rating_number}: grade {rate.data.grade}, {rate.data.status}
            </span>
          )}
          <ErrorMessage error={rate.error} />
        </form>
      )}
      {can("risk:approve") && (
        <form
          aria-label="Set limit"
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            limit.mutate({ customer_number: obligor.customer_number, limit_usd: Number(limitUsd), note: "Set on the risk page" });
          }}
        >
          <label className="flex flex-col gap-0.5 text-slate-600">
            Limit (US$)
            <input aria-label="Limit in US dollars" type="number" min={0} className={`w-36 ${INPUT}`} value={limitUsd} onChange={(e) => setLimitUsd(e.target.value)} />
          </label>
          <Button size="sm" type="submit" disabled={limit.isPending}>
            Set limit
          </Button>
          <ErrorMessage error={limit.error} />
        </form>
      )}
    </div>
  );
}

function ObligorPanel() {
  const [input, setInput] = useState("");
  const [number, setNumber] = useState("");
  const obligor = useObligor(number);
  const breaches = useBreaches();
  const view = obligor.data;
  return (
    <Panel title="Obligors" subtitle="Each customer has an internal grade from 1 (strongest) to 10 (in default), each with a one-year probability of default. The model starts from the KYC rating and worsens it for arrears and frozen facilities; a grade departing from it needs a second person's approval. Exposure (loans, mortgages, drawn facilities plus half the undrawn headroom, overdrafts) is measured in US dollars against the obligor's limit.">
      <form
        aria-label="Look up obligor"
        className="mb-3 flex items-end gap-2 text-xs"
        onSubmit={(e) => {
          e.preventDefault();
          setNumber(input.trim().toUpperCase());
        }}
      >
        <label className="flex flex-col gap-0.5 text-slate-600">
          Customer number
          <input aria-label="Customer number" placeholder="CUS-0000001" className={`w-40 ${INPUT}`} value={input} onChange={(e) => setInput(e.target.value)} />
        </label>
        <Button size="sm" type="submit">
          Look up
        </Button>
      </form>
      <ErrorMessage error={obligor.error} />
      {view && (
        <section aria-label="Obligor" className="mb-4 rounded-md border border-slate-200 p-3 text-sm">
          <p className="font-medium text-slate-900">
            {view.name} ({view.customer_number})
          </p>
          <p className="text-xs text-slate-600" aria-label="Obligor grade">
            Grade {view.grade} (PD {bps(view.pd_bps)}) · limit {usd(view.limit_usd)} ({view.limit_source === "set" ? "set" : "by grade"}) · exposure {usd(view.exposure_usd)}
            {view.excess_usd > 0 && ` · ${usd(view.excess_usd)} over the limit`}
          </p>
          <table aria-label="Exposures" className="mt-2 min-w-full text-xs">
            <tbody className="divide-y divide-slate-100">
              {view.exposures.map((e) => (
                <tr key={`${e.type}-${e.reference}`}>
                  <td className="px-2 py-1 font-mono">{e.reference}</td>
                  <td className="px-2 py-1 text-slate-600">
                    {e.type}
                    {e.days_past_due > 0 && ` · ${e.days_past_due} days past due`}
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums">{formatExactMoney(e.ead, e.currency)}</td>
                </tr>
              ))}
              {view.exposures.length === 0 && (
                <tr>
                  <td className="px-2 py-2 text-center text-slate-500">No credit exposure.</td>
                </tr>
              )}
            </tbody>
          </table>
          <ObligorActions key={view.customer_number} obligor={view} />
        </section>
      )}
      <h3 className="mb-1 text-xs font-semibold text-slate-700">Limit breaches</h3>
      <ErrorMessage error={breaches.error} />
      <table aria-label="Limit breaches" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {breaches.data?.map((b) => (
            <tr key={b.customer_number}>
              <td className="px-2 py-1.5 font-mono text-xs">{b.customer_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {b.name} · grade {b.grade} · limit {usd(b.limit_usd)}
              </td>
              <td className="px-2 py-1.5 text-right text-xs tabular-nums">{usd(b.excess_usd)} over</td>
            </tr>
          ))}
          {breaches.data && breaches.data.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No obligor is over their limit.</td>
            </tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}

function RatingsPanel() {
  const { can } = useAuth();
  const [offset, setOffset] = useState(0);
  const ratings = useRatings(offset);
  const decide = useDecideRating();
  return (
    <Panel title="Ratings" subtitle="A rating lasts a year. One that departs from the model's grade waits for someone other than its rater.">
      <ErrorMessage error={ratings.error ?? decide.error} />
      <table aria-label="Ratings" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {ratings.data?.items.map((r) => (
            <tr key={r.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{r.rating_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {r.customer_name} ({r.customer_number}) · grade {r.grade}
                {r.grade !== r.suggested_grade && ` (model ${r.suggested_grade})`} · {r.rationale}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={RATING_TONE[r.status]} label={r.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {r.status === "pending" && can("risk:approve") && (
                  <div className="flex justify-end gap-1">
                    <Button size="sm" aria-label={`Approve ${r.rating_number}`} onClick={() => decide.mutate({ id: r.id, approve: true })}>
                      Approve
                    </Button>
                    <Button size="sm" variant="secondary" aria-label={`Reject ${r.rating_number}`} onClick={() => decide.mutate({ id: r.id, approve: false })}>
                      Reject
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
          {ratings.data && ratings.data.items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No ratings yet.</td>
            </tr>
          )}
        </tbody>
      </table>
      <Pager label="Rating pages" offset={offset} total={ratings.data?.total ?? 0} onChange={setOffset} />
    </Panel>
  );
}

function RunLines({ runId }: { runId: string }) {
  const lines = useProvisionLines(runId);
  return (
    <>
      <ErrorMessage error={lines.error} />
      <table aria-label="Provision lines" className="mt-2 min-w-full text-xs">
        <tbody className="divide-y divide-slate-100">
          {lines.data?.items.map((l) => (
            <tr key={`${l.exposure_type}-${l.reference}`}>
              <td className="px-2 py-1 font-mono">{l.reference}</td>
              <td className="px-2 py-1 text-slate-600">
                {l.exposure_type} · stage {l.stage} · grade {l.grade} · PD {bps(l.pd_bps)} · LGD {bps(l.lgd_bps)}
                {l.days_past_due > 0 && ` · ${l.days_past_due} days past due`}
              </td>
              <td className="px-2 py-1 text-right tabular-nums">{formatExactMoney(l.ecl, l.currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function ProvisionsPanel() {
  const { can } = useAuth();
  const [offset, setOffset] = useState(0);
  const runs = useProvisionRuns(offset);
  const calculate = useCalculate();
  const decide = useDecideRun();
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Panel title="Expected credit loss" subtitle="A run measures the loan book's ECL as EAD × PD × LGD per exposure: stage 1 a year's PD, stage 2 (30+ days past due, grade 8 or worse, or a frozen facility) the lifetime PD over the remaining term, stage 3 (90+ days or in default) certain default. Posting books the change in the allowance against impairment expense, by someone other than the calculator.">
      {can("risk:rate") && (
        <div className="mb-3 flex items-center gap-2 text-xs">
          <Button size="sm" onClick={() => calculate.mutate()} disabled={calculate.isPending}>
            Calculate ECL
          </Button>
          <ErrorMessage error={calculate.error} />
        </div>
      )}
      <ErrorMessage error={runs.error ?? decide.error} />
      <table aria-label="Provision runs" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {runs.data?.items.map((run) => (
            <tr key={run.id} className="align-top">
              <td className="px-2 py-1.5 font-mono text-xs">
                <button type="button" className="underline decoration-dotted" aria-expanded={open === run.id} aria-label={`Lines of ${run.run_number}`} onClick={() => setOpen(open === run.id ? null : run.id)}>
                  {run.run_number}
                </button>
              </td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                as of {run.as_of} · {run.exposures} exposures
                {Object.entries(run.totals).map(([ccy, t]) => (
                  <div key={ccy}>
                    {ccy}: ECL {formatExactMoney(t.ecl, ccy)} (stage 1 {formatExactMoney(t.stage_1, ccy)}, 2 {formatExactMoney(t.stage_2, ccy)}, 3 {formatExactMoney(t.stage_3, ccy)}) · change {formatExactMoney(t.change, ccy)}
                  </div>
                ))}
                {open === run.id && <RunLines runId={run.id} />}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={RUN_TONE[run.status]} label={run.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {run.status === "calculated" && can("risk:approve") && (
                  <div className="flex justify-end gap-1">
                    <Button size="sm" aria-label={`Post ${run.run_number}`} onClick={() => decide.mutate({ id: run.id, post: true })}>
                      Post
                    </Button>
                    <Button size="sm" variant="secondary" aria-label={`Reject ${run.run_number}`} onClick={() => decide.mutate({ id: run.id, post: false })}>
                      Reject
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
          {runs.data && runs.data.items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No provision runs yet.</td>
            </tr>
          )}
        </tbody>
      </table>
      <Pager label="Run pages" offset={offset} total={runs.data?.total ?? 0} onChange={setOffset} />
    </Panel>
  );
}

/** Risk (Phase 47): internal credit ratings, obligor limits and ECL provisioning. */
export function RiskPage() {
  const summary = useRiskSummary();
  return (
    <>
      <PageHeader title="Risk" description="Internal credit ratings with a model and four-eyes overrides, obligor limits against measured exposure, and IFRS 9 expected-credit-loss provisioning posted to the ledger." />
      {summary.data && (
        <dl aria-label="Risk summary" className="mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          {(
            [
              ["Approved ratings", summary.data.ratings],
              ["Ratings to approve", summary.data.ratings_pending],
              ["Runs to post", summary.data.runs_to_approve],
              ["Last posted run", summary.data.last_posted_run ? `${summary.data.last_posted_run} (${summary.data.last_posted_as_of})` : "None"],
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
        <ObligorPanel />
        <RatingsPanel />
        <ProvisionsPanel />
      </div>
    </>
  );
}
