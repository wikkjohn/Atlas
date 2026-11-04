import { Plus, Repeat } from "lucide-react";
import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { MODE_NAMES, VerdictPill } from "@/features/experiments/ExperimentResults";
import { useAiTools } from "@/services/aiTools";
import { useCreateSeries, useSeries, useSeriesList } from "@/services/experiments";
import { humanize } from "@/services/format";
import { useScenarios } from "@/services/simulations";
import type { ExperimentStatus, SeriesFinding, SeriesMetric } from "@/types/experiments";

const STATUS_TONE: Record<ExperimentStatus, Tone> = { running: "warn", completed: "good", failed: "bad" };
const FINDING: Record<SeriesFinding, { label: string; tone: Tone }> = {
  improved: { label: "Better", tone: "good" },
  worse: { label: "Worse", tone: "bad" },
  no_significant_difference: { label: "No significant difference", tone: "neutral" },
  too_few_seeds: { label: "Too few seeds", tone: "warn" },
  informational: { label: "Informational", tone: "neutral" },
};

const pct = (v: number | null) => (v === null ? "—" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);
const num = (v: number | null) => (v === null ? "—" : Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(3));
export const pValue = (p: number | null) => (p === null ? "—" : p < 0.001 ? "< 0.001" : p.toFixed(3));

