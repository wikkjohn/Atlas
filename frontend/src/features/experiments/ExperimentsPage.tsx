import { BarChart3, Download, FlaskConical, Plus, RotateCcw } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { SyntheticDataBadge } from "@/components/SyntheticDataBadge";
import {
  ComparisonTable,
  CostTable,
  CriteriaList,
  MODE_NAMES,
  VerdictPill,
} from "@/features/experiments/ExperimentResults";
import { useAiTools } from "@/services/aiTools";
import { downloadReport, useCreateExperiment, useExperiment, useExperiments, useReEvaluate } from "@/services/experiments";
import { humanize } from "@/services/format";
import {
  type CostAssumptions,
  DEFAULT_COSTS,
  DEFAULT_THRESHOLDS,
  type ExperimentStatus,
  type SuccessThresholds,
} from "@/types/experiments";

const PAGE = 10;
const STATUS_TONE: Record<ExperimentStatus, Tone> = { running: "warn", completed: "good", failed: "bad" };

const COST_FIELDS: { key: keyof CostAssumptions; label: string; step: string }[] = [
  { key: "reviewer_cost_per_minute", label: "Reviewer cost per minute", step: "0.01" },
  { key: "ai_cost_per_invocation", label: "AI cost per invocation", step: "0.001" },
  { key: "infrastructure_cost_per_run", label: "Infrastructure per workload", step: "0.01" },
  { key: "infrastructure_cost_per_case", label: "Infrastructure per case", step: "0.001" },
  { key: "exception_handling_cost", label: "Cost per workflow exception", step: "0.01" },
  { key: "manual_escalation_cost", label: "Cost per manual escalation", step: "0.01" },
  { key: "oversight_sample_rate", label: "Oversight: share of automated decisions re-checked", step: "0.01" },
  { key: "oversight_minutes_per_sample", label: "Oversight: minutes per re-check", step: "0.1" },
  { key: "false_approval_cost", label: "Risk cost per false approval", step: "1" },
  { key: "false_rejection_cost", label: "Risk cost per false rejection", step: "1" },
];

const THRESHOLD_FIELDS: { key: keyof SuccessThresholds; label: string; step: string }[] = [
  { key: "min_improvement", label: "Minimum improvement (time, labour or cost)", step: "0.01" },
  { key: "max_accuracy_drop", label: "Maximum accuracy drop", step: "0.001" },
  { key: "max_false_approval_rate", label: "Maximum false approval rate", step: "0.01" },
  { key: "max_false_rejection_rate", label: "Maximum false rejection rate", step: "0.01" },
  { key: "max_error_rate", label: "Maximum error rate", step: "0.01" },
  { key: "max_policy_violations", label: "Maximum policy violations", step: "1" },
  { key: "regression_tolerance", label: "Regression tolerance", step: "0.01" },
];

const RATE_KEYS = new Set<string>([
  "oversight_sample_rate",
  "min_improvement",
  "max_accuracy_drop",
  "max_false_approval_rate",
  "max_false_rejection_rate",
  "max_error_rate",
  "regression_tolerance",
]);

// --- New experiment ---------------------------------------------------------------------------

function NewExperimentDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const tools = useAiTools();
  const create = useCreateExperiment();
  const compatible = (tools.data?.items ?? []).filter((t) => t.status === "active" && t.compatible_workflows.includes("WF-0001"));
  const [name, setName] = useState("KYC assistant vs. baseline");
  const [toolId, setToolId] = useState("");
  const [mode, setMode] = useState<"ai_assisted" | "ai_automated">("ai_automated");
  const [applications, setApplications] = useState("100");
  const [employees, setEmployees] = useState("25");
  const [seed, setSeed] = useState("42");
  const [costs, setCosts] = useState<Record<string, string>>(
    Object.fromEntries(COST_FIELDS.map((f) => [f.key, String(DEFAULT_COSTS[f.key])])),
  );
  const [thresholds, setThresholds] = useState<Record<string, string>>(
    Object.fromEntries(THRESHOLD_FIELDS.map((f) => [f.key, String(DEFAULT_THRESHOLDS[f.key])])),
  );
  const [currency, setCurrency] = useState(DEFAULT_COSTS.currency_label);
  const [submitted, setSubmitted] = useState(false);
  // Keyed by registered record so the chosen version is the one sent.
  const selectedTool = compatible.find((t) => t.id === toolId) ?? compatible[0];
  const tool = selectedTool?.tool_id ?? "";

  const numberError = (key: string, raw: string) => {
    const v = Number(raw);
    if (raw.trim() === "" || !Number.isFinite(v) || v < 0) return "A number ≥ 0.";
    if (RATE_KEYS.has(key) && v > 1) return "A share between 0 and 1.";
    if (key === "max_policy_violations" && !Number.isInteger(v)) return "A whole number.";
    return null;
  };
  const errors: Record<string, string | null> = {
    name: name.trim().length >= 3 ? null : "At least 3 characters.",
    tool: tool ? null : "Register an active tool compatible with WF-0001 first.",
    applications: Number(applications) >= 1 && Number(applications) <= 10000 && Number.isInteger(Number(applications)) ? null : "1 – 10,000.",
    employees: Number(employees) >= 3 && Number(employees) <= 500 && Number.isInteger(Number(employees)) ? null : "3 – 500.",
    seed: Number.isInteger(Number(seed)) && Number(seed) >= 0 && seed.trim() !== "" ? null : "A whole number ≥ 0.",
    ...Object.fromEntries(COST_FIELDS.map((f) => [f.key, numberError(f.key, costs[f.key] ?? "")])),
    ...Object.fromEntries(THRESHOLD_FIELDS.map((f) => [f.key, numberError(f.key, thresholds[f.key] ?? "")])),
  };
  const valid = Object.values(errors).every((e) => e === null);
  const show = (key: string) => (submitted ? errors[key] : null);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (!valid) return;
    create.mutate(
      {
        name: name.trim(),
        tool_id: tool,
        tool_version: selectedTool?.tool_version ?? null,
        candidate_mode: mode,
        profile: "custom",
        applications: Number(applications),
        employees: Number(employees),
        seed: Number(seed),
        costs: {
          ...DEFAULT_COSTS,
          ...Object.fromEntries(COST_FIELDS.map((f) => [f.key, Number(costs[f.key])])),
          currency_label: currency,
        },
        thresholds: Object.fromEntries(
          THRESHOLD_FIELDS.map((f) => [f.key, Number(thresholds[f.key])]),
        ) as unknown as SuccessThresholds,
      },
      { onSuccess: (e) => onCreated(e.id) },
    );
  };

  return (
    <Modal title="New experiment" onClose={onClose} wide>
      <form id="new-experiment" aria-label="New experiment" onSubmit={submit} className="space-y-4">
        <p className="text-xs text-slate-500">
          Runs the baseline (A) and the candidate on the same seeded applications and staff, one after the other, then
          evaluates them against the cost assumptions and success thresholds below. Defaults are illustrative.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name" error={show("name")}>
            {(p) => <input {...p} className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />}
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
          <div className="grid grid-cols-3 gap-2">
            <Field label="Applications" error={show("applications")}>
              {(p) => <input {...p} type="number" className={inputClass} value={applications} onChange={(e) => setApplications(e.target.value)} />}
            </Field>
            <Field label="Staff" error={show("employees")}>
              {(p) => <input {...p} type="number" className={inputClass} value={employees} onChange={(e) => setEmployees(e.target.value)} />}
            </Field>
            <Field label="Seed" error={show("seed")}>
              {(p) => <input {...p} inputMode="numeric" className={inputClass} value={seed} onChange={(e) => setSeed(e.target.value)} />}
            </Field>
          </div>
        </div>
        <fieldset className="rounded-lg border border-slate-200 p-3">
          <legend className="px-1 text-xs font-semibold text-slate-700">Cost assumptions</legend>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Currency label">
              {(p) => <input {...p} className={inputClass} value={currency} onChange={(e) => setCurrency(e.target.value)} />}
            </Field>
            {COST_FIELDS.map((f) => (
              <Field key={f.key} label={f.label} error={show(f.key)}>
                {(p) => (
                  <input
                    {...p}
                    type="number"
                    step={f.step}
                    className={inputClass}
                    value={costs[f.key]}
                    onChange={(e) => setCosts({ ...costs, [f.key]: e.target.value })}
                  />
                )}
              </Field>
            ))}
          </div>
        </fieldset>
        <details className="rounded-lg border border-slate-200 p-3">
          <summary className="cursor-pointer text-xs font-semibold text-slate-700">Success thresholds</summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {THRESHOLD_FIELDS.map((f) => (
              <Field key={f.key} label={f.label} error={show(f.key)}>
                {(p) => (
                  <input
                    {...p}
                    type="number"
                    step={f.step}
                    className={inputClass}
                    value={thresholds[f.key]}
                    onChange={(e) => setThresholds({ ...thresholds, [f.key]: e.target.value })}
                  />
                )}
              </Field>
            ))}
          </div>
        </details>
      </form>
      <ErrorMessage error={create.error} className="mt-3" />
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" form="new-experiment" disabled={create.isPending}>
          <FlaskConical aria-hidden className="h-4 w-4" /> Run experiment
        </Button>
      </div>
    </Modal>
  );
}

