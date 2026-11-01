import { useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import {
  COMPLIANCE_PAGE,
  useAlertAction,
  useAlerts,
  useCaseAction,
  useCases,
  useCompleteReview,
  useComplianceSummary,
  useFileSar,
  useReviews,
  useRunMonitoring,
  useRuns,
  useSars,
  useScheduleReviews,
} from "@/services/compliance";
import { formatExactMoney, humanize } from "@/services/format";
import { RULE_LABELS, type AmlAlert, type ComplianceCase } from "@/types/compliance";

const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const ALERT_TONE: Record<AmlAlert["status"], Tone> = { open: "warn", in_case: "warn", dismissed: "neutral", closed: "neutral", escalated: "bad" };
const CASE_TONE: Record<ComplianceCase["status"], Tone> = { investigating: "warn", sar_drafted: "warn", sar_filed: "bad", closed: "neutral" };

/** Newer/older paging for a list, `COMPLIANCE_PAGE` rows at a time. */
function Pager({ label, offset, total, onChange }: { label: string; offset: number; total: number; onChange: (offset: number) => void }) {
  if (total <= COMPLIANCE_PAGE) return null;
  return (
    <nav aria-label={label} className="mt-2 flex items-center justify-end gap-2 text-xs text-slate-600">
      <span>
        {offset + 1}–{Math.min(offset + COMPLIANCE_PAGE, total)} of {total}
      </span>
      <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => onChange(Math.max(offset - COMPLIANCE_PAGE, 0))}>
        Newer
      </Button>
      <Button size="sm" variant="secondary" disabled={offset + COMPLIANCE_PAGE >= total} onClick={() => onChange(offset + COMPLIANCE_PAGE)}>
        Older
      </Button>
    </nav>
  );
}

