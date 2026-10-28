import { Link, useSearchParams } from "react-router-dom";

import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { SyntheticDataBadge } from "@/components/SyntheticDataBadge";
import {
  CostChart,
  CriteriaList,
  formatChange,
  MODE_NAMES,
  ProcessingTimeChart,
  QualityIndicators,
  VerdictPill,
} from "@/features/experiments/ExperimentResults";
import { useBenchmarks, useExperiment, useExperiments } from "@/services/experiments";

const CHANGE_COLUMNS = [
  ["labour_hours", "Labour time"],
  ["cost_per_completed_case", "Cost per case"],
  ["processing_time_hours", "Processing time"],
  ["accuracy", "Accuracy"],
] as const;

function Leaderboard() {
  const benchmarks = useBenchmarks();
  return (
    <div className="space-y-2">
      <ErrorMessage error={benchmarks.error} />
      <div className="overflow-x-auto rounded-xl border border-slate-200">
        <table aria-label="Tool benchmarks" className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="px-3 py-2">Tool</th>
              <th className="px-3 py-2">Configuration</th>
              <th className="px-3 py-2 text-right">Experiments</th>
              {CHANGE_COLUMNS.map(([, label]) => (
                <th key={label} className="px-3 py-2 text-right">
                  {label}
                </th>
              ))}
              <th className="px-3 py-2">Latest verdict</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {(benchmarks.data ?? []).map((row) => (
              <tr key={`${row.tool_id}-${row.tool_version}-${row.candidate_mode}`}>
                <td className="px-3 py-2">
                  <span className="font-medium">{row.tool_id}</span> <span className="text-xs text-slate-500">{row.tool_version}</span>
                </td>
                <td className="px-3 py-2">{MODE_NAMES[row.candidate_mode]}</td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {row.successful}/{row.experiments} successful
                </td>
                {CHANGE_COLUMNS.map(([key]) => (
                  <td key={key} className="px-3 py-2 text-right tabular-nums">
                    {formatChange({ relative_change: row.median_relative_change[key] ?? null })}
                  </td>
                ))}
                <td className="px-3 py-2">
                  <Link to={`/benchmarking?experiment=${row.latest_experiment_id}`} className="hover:underline">
                    <VerdictPill verdict={row.latest_verdict} />
                  </Link>
                </td>
              </tr>
            ))}
            {benchmarks.data?.length === 0 && (
              <tr>
                <td colSpan={8} className="px-3 py-6 text-center text-sm text-slate-500">
                  No completed experiments yet. Run one from the Experiments screen.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-slate-500">
        Median relative change versus each experiment's own baseline (negative is lower). Simulated estimates on synthetic
        data under each experiment's stated assumptions.
      </p>
    </div>
  );
}

function ExperimentBenchmark({ id }: { id: string }) {
  const experiment = useExperiment(id);
  const e = experiment.data;
  if (experiment.error) return <ErrorMessage error={experiment.error} />;
  if (!e) return <p className="text-sm text-slate-500">Loading…</p>;
  if (!e.evaluation) {
    return <p className="text-sm text-slate-500">Experiment #{e.experiment_number} is {e.status}; it has no evaluation yet.</p>;
  }
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-semibold text-slate-900">
          Experiment #{e.experiment_number}: {e.name}
        </h2>
        <VerdictPill verdict={e.verdict} />
        <Link to={`/experiments?experiment=${e.id}`} className="text-xs text-navy-700 hover:underline">
          Full evaluation and report
        </Link>
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <ProcessingTimeChart experiment={e} />
        <CostChart experiment={e} />
      </div>
      <section aria-label="Quality indicators" className="space-y-2">
        <h3 className="text-sm font-semibold text-slate-900">Quality and compliance</h3>
        <QualityIndicators experiment={e} />
      </section>
      <section aria-label="Compliance results" className="space-y-2">
        <h3 className="text-sm font-semibold text-slate-900">Criteria</h3>
        <CriteriaList experiment={e} />
      </section>
      <section aria-label="Run details" className="text-sm">
        <h3 className="mb-1 text-sm font-semibold text-slate-900">Run details</h3>
        <ul className="space-y-0.5 text-xs text-slate-600">
          <li>
            Baseline:{" "}
            <Link className="text-navy-700 hover:underline" to={`/simulations?run=${e.baseline.id}`}>
              run #{e.baseline.run_number}
            </Link>
          </li>
          <li>
            Candidate ({MODE_NAMES[e.candidate_mode]}, {e.tool_id} {e.tool_version}):{" "}
            <Link className="text-navy-700 hover:underline" to={`/simulations?run=${e.candidate.id}`}>
              run #{e.candidate.run_number}
            </Link>
          </li>
          <li>
            Evaluation {e.evaluation.evaluation_version}, digest{" "}
            <span className="font-mono">{e.evaluation.evaluation_digest.slice(0, 16)}</span>
          </li>
        </ul>
      </section>
      <section aria-label="Experiment conclusion" className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-800">
        <h3 className="mb-1 text-sm font-semibold text-slate-900">Conclusion</h3>
        {e.evaluation.conclusion}
      </section>
    </div>
  );
}

export function BenchmarkingPage() {
  const [params, setParams] = useSearchParams();
  const experiments = useExperiments(0, 50);
  const completed = (experiments.data?.items ?? []).filter((x) => x.status === "completed");
  const selected = params.get("experiment") ?? completed[0]?.id ?? null;
  return (
    <div className="space-y-6">
      <PageHeader
        title="Benchmarking"
        description="Baseline versus AI-supported performance: processing time, cost, quality, compliance and conclusions."
        actions={<SyntheticDataBadge />}
      />
      <Panel title="Tools compared" subtitle="All completed experiments, by tool version and configuration">
        <Leaderboard />
      </Panel>
      <Panel
        title="Baseline vs. AI"
        actions={
          completed.length > 0 ? (
            <div className="w-72">
              <Field label="Experiment">
                {(p) => (
                  <select {...p} className={inputClass} value={selected ?? ""} onChange={(ev) => setParams({ experiment: ev.target.value })}>
                    {completed.map((x) => (
                      <option key={x.id} value={x.id}>
                        #{x.experiment_number} {x.name}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
            </div>
          ) : undefined
        }
      >
        <ErrorMessage error={experiments.error} />
        {selected ? <ExperimentBenchmark key={selected} id={selected} /> : <p className="text-sm text-slate-500">No completed experiment to show.</p>}
      </Panel>
    </div>
  );
}