// --- Detail ---------------------------------------------------------------------------------

function ExperimentView({ id }: { id: string }) {
  const experiment = useExperiment(id);
  const reEvaluate = useReEvaluate(id);
  const [downloadError, setDownloadError] = useState<unknown>(null);
  const e = experiment.data;
  if (experiment.error) return <ErrorMessage error={experiment.error} />;
  if (!e) return <p className="text-sm text-slate-500">Loading…</p>;
  const download = (format: "markdown" | "json") => {
    setDownloadError(null);
    downloadReport(e.id, e.experiment_number, format).catch(setDownloadError);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold text-slate-900">
              Experiment #{e.experiment_number}: {e.name}
            </h2>
            <StatusPill tone={STATUS_TONE[e.status]} label={humanize(e.status)} />
            <VerdictPill verdict={e.verdict} />
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {e.tool_id} {e.tool_version} · {MODE_NAMES[e.candidate_mode]} vs. A — Baseline · {e.scenario_id} v
            {e.scenario_version} · configuration <span className="font-mono">{e.configuration_hash.slice(0, 12)}</span>
          </p>
        </div>
        {e.evaluation && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => download("markdown")}>
              <Download aria-hidden className="h-3.5 w-3.5" /> Report (.md)
            </Button>
            <Button size="sm" variant="secondary" onClick={() => download("json")}>
              <Download aria-hidden className="h-3.5 w-3.5" /> Data (.json)
            </Button>
            <Button size="sm" variant="secondary" disabled={reEvaluate.isPending} onClick={() => reEvaluate.mutate()}>
              <RotateCcw aria-hidden className="h-3.5 w-3.5" /> Re-evaluate
            </Button>
            <Link
              to={`/benchmarking?experiment=${e.id}`}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50"
            >
              <BarChart3 aria-hidden className="h-3.5 w-3.5" /> Benchmarking
            </Link>
          </div>
        )}
      </div>
      <ErrorMessage error={downloadError ?? reEvaluate.error} />
      {reEvaluate.data && (
        <p role="status" className="text-xs text-slate-600">
          {reEvaluate.data.matches
            ? `Re-evaluated from the stored raw measurements: identical result (digest ${reEvaluate.data.recomputed_digest.slice(0, 16)}).`
            : "Re-evaluation produced a different result — the evaluation is not reproducible."}
        </p>
      )}

      <section aria-label="Runs" className="grid gap-3 text-sm sm:grid-cols-2">
        {([["A — Baseline", e.baseline], [MODE_NAMES[e.candidate_mode], e.candidate]] as const).map(([label, run]) => (
          <div key={run.id} className="rounded-lg border border-slate-200 p-3">
            <div className="flex items-center justify-between">
              <Link className="font-medium text-navy-700 hover:underline" to={`/simulations?run=${run.id}`}>
                {label} — run #{run.run_number}
              </Link>
              <StatusPill tone={STATUS_TONE[run.status === "completed" ? "completed" : run.status === "failed" ? "failed" : "running"]} label={humanize(run.status)} />
            </div>
            {run.status === "running" && <p className="mt-1 text-xs text-slate-500">{run.percent_complete}% of cases finished</p>}
            {run.failure_reason && <p className="mt-1 text-xs text-rose-700">{run.failure_reason}</p>}
          </div>
        ))}
      </section>

      {e.status === "failed" && (
        <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
          The experiment could not be evaluated: {e.failure_reason}
        </div>
      )}

      {e.evaluation && (
        <>
          <section aria-label="Conclusion" className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-800">
            <h3 className="mb-1 text-sm font-semibold text-slate-900">Conclusion</h3>
            {e.evaluation.conclusion}
          </section>
          <section aria-label="Criteria" className="space-y-2">
            <h3 className="text-sm font-semibold text-slate-900">Success criteria</h3>
            <CriteriaList experiment={e} />
          </section>
          <section aria-label="Comparison" className="space-y-2">
            <h3 className="text-sm font-semibold text-slate-900">Baseline vs. candidate</h3>
            <ComparisonTable experiment={e} />
          </section>
          <section aria-label="Costs" className="space-y-2">
            <h3 className="text-sm font-semibold text-slate-900">Cost model</h3>
            <CostTable experiment={e} />
            <details className="text-xs text-slate-600">
              <summary className="cursor-pointer font-medium">Assumptions used</summary>
              <ul className="mt-2 grid gap-x-6 gap-y-0.5 sm:grid-cols-2">
                {(Object.keys(DEFAULT_COSTS) as (keyof CostAssumptions)[]).map((k) => (
                  <li key={k}>
                    {humanize(k)}: <span className="font-mono">{String(e.configuration.costs[k]) || "—"}</span>
                  </li>
                ))}
              </ul>
            </details>
          </section>
          <section aria-label="Raw measurements" className="text-xs text-slate-600">
            <details>
              <summary className="cursor-pointer text-sm font-semibold text-slate-900">Raw measurements</summary>
              <p className="mt-1">Read from what the runs recorded, stored apart from the derived results above.</p>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {e.measurements.map((m) => (
                  <pre key={m.role} className="max-h-72 overflow-auto rounded-lg bg-slate-50 p-2 text-[11px]">
                    {m.role}: {JSON.stringify(m.metrics, null, 2)}
                  </pre>
                ))}
              </div>
            </details>
          </section>
          <section aria-label="Limitations" className="text-xs text-slate-600">
            <h3 className="mb-1 text-sm font-semibold text-slate-900">Limitations</h3>
            <ul className="list-disc space-y-0.5 pl-5">
              {e.evaluation.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}

// --- Page ------------------------------------------------------------------------------------

export function ExperimentsPage() {
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const experiments = useExperiments(offset, PAGE);
  const selected = params.get("experiment") ?? experiments.data?.items[0]?.id ?? null;

  return (
    <div>
      <PageHeader
        title="Experiments"
        description="Compare an AI-supported configuration with the baseline on identical synthetic workloads, under stated cost assumptions and success criteria."
        actions={
          <>
            <SyntheticDataBadge />
            {can("experiments:run") && (
              <Button onClick={() => setCreating(true)}>
                <Plus aria-hidden className="h-4 w-4" /> New experiment
              </Button>
            )}
          </>
        }
      />
      <div className="grid gap-6 lg:grid-cols-[20rem_1fr]">
        <Panel title="Experiment registry">
          <ErrorMessage error={experiments.error} />
          {experiments.data?.items.length === 0 && <p className="text-sm text-slate-500">No experiments yet.</p>}
          <ul aria-label="Experiments" className="divide-y divide-slate-100">
            {(experiments.data?.items ?? []).map((x) => (
              <li key={x.id}>
                <button
                  type="button"
                  onClick={() => setParams({ experiment: x.id })}
                  aria-current={x.id === selected ? "true" : undefined}
                  className={`w-full px-2 py-2 text-left text-sm hover:bg-slate-50 ${x.id === selected ? "bg-slate-50" : ""}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-slate-900">
                      #{x.experiment_number} {x.name}
                    </span>
                    {x.verdict ? <VerdictPill verdict={x.verdict} /> : <StatusPill tone={STATUS_TONE[x.status]} label={humanize(x.status)} compact />}
                  </div>
                  <div className="text-xs text-slate-500">
                    {x.tool_id} {x.tool_version} · {MODE_NAMES[x.candidate_mode]}
                  </div>
                </button>
              </li>
            ))}
          </ul>
          {experiments.data && <Pagination total={experiments.data.total} limit={PAGE} offset={offset} onChange={setOffset} />}
        </Panel>
        <Panel title="Experiment details">
          {selected ? <ExperimentView key={selected} id={selected} /> : <p className="text-sm text-slate-500">Run an experiment to see its evaluation.</p>}
        </Panel>
      </div>
      {creating && (
        <NewExperimentDialog
          onClose={() => setCreating(false)}
          onCreated={(id) => {
            setCreating(false);
            setParams({ experiment: id });
          }}
        />
      )}
    </div>
  );
}
