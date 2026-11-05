import { GitCompare } from "lucide-react";
import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { MODE_NAMES } from "@/features/experiments/ExperimentResults";
import { pValue } from "@/features/experiments/SeriesPanel";
import { TIER_TONE } from "@/features/experiments/ThresholdsPanel";
import { useAiTools } from "@/services/aiTools";
import { useStartComparison, useToolComparison } from "@/services/experiments";
import { humanize } from "@/services/format";
import { useScenarios } from "@/services/simulations";
import type { Benchmark, PairOutcome, ToolPair } from "@/types/experiments";

const OUTCOME: Record<PairOutcome, { tone: Tone; label: (p: ToolPair) => string }> = {
  a_preferred: { tone: "good", label: (p) => `${p.a} preferred` },
  b_preferred: { tone: "good", label: (p) => `${p.b} preferred` },
  trade_off: { tone: "warn", label: () => "Trade-off" },
  no_difference: { tone: "neutral", label: () => "No significant difference" },
  identical: { tone: "neutral", label: () => "Identical results" },
  too_few_matched: { tone: "neutral", label: () => "Too few matched workloads" },
};
const FINDING = { a_better: "A better", b_better: "B better", no_significant_difference: "—", too_few_matched: "Too few" } as const;
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);
const num = (v: number | null | undefined) => (v === null || v === undefined ? "—" : Number(v.toFixed(3)).toLocaleString());