function MonitoringPanel() {
  const { can } = useAuth();
  const runs = useRuns();
  const run = useRunMonitoring();
  const [days, setDays] = useState("30");
  const [offset, setOffset] = useState(0);
  const [account, setAccount] = useState("");
  const alerts = useAlerts(offset, account.trim().toUpperCase());
  const action = useAlertAction();
  const items = alerts.data?.items ?? [];
  return (
    <Panel title="Transaction monitoring" subtitle="Each run reads customer accounts' ledger activity over a window. Rules: a cash deposit at or above the reporting threshold (US$10,000 equivalent), three or more just under it within ten days, money passed straight through, and high turnover by a high-risk customer.">
      {can("compliance:monitor") && (
        <form
          aria-label="Run monitoring"
          className="mb-3 flex flex-wrap items-end gap-2 text-xs"
          onSubmit={(e) => {
            e.preventDefault();
            run.mutate(Number(days));
          }}
        >
          <label className="flex flex-col gap-0.5 text-slate-600">
            Window (days)
            <input aria-label="Window days" type="number" min={1} max={366} className={`w-20 ${INPUT}`} value={days} onChange={(e) => setDays(e.target.value)} />
          </label>
          <Button size="sm" type="submit" disabled={run.isPending}>
            Run monitoring
          </Button>
          <ErrorMessage error={run.error} />
        </form>
      )}
      {runs.data && runs.data.items.length > 0 && (
        <p className="mb-2 text-xs text-slate-600" aria-label="Latest run">
          {runs.data.items[0].run_number}: {runs.data.items[0].window_start} to {runs.data.items[0].window_end}, {runs.data.items[0].accounts_scanned} accounts, {runs.data.items[0].alerts_raised} alerts
        </p>
      )}
      <label className="mb-2 flex items-center gap-2 text-xs text-slate-600">
        Account
        <input
          aria-label="Alerts for account"
          placeholder="All accounts"
          className={`w-44 ${INPUT}`}
          value={account}
          onChange={(e) => {
            setAccount(e.target.value);
            setOffset(0);
          }}
        />
      </label>
      <ErrorMessage error={alerts.error ?? action.error} />
      <table aria-label="Alerts" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {items.map((a) => (
            <tr key={a.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{a.alert_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {RULE_LABELS[a.rule]} (score {a.score}) · {a.customer_name} ({a.customer_number}) · {a.account_number}
                {a.case_number && ` · ${a.case_number}`}
                {a.note && ` · ${a.note}`}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(a.amount, a.currency)}</td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={ALERT_TONE[a.status]} label={humanize(a.status)} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {a.status === "open" && can("compliance:monitor") && (
                  <div className="flex justify-end gap-1">
                    <Button size="sm" aria-label={`Investigate ${a.alert_number}`} onClick={() => action.mutate({ id: a.id, action: "investigate" })}>
                      Investigate
                    </Button>
                    <Button size="sm" variant="secondary" aria-label={`Dismiss ${a.alert_number}`} onClick={() => action.mutate({ id: a.id, action: "dismiss" })}>
                      Dismiss
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
          {alerts.data && items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No alerts.</td>
            </tr>
          )}
        </tbody>
      </table>
      <Pager label="Alert pages" offset={offset} total={alerts.data?.total ?? 0} onChange={setOffset} />
    </Panel>
  );
}

function CasesPanel() {
  const { can } = useAuth();
  const [offset, setOffset] = useState(0);
  const cases = useCases(offset);
  const action = useCaseAction();
  const [sarOffset, setSarOffset] = useState(0);
  const sars = useSars(sarOffset);
  const file = useFileSar();
  return (
    <Panel title="Cases and reports" subtitle="A case takes in all of a customer's open alerts. Closing it with no action needs a second compliance officer; escalating drafts a suspicious activity report, filed with the (synthetic) FIU by someone other than its preparer.">
      <ErrorMessage error={cases.error ?? action.error} />
      <table aria-label="Cases" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {cases.data?.items.map((c) => (
            <tr key={c.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{c.case_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {c.customer_name} ({c.customer_number}) · {c.alerts.join(", ")}
                {c.sar_number && ` · ${c.sar_number}`}
                {c.note && ` · ${c.note}`}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={CASE_TONE[c.status]} label={humanize(c.status)} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {c.status === "investigating" && can("compliance:monitor") && (
                  <div className="flex justify-end gap-1">
                    <Button size="sm" aria-label={`Escalate ${c.case_number}`} onClick={() => action.mutate({ id: c.id, action: "sar" })}>
                      Draft report
                    </Button>
                    <Button size="sm" variant="secondary" aria-label={`Close ${c.case_number}`} onClick={() => action.mutate({ id: c.id, action: "close" })}>
                      Close, no action
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Pager label="Case pages" offset={offset} total={cases.data?.total ?? 0} onChange={setOffset} />
      <ErrorMessage error={sars.error ?? file.error} />
      <table aria-label="Suspicious activity reports" className="mt-4 min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {sars.data?.items.map((s) => (
            <tr key={s.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{s.sar_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {s.case_number} · {s.narrative}
                {s.filing_reference && ` · ${s.filing_reference}`}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={s.status === "filed" ? "bad" : "warn"} label={s.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {s.status === "draft" && can("compliance:file") && (
                  <Button size="sm" aria-label={`File ${s.sar_number}`} onClick={() => file.mutate(s.id)}>
                    File
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Pager label="Report pages" offset={sarOffset} total={sars.data?.total ?? 0} onChange={setSarOffset} />
    </Panel>
  );
}

function ReviewsPanel() {
  const { can } = useAuth();
  const [offset, setOffset] = useState(0);
  const reviews = useReviews(offset);
  const schedule = useScheduleReviews();
  const complete = useCompleteReview();
  const [ratings, setRatings] = useState<Record<string, string>>({});
  return (
    <Panel title="Periodic KYC reviews" subtitle="Due every year for high-risk customers, two years for medium and three for low, from the last review (or when they joined). Completing a review confirms, raises or lowers the risk rating.">
      {can("compliance:monitor") && (
        <div className="mb-3 flex items-center gap-2 text-xs">
          <Button size="sm" onClick={() => schedule.mutate(30)} disabled={schedule.isPending}>
            Open reviews due in 30 days
          </Button>
          {schedule.data && <span role="status">{schedule.data.opened} opened</span>}
          <ErrorMessage error={schedule.error} />
        </div>
      )}
      <ErrorMessage error={reviews.error ?? complete.error} />
      <table aria-label="KYC reviews" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {reviews.data?.items.map((r) => (
            <tr key={r.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{r.review_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {r.customer_name} ({r.customer_number}) · due {r.due_on} · rated {r.risk_before}
                {r.outcome && ` · ${r.outcome}${r.risk_after ? ` to ${r.risk_after}` : ""}`}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={r.status === "due" ? "warn" : "good"} label={r.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {r.status === "due" && can("compliance:monitor") && (
                  <div className="flex justify-end gap-1">
                    <select aria-label={`Rating for ${r.review_number}`} className={`text-xs ${INPUT}`} value={ratings[r.id] ?? r.risk_before} onChange={(e) => setRatings({ ...ratings, [r.id]: e.target.value })}>
                      {["low", "medium", "high"].map((v) => (
                        <option key={v} value={v}>
                          {v}
                        </option>
                      ))}
                    </select>
                    <Button size="sm" aria-label={`Complete ${r.review_number}`} onClick={() => complete.mutate({ id: r.id, risk_rating: ratings[r.id] ?? r.risk_before })}>
                      Complete
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Pager label="Review pages" offset={offset} total={reviews.data?.total ?? 0} onChange={setOffset} />
    </Panel>
  );
}

/** Compliance (Phase 45): AML monitoring, alerts, cases, reports and periodic KYC reviews. */
export function CompliancePage() {
  const summary = useComplianceSummary();
  return (
    <>
      <PageHeader title="Compliance" description="Anti-money-laundering transaction monitoring, alert investigation, suspicious activity reports filed with a synthetic financial intelligence unit, and periodic KYC reviews." />
      {summary.data && (
        <dl aria-label="Compliance summary" className="mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
          {(
            [
              ["Open alerts", summary.data.open_alerts],
              ["Open cases", summary.data.open_cases],
              ["Reports to file", summary.data.draft_sars],
              ["Reviews due", summary.data.reviews_due],
              ["Reviews overdue", summary.data.reviews_overdue],
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
        <MonitoringPanel />
        <CasesPanel />
        <ReviewsPanel />
      </div>
    </>
  );
}