/** The effect across seeds: one row per metric, with its interval and adjusted p-value. */
export function SeriesTable({ metrics, confidence }: { metrics: SeriesMetric[]; confidence: number }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table aria-label="Effect across seeds" className="min-w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
          <tr>
            <th className="px-3 py-2">Metric</th>
            <th className="px-3 py-2 text-right">Baseline (mean)</th>
            <th className="px-3 py-2 text-right">Candidate (mean)</th>
            <th className="px-3 py-2 text-right">Change</th>
            <th className="px-3 py-2 text-right">{Math.round(confidence * 100)}% interval</th>
            <th className="px-3 py-2 text-right">p (adjusted)</th>
            <th className="px-3 py-2">Finding</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {metrics.map((m) => (
            <tr key={m.metric}>
              <td className="px-3 py-2">{m.label}</td>
              <td className="px-3 py-2 text-right tabular-nums">{num(m.baseline_mean)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{num(m.candidate_mean)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{pct(m.relative_change)}</td>
              <td className="px-3 py-2 text-right text-xs tabular-nums">
                {m.relative_ci_low === null ? "—" : `${pct(m.relative_ci_low)} to ${pct(m.relative_ci_high)}`}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{pValue(m.p_adjusted)}</td>
              <td className="px-3 py-2">
                <StatusPill tone={FINDING[m.finding].tone} label={FINDING[m.finding].label} compact />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SeriesView({ id }: { id: string }) {
  const series = useSeries(id);
  const s = series.data;
  if (series.error) return <ErrorMessage error={series.error} />;
  if (!s) return <p className="text-sm text-slate-500">Loading…</p>;
  return (
    <section aria-label="Series details" className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-slate-900">
          #{s.series_number} {s.name}
        </h3>
        {s.verdict ? <VerdictPill verdict={s.verdict} /> : <StatusPill tone={STATUS_TONE[s.status]} label={humanize(s.status)} compact />}
      </div>
      <p className="text-xs text-slate-500">
        {s.tool_id} {s.tool_version} · {MODE_NAMES[s.candidate_mode]} · seeds {s.seeds.join(", ")} · {s.replicates_completed} of{" "}
        {s.seeds.length} replicates evaluated
      </p>
      {s.failure_reason && <p className="text-sm text-red-700">{s.failure_reason}</p>}
      {s.statistics && (
        <>
          <p className="text-sm text-slate-700">{s.statistics.conclusion}</p>
          <SeriesTable metrics={s.statistics.metrics} confidence={s.statistics.confidence} />
          <p className="text-xs text-slate-500">Method: {s.statistics.method}</p>
        </>
      )}
    </section>
  );
}

function NewSeriesDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const tools = useAiTools();
  const scenarios = useScenarios();
  const create = useCreateSeries();
  const aiScenarios = Object.values(
    Object.fromEntries(
      [...(scenarios.data ?? [])]
        .filter((x) => x.modes.length > 1)
        .sort((a, b) => a.version - b.version)
        .map((x) => [x.scenario_id, x]),
    ),
  );
  const [scenarioId, setScenarioId] = useState("retail-onboarding");
  const scenario = aiScenarios.find((x) => x.scenario_id === scenarioId) ?? aiScenarios[0];
  const workflowId = scenario?.workflow_id ?? "WF-0001";
  const compatible = (tools.data?.items ?? []).filter((t) => t.status === "active" && t.compatible_workflows.includes(workflowId));
  const [toolId, setToolId] = useState("");
  const selectedTool = compatible.find((t) => t.id === toolId) ?? compatible[0];
  const [name, setName] = useState("KYC assistant over five seeds");
  const [mode, setMode] = useState<"ai_assisted" | "ai_automated">("ai_assisted");
  const [applications, setApplications] = useState("100");
  const [employees, setEmployees] = useState("20");
  const [seed, setSeed] = useState("101");
  const [replicates, setReplicates] = useState("5");
  const [confidence, setConfidence] = useState("0.95");
  const [submitted, setSubmitted] = useState(false);

  const whole = (raw: string, low: number, high: number) => {
    const v = Number(raw);
    return raw.trim() !== "" && Number.isInteger(v) && v >= low && v <= high;
  };
  const errors: Record<string, string | null> = {
    name: name.trim().length >= 3 ? null : "At least 3 characters.",
    tool: selectedTool ? null : `Register an active tool compatible with ${workflowId} first.`,
    applications: whole(applications, 1, 10000) ? null : "1 – 10,000.",
    employees: whole(employees, 3, 500) ? null : "3 – 500.",
    seed: whole(seed, 0, 2 ** 31 - 1) ? null : "A whole number ≥ 0.",
    replicates: whole(replicates, 2, 30) ? null : "2 – 30 seeds.",
  };
  const valid = Object.values(errors).every((e) => e === null);
  const show = (key: string) => (submitted ? errors[key] : null);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (!valid || !selectedTool) return;
    create.mutate(
      {
        name: name.trim(),
        scenario_id: scenario?.scenario_id ?? "retail-onboarding",
        tool_id: selectedTool.tool_id,
        tool_version: selectedTool.tool_version,
        candidate_mode: mode,
        profile: "custom",
        applications: Number(applications),
        employees: Number(employees),
        seed: Number(seed),
        replicates: Number(replicates),
        confidence: Number(confidence),
      },
      { onSuccess: (s) => onCreated(s.id) },
    );
  };

  return (
    <Modal title="New series" onClose={onClose} wide>
      <form id="new-series" aria-label="New series" onSubmit={submit} className="space-y-4">
        <p className="text-xs text-slate-500">
          Runs the experiment once per seed (the first seed, the next, and so on), then tests the candidate's effect across
          the seeds: a confidence interval per metric and p-values adjusted for testing many metrics together. Default cost
          assumptions and thresholds apply.
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
                value={scenario?.scenario_id ?? ""}
                onChange={(e) => {
                  setScenarioId(e.target.value);
                  setToolId("");
                }}
              >
                {aiScenarios.map((x) => (
                  <option key={x.scenario_id} value={x.scenario_id}>
                    {x.name}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="AI tool" error={show("tool")}>
            {(p) => (
              <select {...p} className={inputClass} value={selectedTool?.id ?? ""} onChange={(e) => setToolId(e.target.value)}>
                {compatible.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.tool_name} {t.tool_version}
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
          <div className="grid grid-cols-2 gap-2">
            <Field label="Cases" error={show("applications")}>
              {(p) => <input {...p} type="number" className={inputClass} value={applications} onChange={(e) => setApplications(e.target.value)} />}
            </Field>
            <Field label="Staff" error={show("employees")}>
              {(p) => <input {...p} type="number" className={inputClass} value={employees} onChange={(e) => setEmployees(e.target.value)} />}
            </Field>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <Field label="First seed" error={show("seed")}>
              {(p) => <input {...p} inputMode="numeric" className={inputClass} value={seed} onChange={(e) => setSeed(e.target.value)} />}
            </Field>
            <Field label="Seeds" error={show("replicates")}>
              {(p) => <input {...p} type="number" className={inputClass} value={replicates} onChange={(e) => setReplicates(e.target.value)} />}
            </Field>
            <Field label="Confidence">
              {(p) => (
                <select {...p} className={inputClass} value={confidence} onChange={(e) => setConfidence(e.target.value)}>
                  <option value="0.9">90%</option>
                  <option value="0.95">95%</option>
                  <option value="0.99">99%</option>
                </select>
              )}
            </Field>
          </div>
        </div>
      </form>
      <ErrorMessage error={create.error} className="mt-3" />
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" form="new-series" disabled={create.isPending}>
          <Repeat aria-hidden className="h-4 w-4" /> Run series
        </Button>
      </div>
    </Modal>
  );
}

/** Repeated-seed series (Phase 77): an experiment over several seeds, with significance tests. */
export function SeriesPanel() {
  const { can } = useAuth();
  const list = useSeriesList();
  const [chosen, setChosen] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const selected = chosen ?? list.data?.items[0]?.id ?? null;
  return (
    <Panel
      title="Repeated-seed series"
      actions={
        can("experiments:run") && (
          <Button variant="secondary" onClick={() => setCreating(true)}>
            <Plus aria-hidden className="h-4 w-4" /> New series
          </Button>
        )
      }
    >
      <ErrorMessage error={list.error} />
      {list.data?.items.length === 0 && (
        <p className="text-sm text-slate-500">No series yet. A series repeats an experiment over several seeds and tests whether its effect holds.</p>
      )}
      <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
        <ul aria-label="Series" className="divide-y divide-slate-100">
          {(list.data?.items ?? []).map((x) => (
            <li key={x.id}>
              <button
                type="button"
                onClick={() => setChosen(x.id)}
                aria-current={x.id === selected ? "true" : undefined}
                className={`w-full px-2 py-2 text-left text-sm hover:bg-slate-50 ${x.id === selected ? "bg-slate-50" : ""}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-slate-900">
                    #{x.series_number} {x.name}
                  </span>
                  {x.verdict ? <VerdictPill verdict={x.verdict} /> : <StatusPill tone={STATUS_TONE[x.status]} label={humanize(x.status)} compact />}
                </div>
                <div className="text-xs text-slate-500">
                  {x.tool_id} · {MODE_NAMES[x.candidate_mode]} · {x.seeds.length} seeds
                </div>
              </button>
            </li>
          ))}
        </ul>
        {selected && <SeriesView key={selected} id={selected} />}
      </div>
      {creating && (
        <NewSeriesDialog
          onClose={() => setCreating(false)}
          onCreated={(id) => {
            setCreating(false);
            setChosen(id);
          }}
        />
      )}
    </Panel>
  );
}