function PairDetail({ pair }: { pair: ToolPair }) {
  const outcome = OUTCOME[pair.outcome];
  return (
    <details className="rounded-lg border border-slate-200 p-2">
      <summary className="flex cursor-pointer flex-wrap items-center gap-2 text-xs">
        <span className="font-medium text-slate-800">
          A {pair.a} vs. B {pair.b}
        </span>
        <StatusPill tone={outcome.tone} label={outcome.label(pair)} />
        <span className="text-slate-500">
          {pair.matched_workloads} matched workloads (seeds {pair.seeds.join(", ") || "—"})
          {pair.a_better_on.length > 0 && ` · A better on ${pair.a_better_on.map(humanize).join(", ")}`}
          {pair.b_better_on.length > 0 && ` · B better on ${pair.b_better_on.map(humanize).join(", ")}`}
        </span>
      </summary>
      <div className="mt-2 overflow-x-auto">
        <table aria-label={`${pair.a} against ${pair.b}`} className="min-w-full text-xs">
          <thead className="text-left text-slate-500">
            <tr>
              <th className="px-2 py-1">Metric</th>
              <th className="px-2 py-1 text-right">A</th>
              <th className="px-2 py-1 text-right">B</th>
              <th className="px-2 py-1 text-right">A − B</th>
              <th className="px-2 py-1 text-right">Relative</th>
              <th className="px-2 py-1 text-right">p (adjusted)</th>
              <th className="px-2 py-1">Finding</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {pair.metrics.map((m) => (
              <tr key={m.metric}>
                <td className="px-2 py-1">{m.label}</td>
                <td className="px-2 py-1 text-right tabular-nums">{num(m.a_mean)}</td>
                <td className="px-2 py-1 text-right tabular-nums">{num(m.b_mean)}</td>
                <td className="px-2 py-1 text-right tabular-nums">{num(m.mean_difference)}</td>
                <td className="px-2 py-1 text-right tabular-nums">{pct(m.relative_difference)}</td>
                <td className="px-2 py-1 text-right tabular-nums">{pValue(m.p_adjusted)}</td>
                <td className="px-2 py-1">{FINDING[m.finding]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function BenchmarkView({ benchmark }: { benchmark: Benchmark }) {
  const b = benchmark;
  return (
    <section aria-label={`Benchmark ${b.scenario_id}`} className="space-y-2 rounded-xl border border-slate-200 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-semibold text-slate-900">
          {b.scenario_id} v{b.scenario_version} · {MODE_NAMES[b.candidate_mode]}
        </h4>
        <StatusPill tone={TIER_TONE[b.risk_tier]} label={`${humanize(b.risk_tier)} risk`} />
      </div>
      <table aria-label={`Ranking on ${b.scenario_id}`} className="min-w-full text-sm">
        <thead className="text-left text-xs text-slate-500">
          <tr>
            <th className="px-2 py-1">Rank</th>
            <th className="px-2 py-1">Tool</th>
            <th className="px-2 py-1 text-right">Successful (today's thresholds)</th>
            <th className="px-2 py-1 text-right">Preferred / beaten</th>
            <th className="px-2 py-1 text-right">Labour vs. own baseline</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {b.tools.map((t) => (
            <tr key={t.tool}>
              <td className="px-2 py-1 font-semibold">#{t.rank}</td>
              <td className="px-2 py-1">{t.tool}</td>
              <td className="px-2 py-1 text-right tabular-nums">
                {t.successful} of {t.experiments}
              </td>
              <td className="px-2 py-1 text-right tabular-nums">
                {t.preferred_in} / {t.not_preferred_in}
              </td>
              <td className="px-2 py-1 text-right tabular-nums">{pct(t.mean_relative_change.labour_hours)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="space-y-1">
        {b.pairs.map((p) => (
          <PairDetail key={`${p.a}|${p.b}`} pair={p} />
        ))}
      </div>
    </section>
  );
}

function CompareDialog({ onClose }: { onClose: () => void }) {
  const tools = useAiTools();
  const scenarios = useScenarios();
  const start = useStartComparison();
  const aiScenarios = Object.values(
    Object.fromEntries(
      [...(scenarios.data ?? [])]
        .filter((s) => s.modes.length > 1)
        .sort((a, b) => a.version - b.version)
        .map((s) => [s.scenario_id, s]),
    ),
  );
  const [scenarioId, setScenarioId] = useState("retail-onboarding");
  const scenario = aiScenarios.find((s) => s.scenario_id === scenarioId);
  const workflowId = scenario?.workflow_id ?? "WF-0001";
  const compatible = (tools.data?.items ?? []).filter((t) => t.status === "active" && t.compatible_workflows.includes(workflowId));
  const [chosen, setChosen] = useState<string[]>([]);
  const [name, setName] = useState("Tool comparison");
  const [mode, setMode] = useState<"ai_assisted" | "ai_automated">("ai_assisted");
  const [applications, setApplications] = useState("40");
  const [employees, setEmployees] = useState("12");
  const [seed, setSeed] = useState("42");
  const [replicates, setReplicates] = useState("3");
  const [submitted, setSubmitted] = useState(false);
  const whole = (v: string, lo: number, hi: number) => Number.isInteger(Number(v)) && v.trim() !== "" && Number(v) >= lo && Number(v) <= hi;
  const errors: Record<string, string | null> = {
    name: name.trim().length >= 3 ? null : "At least 3 characters.",
    tools: chosen.length >= 2 && chosen.length <= 5 ? null : "Choose 2 to 5 tools.",
    applications: whole(applications, 5, 10000) ? null : "5 – 10,000.",
    employees: whole(employees, 3, 500) ? null : "3 – 500.",
    seed: whole(seed, 0, 2 ** 31 - 1) ? null : "A whole number ≥ 0.",
    replicates: whole(replicates, 2, 30) ? null : "2 – 30.",
  };
  const valid = Object.values(errors).every((e) => e === null);
  const show = (k: string) => (submitted ? errors[k] : null);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (!valid) return;
    start.mutate(
      {
        name: name.trim(),
        scenario_id: scenarioId,
        tools: compatible.filter((t) => chosen.includes(t.id)).map((t) => ({ tool_id: t.tool_id, tool_version: t.tool_version })),
        candidate_mode: mode,
        applications: Number(applications),
        employees: Number(employees),
        seed: Number(seed),
        replicates: Number(replicates),
      },
      { onSuccess: onClose },
    );
  };
  return (
    <Modal title="Compare tools" onClose={onClose} wide>
      <form id="compare-tools" aria-label="Compare tools" onSubmit={submit} className="space-y-3">
        <p className="text-xs text-slate-500">
          Runs every chosen tool on the same scenario, seeds and sizes — one series each — so every pair is compared on
          identical workloads.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name" error={show("name")}>
            {(p) => <input {...p} className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />}
          </Field>
          <Field label="Scenario">
            {(p) => (
              <select
                {...p}
                className={inputClass}
                value={scenarioId}
                onChange={(e) => {
                  setScenarioId(e.target.value);
                  setChosen([]);
                }}
              >
                {aiScenarios.map((s) => (
                  <option key={s.scenario_id} value={s.scenario_id}>
                    {s.name}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Candidate configuration">
            {(p) => (
              <select {...p} className={inputClass} value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
                <option value="ai_assisted">{MODE_NAMES.ai_assisted}</option>
                <option value="ai_automated">{MODE_NAMES.ai_automated}</option>
              </select>
            )}
          </Field>
          <div className="grid grid-cols-4 gap-2">
            <Field label="Cases" error={show("applications")}>
              {(p) => <input {...p} type="number" className={inputClass} value={applications} onChange={(e) => setApplications(e.target.value)} />}
            </Field>
            <Field label="Staff" error={show("employees")}>
              {(p) => <input {...p} type="number" className={inputClass} value={employees} onChange={(e) => setEmployees(e.target.value)} />}
            </Field>
            <Field label="First seed" error={show("seed")}>
              {(p) => <input {...p} inputMode="numeric" className={inputClass} value={seed} onChange={(e) => setSeed(e.target.value)} />}
            </Field>
            <Field label="Seeds" error={show("replicates")}>
              {(p) => <input {...p} type="number" className={inputClass} value={replicates} onChange={(e) => setReplicates(e.target.value)} />}
            </Field>
          </div>
        </div>
        <fieldset className="rounded-lg border border-slate-200 p-3">
          <legend className="px-1 text-xs font-semibold text-slate-700">Tools ({workflowId})</legend>
          {compatible.length === 0 && <p className="text-xs text-slate-500">No active tool serves {workflowId}.</p>}
          <div className="grid gap-1 sm:grid-cols-2">
            {compatible.map((t) => (
              <label key={t.id} className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={chosen.includes(t.id)}
                  onChange={(e) => setChosen(e.target.checked ? [...chosen, t.id] : chosen.filter((c) => c !== t.id))}
                />
                {t.tool_name} {t.tool_version}
              </label>
            ))}
          </div>
          {show("tools") && <p className="mt-1 text-xs text-rose-600">{show("tools")}</p>}
        </fieldset>
      </form>
      <ErrorMessage error={start.error} className="mt-3" />
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" form="compare-tools" disabled={start.isPending}>
          <GitCompare aria-hidden className="h-4 w-4" /> Start comparison
        </Button>
      </div>
    </Modal>
  );
}

export function ToolComparisonPanel() {
  const { can } = useAuth();
  const comparison = useToolComparison();
  const [comparing, setComparing] = useState(false);
  const c = comparison.data;
  return (
    <Panel
      title="Head-to-head"
      subtitle="Tools compared only on matched workloads — same scenario, seed, sizes, cases and cost assumptions — with paired tests"
      actions={
        can("experiments:run") ? (
          <Button size="sm" onClick={() => setComparing(true)}>
            <GitCompare aria-hidden className="h-4 w-4" /> Compare tools
          </Button>
        ) : undefined
      }
    >
      <ErrorMessage error={comparison.error} />
      {c && (
        <div className="space-y-4">
          {c.benchmarks.length === 0 ? (
            <p className="text-sm text-slate-500">No benchmark has two tools yet. Compare tools to run them on the same workloads.</p>
          ) : (
            <>
              <div className="overflow-x-auto rounded-xl border border-slate-200">
                <table aria-label="Scoreboard across benchmarks" className="min-w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
                    <tr>
                      <th className="px-3 py-2">Tool</th>
                      <th className="px-3 py-2 text-right">Benchmarks</th>
                      <th className="px-3 py-2 text-right">Ranked first</th>
                      <th className="px-3 py-2 text-right">Successful</th>
                      <th className="px-3 py-2 text-right">Preferred / beaten</th>
                      <th className="px-3 py-2 text-right">Trade-off / no difference / identical</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {c.scoreboard.map((r) => (
                      <tr key={r.tool}>
                        <td className="px-3 py-2 font-medium">{r.tool}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{r.benchmarks}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{r.ranked_first}</td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {r.successful} of {r.experiments}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {r.preferred} / {r.not_preferred}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {r.trade_off} / {r.no_difference} / {r.identical}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {c.benchmarks.map((b) => (
                <BenchmarkView key={`${b.scenario_id}-${b.scenario_version}-${b.candidate_mode}`} benchmark={b} />
              ))}
            </>
          )}
          <p className="text-[11px] text-slate-500">Method: {c.method}</p>
        </div>
      )}
      {comparing && <CompareDialog onClose={() => setComparing(false)} />}
    </Panel>
  );
}
