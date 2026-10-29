import { CalendarClock } from "lucide-react";
import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Panel } from "@/components/Panel";
import { formatTimestamp } from "@/features/dashboard/format";
import { useRunServicing, useServicingRuns } from "@/services/banking";
import { formatExactMoney } from "@/services/format";
import type { ServicingRun } from "@/types/banking";

const BUCKETS = ["current", "1-29", "30-59", "60-89", "90+"] as const;

function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** The next date to service to: a month after the business date, or today. */
export function suggestedDate(businessDate: string | null, today = new Date()): string {
  if (!businessDate) return isoDate(today);
  const next = new Date(`${businessDate}T00:00:00Z`);
  next.setUTCMonth(next.getUTCMonth() + 1);
  return isoDate(next);
}

function arrearsTotal(run: ServicingRun): string {
  const parts = Object.entries(run.summary.arrears_amount).map(([currency, amount]) => formatExactMoney(amount, currency));
  return parts.length ? parts.join(" · ") : "—";
}

export function ServicingPanel() {
  const { can } = useAuth();
  const runs = useServicingRuns({ limit: 5 });
  const latest = runs.data?.items[0] ?? null;
  const businessDate = latest?.as_of ?? null;
  const [asOf, setAsOf] = useState<string | null>(null);
  const start = useRunServicing();
  const target = asOf ?? suggestedDate(businessDate);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    start.mutate(target, { onSuccess: () => setAsOf(null) });
  };

  return (
    <Panel
      title="Loan servicing"
      subtitle="A servicing run accrues interest and collects every instalment due up to its business date, oldest first, from the borrower's account. Instalments it cannot collect stay due: the loan is in arrears. At 30 days past due WF-0004 opens a collections case."
    >
      <div className="grid gap-5 lg:grid-cols-[minmax(0,18rem)_1fr]">
        <div className="space-y-3">
          <div>
            <div className="text-xs font-medium tracking-wide text-slate-500 uppercase">Business date</div>
            <div className="mt-0.5 flex items-center gap-2 text-lg font-semibold text-slate-900" data-testid="business-date">
              <CalendarClock aria-hidden className="h-4 w-4 text-slate-400" />
              {runs.isPending ? "…" : (businessDate ?? "Not serviced yet")}
            </div>
          </div>
          {can("loans:service") && (
            <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
              <label className="text-xs font-medium text-slate-700">
                Service to
                <input
                  type="date"
                  aria-label="Service to"
                  required
                  min={businessDate ?? undefined}
                  value={target}
                  onChange={(e) => setAsOf(e.target.value)}
                  className="mt-1 block rounded-lg border border-slate-200 px-2 py-1 text-sm"
                />
              </label>
              <Button type="submit" size="sm" disabled={start.isPending}>
                {start.isPending ? "Servicing…" : "Run servicing"}
              </Button>
            </form>
          )}
          <ErrorMessage error={start.error ?? runs.error} />
        </div>
        <div className="overflow-x-auto">
          <table aria-label="Servicing runs" className="min-w-full text-sm">
            <thead className="text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
              <tr>
                <th className="px-2 py-1">Run</th>
                <th className="px-2 py-1">As of</th>
                <th className="px-2 py-1 text-right">Loans</th>
                <th className="px-2 py-1 text-right">Collected</th>
                <th className="px-2 py-1 text-right">Missed</th>
                <th className="px-2 py-1 text-right">Repaid</th>
                <th className="px-2 py-1">Arrears</th>
                <th className="px-2 py-1">Buckets</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {runs.data?.items.map((run) => (
                <tr key={run.id}>
                  <td className="px-2 py-1.5">
                    <div className="font-mono text-xs">#{run.run_number}</div>
                    <div className="text-[11px] text-slate-400">
                      {run.started_by_username} · {formatTimestamp(run.created_at)}
                    </div>
                  </td>
                  <td className="px-2 py-1.5 tabular-nums">{run.as_of}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{run.summary.loans}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{run.summary.collected}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{run.summary.missed}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{run.summary.repaid}</td>
                  <td className="px-2 py-1.5 tabular-nums">{arrearsTotal(run)}</td>
                  <td className="px-2 py-1.5 text-xs text-slate-600">
                    {BUCKETS.filter((b) => run.summary.buckets[b])
                      .map((b) => `${b}: ${run.summary.buckets[b]}`)
                      .join(" · ") || "—"}
                  </td>
                </tr>
              ))}
              {runs.data?.items.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-2 py-4 text-center text-xs text-slate-500">
                    No servicing runs yet: no instalment has been accrued or collected.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </Panel>
  );
}
