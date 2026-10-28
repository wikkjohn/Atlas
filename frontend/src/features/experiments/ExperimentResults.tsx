import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";

import { PairedBarChart } from "@/components/PairedBarChart";
import { StatusPill } from "@/components/StatusPill";
import type { Comparison, ExperimentDetail, Verdict } from "@/types/experiments";

/** Cost lines in reading order (the API's JSON objects do not keep key order). */
export const COST_LINES: [string, string][] = [
  ["review_labour", "Review labour"],
  ["automation_oversight", "Oversight of automated decisions"],
  ["ai_execution", "AI execution"],
  ["infrastructure", "Infrastructure"],
  ["exception_handling", "Exception handling"],
  ["manual_escalation", "Manual escalation"],
];

export const MODE_NAMES = { ai_assisted: "B — AI assisted", ai_automated: "C — AI automated tasks" } as const;

export function VerdictPill({ verdict }: { verdict: Verdict | null }) {
  if (!verdict) return null;
  return verdict === "successful" ? (
    <StatusPill tone="good" label="Successful" />
  ) : (
    <StatusPill tone="bad" label="Not successful" />
  );
}

export function formatValue(value: number | null, unit: Comparison["unit"], currency = ""): string {
  if (value === null) return "—";
  if (unit === "ratio") return `${(value * 100).toFixed(1)}%`;
  if (unit === "hours") return `${value.toFixed(2)} h`;
  if (unit === "currency") return `${currency}${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return value.toLocaleString();
}

export function formatChange(row: Pick<Comparison, "relative_change">): string {
  if (row.relative_change === null) return "—";
  const pct = row.relative_change * 100;
  return `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

export function CriteriaList({ experiment }: { experiment: ExperimentDetail }) {
  const evaluation = experiment.evaluation;
  if (!evaluation) return null;
  return (
    <ul aria-label="Success criteria" className="space-y-1.5">
      {evaluation.criteria.map((c) => (
        <li key={c.criterion} className="flex items-start gap-2 text-sm">
          {c.passed ? (
            <CheckCircle2 aria-label="Met" className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
          ) : (
            <XCircle aria-label="Not met" className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
          )}
          <span>
            <span className="font-medium text-slate-900">{c.label}</span>
            <span className="block text-xs text-slate-600">{c.detail}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function ComparisonTable({ experiment }: { experiment: ExperimentDetail }) {
  const evaluation = experiment.evaluation;
  if (!evaluation) return null;
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table aria-label="Metric comparison" className="min-w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
          <tr>
            <th className="px-3 py-2">Metric</th>
            <th className="px-3 py-2 text-right">Baseline</th>
            <th className="px-3 py-2 text-right">Candidate</th>
            <th className="px-3 py-2 text-right">Change</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {evaluation.comparisons.map((row) => (
            <tr key={row.metric} className={row.regression ? "bg-rose-50" : undefined}>
              <td className="px-3 py-2">
                {row.label}
                {row.better === "none" && <span className="ml-1 text-[11px] text-slate-400">(informational)</span>}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{formatValue(row.baseline, row.unit)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{formatValue(row.candidate, row.unit)}</td>
              <td className="px-3 py-2 text-right tabular-nums">
                <span className="inline-flex items-center gap-1">
                  {formatChange(row)}
                  {row.regression && (
                    <span className="inline-flex items-center gap-0.5 text-[11px] font-medium text-rose-700">
                      <AlertTriangle aria-hidden className="h-3 w-3" /> Regression
                    </span>
                  )}
                  {row.improved && <span className="text-[11px] font-medium text-emerald-700">Better</span>}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CostTable({ experiment }: { experiment: ExperimentDetail }) {
  const evaluation = experiment.evaluation;
  if (!evaluation) return null;
  const { baseline, candidate } = evaluation.costs;
  const money = (v: number | null) => formatValue(v, "currency");
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table aria-label="Cost breakdown" className="min-w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
          <tr>
            <th className="px-3 py-2">Cost line ({experiment.configuration.costs.currency_label})</th>
            <th className="px-3 py-2 text-right">Baseline</th>
            <th className="px-3 py-2 text-right">Candidate</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {COST_LINES.map(([line, label]) => (
            <tr key={line}>
              <td className="px-3 py-2">{label}</td>
              <td className="px-3 py-2 text-right tabular-nums">{money(baseline.lines[line] ?? null)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{money(candidate.lines[line] ?? null)}</td>
            </tr>
          ))}
          <tr className="font-semibold">
            <td className="px-3 py-2">Operating total</td>
            <td className="px-3 py-2 text-right tabular-nums">{money(baseline.operating_total)}</td>
            <td className="px-3 py-2 text-right tabular-nums">{money(candidate.operating_total)}</td>
          </tr>
          <tr>
            <td className="px-3 py-2">Cost per completed case</td>
            <td className="px-3 py-2 text-right tabular-nums">{money(baseline.cost_per_completed_case)}</td>
            <td className="px-3 py-2 text-right tabular-nums">{money(candidate.cost_per_completed_case)}</td>
          </tr>
          <tr className="text-slate-500">
            <td className="px-3 py-2">Risk exposure of wrong decisions (not in operating cost)</td>
            <td className="px-3 py-2 text-right tabular-nums">{money(baseline.risk_exposure_total)}</td>
            <td className="px-3 py-2 text-right tabular-nums">{money(candidate.risk_exposure_total)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function seriesLabels(experiment: ExperimentDetail) {
  return {
    baseline: `A — Baseline (run #${experiment.baseline.run_number})`,
    candidate: `${MODE_NAMES[experiment.candidate_mode]} (run #${experiment.candidate.run_number})`,
  };
}

export function ProcessingTimeChart({ experiment }: { experiment: ExperimentDetail }) {
  const raw = Object.fromEntries(experiment.measurements.map((m) => [m.role, m.metrics]));
  const hours = (role: string, key: "avg" | "p50" | "p95") => {
    const v = raw[role]?.cycle_seconds[key];
    return v == null ? null : v / 3600;
  };
  return (
    <PairedBarChart
      title="Processing time per case (simulated hours)"
      rows={(["avg", "p50", "p95"] as const).map((key) => ({
        label: { avg: "Average", p50: "Median", p95: "95th percentile" }[key],
        baseline: hours("baseline", key),
        candidate: hours("candidate", key),
      }))}
      format={(v) => `${v.toFixed(2)} h`}
      seriesLabels={seriesLabels(experiment)}
      caption="From the cases' recorded cycle times; steps take no simulated time, so this is waiting for people and documents."
    />
  );
}

export function CostChart({ experiment }: { experiment: ExperimentDetail }) {
  const evaluation = experiment.evaluation;
  if (!evaluation) return null;
  const { baseline, candidate } = evaluation.costs;
  return (
    <PairedBarChart
      title={`Estimated operating cost by line (${experiment.configuration.costs.currency_label})`}
      rows={COST_LINES.map(([line, label]) => ({
        label,
        baseline: baseline.lines[line] ?? null,
        candidate: candidate.lines[line] ?? null,
      }))}
      format={(v) => v.toLocaleString(undefined, { maximumFractionDigits: 0 })}
      seriesLabels={seriesLabels(experiment)}
      caption="Simulation estimates computed from the stated assumptions — not measured spending or verified savings."
    />
  );
}

export function QualityIndicators({ experiment }: { experiment: ExperimentDetail }) {
  const evaluation = experiment.evaluation;
  if (!evaluation) return null;
  const pick = ["accuracy", "false_approval_rate", "false_rejection_rate", "escalation_rate", "error_count", "policy_violation_rate"];
  const rows = evaluation.comparisons.filter((r) => pick.includes(r.metric));
  return (
    <dl aria-label="Quality and compliance indicators" className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {rows.map((r) => (
        <div key={r.metric} className={`rounded-lg border p-3 ${r.regression ? "border-rose-300 bg-rose-50" : "border-slate-200 bg-white"}`}>
          <dt className="text-xs text-slate-500">{r.label}</dt>
          <dd className="mt-0.5 text-sm text-slate-900">
            <span className="tabular-nums">{formatValue(r.baseline, r.unit)}</span>
            <span className="mx-1 text-slate-400">→</span>
            <span className="font-semibold tabular-nums">{formatValue(r.candidate, r.unit)}</span>
          </dd>
          {r.regression && (
            <dd className="mt-0.5 inline-flex items-center gap-1 text-[11px] font-medium text-rose-700">
              <AlertTriangle aria-hidden className="h-3 w-3" /> Regression
            </dd>
          )}
        </div>
      ))}
    </dl>
  );
}
