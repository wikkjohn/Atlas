import { useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import {
  FINANCE_PAGE,
  downloadReportCsv,
  useAllocations,
  useCalculateAllocation,
  useCloses,
  useDecideAllocation,
  useDecideClose,
  useDecideReport,
  useFinanceSummary,
  usePrepareClose,
  usePrepareReport,
  useRecordExpense,
  useReports,
} from "@/services/finance";
import { formatExactMoney, toMinorUnits } from "@/services/format";
import { CHECK_LABELS, REPORT_LABELS, type ReportType } from "@/types/finance";

const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const TONE: Record<string, Tone> = { prepared: "warn", calculated: "warn", closed: "good", submitted: "good", posted: "good", rejected: "neutral" };
const lastMonth = () => {
  const d = new Date();
  d.setDate(0);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};
const thisMonth = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};

/** Newer/older paging, `FINANCE_PAGE` rows at a time. */
function Pager({ label, offset, total, onChange }: { label: string; offset: number; total: number; onChange: (offset: number) => void }) {
  if (total <= FINANCE_PAGE) return null;
  return (
    <nav aria-label={label} className="mt-2 flex items-center justify-end gap-2 text-xs text-slate-600">
      <span>
        {offset + 1}–{Math.min(offset + FINANCE_PAGE, total)} of {total}
      </span>
      <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => onChange(Math.max(offset - FINANCE_PAGE, 0))}>
        Newer
      </Button>
      <Button size="sm" variant="secondary" disabled={offset + FINANCE_PAGE >= total} onClick={() => onChange(offset + FINANCE_PAGE)}>
        Older
      </Button>
    </nav>
  );
}

function ClosePanel({ nextPeriod }: { nextPeriod: string | null }) {
  const { can } = useAuth();
  const [offset, setOffset] = useState(0);
  const closes = useCloses(offset);
  const prepare = usePrepareClose();
  const decide = useDecideClose();
  const [period, setPeriod] = useState(nextPeriod ?? lastMonth());
  return (
    <Panel title="Month-end close" subtitle="Preparing a close checks the ledger as of the month's end (the month is over, debits equal credits, a reconciliation has passed since; ECL provisions are advisory) and measures each currency's result. Someone else closes the month, bringing income and expense to zero against retained earnings. Months close in order.">
      {can("finance:close") && (
        <form
          aria-label="Prepare close"
          className="mb-3 flex flex-wrap items-end gap-2 text-xs"
          onSubmit={(e) => {
            e.preventDefault();
            prepare.mutate(period);
          }}
        >
          <label className="flex flex-col gap-0.5 text-slate-600">
            Month
            <input aria-label="Close month" type="month" className={INPUT} value={period} onChange={(e) => setPeriod(e.target.value)} />
          </label>
          <Button size="sm" type="submit" disabled={prepare.isPending}>
            Prepare close
          </Button>
          <ErrorMessage error={prepare.error} />
        </form>
      )}
      <ErrorMessage error={closes.error ?? decide.error} />
      <table aria-label="Closes" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {closes.data?.items.map((c) => (
            <tr key={c.id} className="align-top">
              <td className="px-2 py-1.5 font-mono text-xs">{c.close_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                <div>
                  {c.period} ·{" "}
                  {c.checks.map((k) => (
                    <span key={k.check} title={k.detail} className={k.passed ? "text-emerald-700" : k.blocking ? "text-rose-700" : "text-amber-700"}>
                      {CHECK_LABELS[k.check]} {k.passed ? "✓" : "✗"}{" "}
                    </span>
                  ))}
                </div>
                {Object.entries(c.results).map(([ccy, r]) => (
                  <div key={ccy}>
                    {ccy}: income {formatExactMoney(r.income, ccy)}, expense {formatExactMoney(r.expense, ccy)}, net {formatExactMoney(r.net_income, ccy)}
                  </div>
                ))}
                {c.note && <div>{c.note}</div>}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={TONE[c.status]} label={c.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {c.status === "prepared" && can("finance:approve") && (
                  <div className="flex justify-end gap-1">
                    <Button size="sm" aria-label={`Close ${c.close_number}`} onClick={() => decide.mutate({ id: c.id, approve: true })}>
                      Close month
                    </Button>
                    <Button size="sm" variant="secondary" aria-label={`Reject ${c.close_number}`} onClick={() => decide.mutate({ id: c.id, approve: false })}>
                      Reject
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
          {closes.data && closes.data.items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No closes yet.</td>
            </tr>
          )}
        </tbody>
      </table>
      <Pager label="Close pages" offset={offset} total={closes.data?.total ?? 0} onChange={setOffset} />
    </Panel>
  );
}

function ReportsPanel({ lastClosed }: { lastClosed: string | null }) {
  const { can } = useAuth();
  const [offset, setOffset] = useState(0);
  const reports = useReports(offset);
  const prepare = usePrepareReport();
  const decide = useDecideReport();
  const [type, setType] = useState<ReportType>("balance_sheet");
  const [period, setPeriod] = useState(lastClosed ?? lastMonth());
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Panel title="Regulatory reports" subtitle="Extracts for a closed month: balance sheet and income statement by currency, large exposures (obligors of US$10,000 or more) and credit quality (the latest posted ECL run by stage). Someone other than the preparer submits each to the synthetic regulator; one of a type per month.">
      {can("finance:close") && (
        <form
          aria-label="Prepare report"
          className="mb-3 flex flex-wrap items-end gap-2 text-xs"
          onSubmit={(e) => {
            e.preventDefault();
            prepare.mutate({ report_type: type, period });
          }}
        >
          <label className="flex flex-col gap-0.5 text-slate-600">
            Report
            <select aria-label="Report type" className={INPUT} value={type} onChange={(e) => setType(e.target.value as ReportType)}>
              {(Object.keys(REPORT_LABELS) as ReportType[]).map((t) => (
                <option key={t} value={t}>
                  {REPORT_LABELS[t]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-0.5 text-slate-600">
            Month
            <input aria-label="Report month" type="month" className={INPUT} value={period} onChange={(e) => setPeriod(e.target.value)} />
          </label>
          <Button size="sm" type="submit" disabled={prepare.isPending}>
            Extract
          </Button>
          <ErrorMessage error={prepare.error} />
        </form>
      )}
      <ErrorMessage error={reports.error ?? decide.error} />
      <table aria-label="Reports" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {reports.data?.items.map((r) => (
            <tr key={r.id} className="align-top">
              <td className="px-2 py-1.5 font-mono text-xs">
                <button type="button" className="underline decoration-dotted" aria-expanded={open === r.id} aria-label={`Rows of ${r.report_number}`} onClick={() => setOpen(open === r.id ? null : r.id)}>
                  {r.report_number}
                </button>
              </td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {REPORT_LABELS[r.report_type]} · {r.period} · {r.rows.length} rows
                {r.reference && ` · ${r.reference}`}
                {open === r.id && (
                  <table aria-label="Report rows" className="mt-1 min-w-full">
                    <tbody>
                      {r.rows.map((row, i) => (
                        <tr key={i}>
                          {Object.values(row).map((v, j) => (
                            <td key={j} className="pr-3 tabular-nums">
                              {String(v)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={TONE[r.status]} label={r.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                <div className="flex justify-end gap-1">
                  <Button size="sm" variant="secondary" aria-label={`Download ${r.report_number}`} onClick={() => void downloadReportCsv(r)}>
                    CSV
                  </Button>
                  {r.status === "prepared" && can("finance:approve") && (
                    <>
                      <Button size="sm" aria-label={`Submit ${r.report_number}`} onClick={() => decide.mutate({ id: r.id, submit: true })}>
                        Submit
                      </Button>
                      <Button size="sm" variant="secondary" aria-label={`Reject ${r.report_number}`} onClick={() => decide.mutate({ id: r.id, submit: false })}>
                        Reject
                      </Button>
                    </>
                  )}
                </div>
              </td>
            </tr>
          ))}
          {reports.data && reports.data.items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No reports yet.</td>
            </tr>
          )}
        </tbody>
      </table>
      <Pager label="Report pages" offset={offset} total={reports.data?.total ?? 0} onChange={setOffset} />
    </Panel>
  );
}

function CostsPanel() {
  const { can } = useAuth();
  const [offset, setOffset] = useState(0);
  const allocations = useAllocations(offset);
  const expense = useRecordExpense();
  const calculate = useCalculateAllocation();
  const decide = useDecideAllocation();
  const [currency, setCurrency] = useState("USD");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("Office rent");
  const [period, setPeriod] = useState(thisMonth());
  return (
    <Panel title="Shared costs and allocation" subtitle="Shared operating costs (rent, technology, utilities) are paid from cash into a shared pool per currency. An allocation splits a month's pool across departments by their active headcount; someone else posts it to the departments' cost centres while the month is open.">
      {can("finance:close") && (
        <div className="mb-3 flex flex-col gap-2 text-xs">
          <form
            aria-label="Record expense"
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              expense.mutate({ currency, amount: toMinorUnits(Number(amount), currency), description });
            }}
          >
            <label className="flex flex-col gap-0.5 text-slate-600">
              Currency
              <input aria-label="Expense currency" className={`w-16 ${INPUT}`} maxLength={3} value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} />
            </label>
            <label className="flex flex-col gap-0.5 text-slate-600">
              Amount
              <input aria-label="Expense amount" type="number" min={0.01} step="0.01" className={`w-28 ${INPUT}`} value={amount} onChange={(e) => setAmount(e.target.value)} />
            </label>
            <label className="flex flex-col gap-0.5 text-slate-600">
              Description
              <input aria-label="Expense description" className={`w-48 ${INPUT}`} value={description} onChange={(e) => setDescription(e.target.value)} />
            </label>
            <Button size="sm" type="submit" disabled={expense.isPending || !amount}>
              Record cost
            </Button>
            {expense.data && <span role="status">{expense.data.entry_number} posted</span>}
            <ErrorMessage error={expense.error} />
          </form>
          <form
            aria-label="Allocate costs"
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              calculate.mutate({ period, currency });
            }}
          >
            <label className="flex flex-col gap-0.5 text-slate-600">
              Month
              <input aria-label="Allocation month" type="month" className={INPUT} value={period} onChange={(e) => setPeriod(e.target.value)} />
            </label>
            <Button size="sm" type="submit" disabled={calculate.isPending}>
              Split {currency} costs
            </Button>
            <ErrorMessage error={calculate.error} />
          </form>
        </div>
      )}
      <ErrorMessage error={allocations.error ?? decide.error} />
      <table aria-label="Allocations" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {allocations.data?.items.map((a) => (
            <tr key={a.id} className="align-top">
              <td className="px-2 py-1.5 font-mono text-xs">{a.allocation_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {a.period} · {formatExactMoney(a.pool, a.currency)} across {a.lines.length} departments by headcount
                <ul className="mt-0.5">
                  {a.lines.slice(0, 5).map((l) => (
                    <li key={l.department_id}>
                      {l.department} ({l.headcount}): {formatExactMoney(l.amount, a.currency)}
                    </li>
                  ))}
                  {a.lines.length > 5 && <li>and {a.lines.length - 5} more</li>}
                </ul>
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={TONE[a.status]} label={a.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {a.status === "calculated" && can("finance:approve") && (
                  <div className="flex justify-end gap-1">
                    <Button size="sm" aria-label={`Post ${a.allocation_number}`} onClick={() => decide.mutate({ id: a.id, post: true })}>
                      Post
                    </Button>
                    <Button size="sm" variant="secondary" aria-label={`Reject ${a.allocation_number}`} onClick={() => decide.mutate({ id: a.id, post: false })}>
                      Reject
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
          {allocations.data && allocations.data.items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No allocations yet.</td>
            </tr>
          )}
        </tbody>
      </table>
      <Pager label="Allocation pages" offset={offset} total={allocations.data?.total ?? 0} onChange={setOffset} />
    </Panel>
  );
}

/** Finance (Phase 49): month-end close, regulatory reports and cost allocation. */
export function FinancePage() {
  const summary = useFinanceSummary();
  return (
    <>
      <PageHeader title="Finance" description="The general ledger's month-end close, regulatory reporting extracts submitted to a synthetic regulator, and shared operating costs allocated to departments." />
      {summary.data && (
        <dl aria-label="Finance summary" className="mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          {(
            [
              ["Last closed month", summary.data.last_closed_period ?? "None"],
              ["Closes to approve", summary.data.closes_to_approve],
              ["Reports to submit", summary.data.reports_to_submit],
              ["Allocations to post", summary.data.allocations_to_post],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="rounded-lg border border-slate-200 bg-white p-3">
              <dt className="text-xs text-slate-500">{label}</dt>
              <dd className="text-lg font-semibold text-slate-900">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {summary.data && (
        <div className="flex flex-col gap-6">
          <ClosePanel nextPeriod={summary.data.next_period} />
          <ReportsPanel lastClosed={summary.data.last_closed_period} />
          <CostsPanel />
        </div>
      )}
      <ErrorMessage error={summary.error} />
    </>
  );
}
