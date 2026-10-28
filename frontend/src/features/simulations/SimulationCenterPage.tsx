import { CheckCircle2, Dices, Play, RotateCcw, XCircle } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { SyntheticDataBadge } from "@/components/SyntheticDataBadge";
import { formatMilliseconds, formatTimestamp } from "@/features/dashboard/format";
import { humanize } from "@/services/format";
import {
  useProfiles,
  useRerunSimulation,
  useScenarios,
  useSimulationCases,
  useSimulationRun,
  useSimulationRuns,
  useStartSimulation,
} from "@/services/simulations";
import { useAiTools } from "@/services/aiTools";
import {
  type ExperimentMode,
  MODE_LABELS,
  type ProfileId,
  type SimulationRunDetail,
  type SimulationStatus,
} from "@/types/simulations";

const RUNS_PAGE = 10;
const CASES_PAGE = 20;
const MAX_SEED = 2 ** 53 - 1;

const STATUS_TONE: Record<SimulationStatus, Tone> = {
  queued: "neutral",
  running: "warn",
  completed: "good",
  failed: "bad",
};

const percent = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
const hours = (value: number | null | undefined) => {
  if (value === null || value === undefined) return "—";
  return value < 1 ? `${Math.round(value * 60)} min` : `${value.toFixed(1)} h`;
};

function randomSeed(): number {
  return Math.floor(Math.random() * 1_000_000_000);
}

// --- Start a run ----------------------------------------------------------------------------

function StartRunForm({ onStarted }: { onStarted: (id: string) => void }) {
  const scenarios = useScenarios();
  const profiles = useProfiles();
  const start = useStartSimulation();
  const tools = useAiTools();
  const [scenarioKey, setScenarioKey] = useState("");
  const [mode, setMode] = useState<ExperimentMode>("baseline");
  const [toolId, setToolId] = useState("");
  const [profile, setProfile] = useState<ProfileId>("small");
  const [seed, setSeed] = useState("42");
  const [applications, setApplications] = useState("50");
  const [employees, setEmployees] = useState("10");

  const selected = profiles.data?.find((p) => p.profile_id === profile);
  const scenarioList = scenarios.data ?? [];
  // Default: the latest version of the first scenario.
  const chosen =
    scenarioList.find((s) => `${s.scenario_id}@${s.version}` === scenarioKey) ??
    [...scenarioList].sort((a, b) => b.version - a.version)[0];
  const modes = chosen?.modes ?? ["baseline"];
  const effectiveMode: ExperimentMode = modes.includes(mode) ? mode : "baseline";
  const compatibleTools = (tools.data?.items ?? []).filter(
    (t) => t.status === "active" && chosen && t.compatible_workflows.includes(chosen.workflow_id),
  );
  const selectedTool = compatibleTools.find((t) => t.id === toolId) ?? compatibleTools[0];
  const toolIdValue = selectedTool?.tool_id ?? "";
  const needsTool = effectiveMode !== "baseline";
  const seedValue = Number(seed);
  const seedError =
    seed.trim() === "" || !Number.isInteger(seedValue) || seedValue < 0 || seedValue > MAX_SEED
      ? "A whole number from 0 upwards."
      : null;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (seedError || !chosen || (needsTool && !toolIdValue)) return;
    start.mutate(
      {
        scenario_id: chosen.scenario_id,
        scenario_version: chosen.version,
        mode: effectiveMode,
        tool_id: needsTool ? toolIdValue : null,
        tool_version: needsTool ? (selectedTool?.tool_version ?? null) : null,
        profile,
        seed: seedValue,
        applications: profile === "custom" ? Number(applications) : null,
        employees: profile === "custom" ? Number(employees) : null,
      },
      { onSuccess: (run) => onStarted(run.id) },
    );
  };

  return (
    <form aria-label="Start a simulation" onSubmit={submit} className="space-y-4">
      <Field label="Scenario">
        {(props) => (
          <select
            {...props}
            className={inputClass}
            value={chosen ? `${chosen.scenario_id}@${chosen.version}` : ""}
            onChange={(e) => setScenarioKey(e.target.value)}
          >
            {scenarioList.map((s) => (
              <option key={`${s.scenario_id}@${s.version}`} value={`${s.scenario_id}@${s.version}`}>
                {s.name} (v{s.version}, {s.workflow_id} v{s.workflow_version})
              </option>
            ))}
          </select>
        )}
      </Field>
      {modes.length > 1 && (
        <Field label="Mode" hint="All modes use the same applications and staff for a given seed.">
          {(props) => (
            <select
              {...props}
              className={inputClass}
              value={effectiveMode}
              onChange={(e) => setMode(e.target.value as ExperimentMode)}
            >
              {modes.map((m) => (
                <option key={m} value={m}>
                  {MODE_LABELS[m]}
                </option>
              ))}
            </select>
          )}
        </Field>
      )}
      {needsTool && (
        <Field
          label="AI tool"
          error={compatibleTools.length === 0 ? "No active tool is compatible with this workflow." : null}
        >
          {(props) => (
            <select {...props} className={inputClass} value={selectedTool?.id ?? ""} onChange={(e) => setToolId(e.target.value)}>
              {compatibleTools.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.tool_name} {t.tool_version}
                </option>
              ))}
            </select>
          )}
        </Field>
      )}
      <Field
        label="Workload"
        hint={
          profile === "custom"
            ? "Choose the number of applications and simulated staff."
            : selected
              ? `${selected.applications.toLocaleString()} applications · ${selected.customers.toLocaleString()} customers · ${selected.employees.toLocaleString()} staff${selected.runnable ? "" : ` — ${selected.note}`}`
              : undefined
        }
      >
        {(props) => (
          <select
            {...props}
            className={inputClass}
            value={profile}
            onChange={(e) => setProfile(e.target.value as ProfileId)}
          >
            {(profiles.data ?? []).map((p) => (
              <option key={p.profile_id} value={p.profile_id} disabled={!p.runnable}>
                {p.name}
                {p.runnable ? "" : " (target only — not runnable)"}
              </option>
            ))}
            <option value="custom">Custom size</option>
          </select>
        )}
      </Field>
      {profile === "custom" && (
        <div className="grid grid-cols-2 gap-3">
          <Field label="Applications" hint="1 – 10,000">
            {(props) => (
              <input
                {...props}
                type="number"
                min={1}
                max={10000}
                className={inputClass}
                value={applications}
                onChange={(e) => setApplications(e.target.value)}
              />
            )}
          </Field>
          <Field label="Simulated staff" hint="3 – 500">
            {(props) => (
              <input
                {...props}
                type="number"
                min={3}
                max={500}
                className={inputClass}
                value={employees}
                onChange={(e) => setEmployees(e.target.value)}
              />
            )}
          </Field>
        </div>
      )}
      <Field label="Random seed" hint="The same seed reproduces the same run." error={seedError}>
        {(props) => (
          <div className="flex gap-2">
            <input
              {...props}
              inputMode="numeric"
              className={inputClass}
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
            />
            <Button variant="secondary" aria-label="Pick a random seed" onClick={() => setSeed(String(randomSeed()))}>
              <Dices aria-hidden className="h-4 w-4" />
            </Button>
          </div>
        )}
      </Field>
      <Button
        type="submit"
        className="w-full"
        disabled={start.isPending || Boolean(seedError) || (needsTool && !toolIdValue)}
      >
        <Play aria-hidden className="h-4 w-4" /> Start run
      </Button>
      <ErrorMessage error={start.error} />
    </form>
  );
}

// --- Run detail -----------------------------------------------------------------------------

function Metric({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-lg font-semibold text-slate-900">{value}</dd>
      {hint && <dd className="text-[11px] text-slate-500">{hint}</dd>}
    </div>
  );
}

function Progress({ run }: { run: SimulationRunDetail }) {
  const p = run.progress;
  return (
    <div className="space-y-2">
      <div
        role="progressbar"
        aria-label={`Run #${run.run_number} progress`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={run.percent_complete}
        className="h-2 overflow-hidden rounded-full bg-slate-100"
      >
        <div className="h-full bg-navy-700 transition-all" style={{ width: `${run.percent_complete}%` }} />
      </div>
      <p className="text-xs text-slate-600">
        {p.cases_completed ?? 0} of {p.cases_total ?? run.applications} cases finished · {p.cases_started ?? 0}{" "}
        started · {p.events_processed ?? 0} events · simulated time {formatTimestamp(p.simulated_now)}
      </p>
    </div>
  );
}

function Cases({ runId }: { runId: string }) {
  const [offset, setOffset] = useState(0);
  const [mismatched, setMismatched] = useState(false);
  const cases = useSimulationCases(runId, { offset, limit: CASES_PAGE, mismatched }, true);
  return (
    <div>
      <label className="mb-2 flex items-center gap-2 text-xs text-slate-600">
        <input
          type="checkbox"
          checked={mismatched}
          onChange={(e) => {
            setMismatched(e.target.checked);
            setOffset(0);
          }}
        />
        Only cases whose outcome differs from the ground truth
      </label>
      <ErrorMessage error={cases.error} />
      <div className="overflow-x-auto rounded-xl border border-slate-200">
        <table aria-label="Case results" className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="px-3 py-2">#</th>
              <th className="px-3 py-2">Case type</th>
              <th className="px-3 py-2">Expected</th>
              <th className="px-3 py-2">Outcome</th>
              <th className="px-3 py-2">Risk</th>
              <th className="px-3 py-2">AI advice</th>
              <th className="px-3 py-2 text-right">Reviews</th>
              <th className="px-3 py-2 text-right">Queue wait</th>
              <th className="px-3 py-2 text-right">Cycle time</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {(cases.data?.items ?? []).map((c) => (
              <tr key={c.case_index}>
                <td className="px-3 py-2 font-mono text-xs text-slate-500">{c.case_index}</td>
                <td className="px-3 py-2">{humanize(c.kind)}</td>
                <td className="px-3 py-2">{humanize(c.expected_outcome)}</td>
                <td className="px-3 py-2">
                  <span className="inline-flex items-center gap-1">
                    {c.matches_ground_truth ? (
                      <CheckCircle2 aria-label="Matches ground truth" className="h-3.5 w-3.5 text-emerald-600" />
                    ) : (
                      <XCircle aria-label="Differs from ground truth" className="h-3.5 w-3.5 text-rose-600" />
                    )}
                    {c.outcome ? humanize(c.outcome) : humanize(c.status)}
                  </span>
                </td>
                <td className="px-3 py-2">{c.risk_rating ? humanize(c.risk_rating) : "—"}</td>
                <td className="px-3 py-2">
                  {c.ai_recommendation
                    ? humanize(c.ai_recommendation)
                    : c.ai_status
                      ? humanize(c.ai_status)
                      : "—"}
                  {c.automated && " · automated"}
                </td>
                <td className="px-3 py-2 text-right">{c.manual_reviews}</td>
                <td className="px-3 py-2 text-right">{c.queue_wait_minutes} min</td>
                <td className="px-3 py-2 text-right">{hours(c.cycle_hours)}</td>
              </tr>
            ))}
            {cases.data && cases.data.items.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-6 text-center text-sm text-slate-500">
                  No cases match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {cases.data && (
        <Pagination total={cases.data.total} limit={CASES_PAGE} offset={offset} onChange={setOffset} />
      )}
    </div>
  );
}

function RunDetail({ id, onSelect }: { id: string; onSelect: (id: string) => void }) {
  const { can } = useAuth();
  const run = useSimulationRun(id);
  const rerun = useRerunSimulation();
  if (run.error) return <ErrorMessage error={run.error} />;
  const r = run.data;
  if (!r) return <p className="text-sm text-slate-500">Loading…</p>;
  const res = r.results;
  const running = r.status === "queued" || r.status === "running";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold text-slate-900">Run #{r.run_number}</h2>
            <StatusPill tone={STATUS_TONE[r.status]} label={humanize(r.status)} />
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {MODE_LABELS[r.mode]}
            {r.tool_id && ` with ${r.tool_id} ${r.tool_version}`} · {r.scenario_id} v{r.scenario_version} ·{" "}
            {r.workflow_id} v{r.workflow_version} · {humanize(r.profile)} ·{" "}
            {r.applications.toLocaleString()} applications · {r.employees} staff · seed{" "}
            <span className="font-mono">{r.seed}</span>
          </p>
        </div>
        {can("simulations:run") && !running && (
          <Button
            variant="secondary"
            size="sm"
            disabled={rerun.isPending}
            onClick={() => rerun.mutate(r.id, { onSuccess: (next) => onSelect(next.id) })}
          >
            <RotateCcw aria-hidden className="h-3.5 w-3.5" /> Run again with this seed
          </Button>
        )}
      </div>
      <ErrorMessage error={rerun.error} />

      {running && <Progress run={r} />}
      {r.status === "failed" && (
        <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
          <p className="font-medium">The run failed.</p>
          <p className="mt-1">{r.failure_reason}</p>
        </div>
      )}

      {res && (
        <>
          <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <Metric label="Cases completed" value={`${res.completed} / ${res.cases}`} />
            <Metric label="Approved" value={res.outcomes.approved ?? 0} />
            <Metric label="Rejected" value={res.outcomes.rejected ?? 0} />
            <Metric
              label="Decision accuracy"
              value={percent(res.ground_truth.accuracy)}
              hint={`${res.ground_truth.false_approvals} false approvals · ${res.ground_truth.false_rejections} false rejections`}
            />
            <Metric label="Straight-through" value={percent(res.straight_through_rate)} hint="No manual review" />
            <Metric
              label="Manual reviews"
              value={res.manual_reviews}
              hint={`${hours(res.review_labor_hours)} of reviewer time`}
            />
            <Metric
              label="Cycle time"
              value={hours(res.cycle_time_hours.p50)}
              hint={`median · p95 ${hours(res.cycle_time_hours.p95)}`}
            />
            <Metric
              label="Review queue wait"
              value={hours(res.review_queue_wait_hours.avg)}
              hint={`average · p95 ${hours(res.review_queue_wait_hours.p95)} · ${res.overdue_tasks} overdue`}
            />
          </dl>

          {res.ai && res.ai.mode !== "off" && (
            <section aria-label="AI tool behaviour" className="rounded-lg border border-slate-200 p-3 text-xs text-slate-600">
              <h3 className="mb-1 text-sm font-semibold text-slate-900">AI tool behaviour</h3>
              <p>
                {res.ai.invocations} invocations · {res.ai.failed_invocations} failed or blocked (
                {Object.entries(res.ai.invocation_statuses)
                  .map(([s, n]) => `${humanize(s)} ${n}`)
                  .join(", ") || "none"}
                )
              </p>
              <p>
                Recommendations:{" "}
                {Object.entries(res.ai.recommendations)
                  .map(([k, n]) => `${humanize(k)} ${n}`)
                  .join(" · ") || "none"}{" "}
                · accuracy of approve/reject recommendations {percent(res.ai.recommendation_accuracy)}
              </p>
              <p>Approved by the policy engine without a person: {res.ai.automated_approvals}</p>
            </section>
          )}

          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table aria-label="Outcomes by case type" className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
                <tr>
                  <th className="px-3 py-2">Case type</th>
                  <th className="px-3 py-2 text-right">Cases</th>
                  <th className="px-3 py-2 text-right">Approved</th>
                  <th className="px-3 py-2 text-right">Rejected</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {Object.entries(res.by_kind).map(([kind, row]) => (
                  <tr key={kind}>
                    <td className="px-3 py-2">{humanize(kind)}</td>
                    <td className="px-3 py-2 text-right">{row.cases}</td>
                    <td className="px-3 py-2 text-right">{row.approved}</td>
                    <td className="px-3 py-2 text-right">{row.rejected}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <section aria-label="Execution and reproducibility" className="grid gap-3 text-xs text-slate-600 sm:grid-cols-2">
            <div className="rounded-lg border border-slate-200 p-3">
              <h3 className="mb-1 text-sm font-semibold text-slate-900">Execution</h3>
              <p>
                {res.execution.events_processed.toLocaleString()} simulated events ·{" "}
                {res.execution.workflow_steps_completed.toLocaleString()} workflow steps
              </p>
              <p>
                Wall time {formatMilliseconds(res.execution.wall_ms)} · {res.execution.cases_per_second ?? "—"} cases/s
              </p>
              <p>
                Simulated {formatTimestamp(r.simulated_start)} → {formatTimestamp(r.simulated_end)} (
                {hours(res.simulated_hours)})
              </p>
            </div>
            <div className="rounded-lg border border-slate-200 p-3">
              <h3 className="mb-1 text-sm font-semibold text-slate-900">Reproducibility</h3>
              <p>
                Software {r.software_version} · config <span className="font-mono">{r.config_hash.slice(0, 12)}</span>
              </p>
              <p>
                Result digest <span className="font-mono">{r.result_digest?.slice(0, 16)}</span>
              </p>
              {r.reproductions.length === 0 ? (
                <p className="mt-1">No other run with this scenario, seed, configuration and software yet.</p>
              ) : (
                <ul className="mt-1 space-y-0.5">
                  {r.reproductions.map((p) => (
                    <li key={p.id} className="flex items-center gap-1">
                      {p.matches ? (
                        <CheckCircle2 aria-hidden className="h-3.5 w-3.5 text-emerald-600" />
                      ) : (
                        <XCircle aria-hidden className="h-3.5 w-3.5 text-rose-600" />
                      )}
                      Run #{p.run_number}: {p.matches ? "identical results" : "results differ"}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          <Cases runId={r.id} />
        </>
      )}
    </div>
  );
}

// --- Page -----------------------------------------------------------------------------------

export function SimulationCenterPage() {
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const selected = params.get("run");
  const [offset, setOffset] = useState(0);
  const runs = useSimulationRuns(offset, RUNS_PAGE);
  const select = (id: string) => setParams({ run: id });

  return (
    <div>
      <PageHeader
        title="Simulation Center"
        description="Run seeded, reproducible workloads of synthetic customers and staff through the real workflow engine on simulated time."
        actions={<SyntheticDataBadge />}
      />
      <div className="grid gap-6 lg:grid-cols-[20rem_1fr]">
        <div className="space-y-6">
          {can("simulations:run") ? (
            <Panel title="New run" subtitle="One run executes at a time.">
              <StartRunForm onStarted={select} />
            </Panel>
          ) : (
            <Panel title="New run">
              <p className="text-sm text-slate-500">Your role can review runs but not start them.</p>
            </Panel>
          )}
          <Panel title="Runs">
            <ErrorMessage error={runs.error} />
            {runs.data && runs.data.items.length === 0 && (
              <p className="text-sm text-slate-500">No simulation has been run yet.</p>
            )}
            <ul aria-label="Simulation runs" className="divide-y divide-slate-100">
              {(runs.data?.items ?? []).map((run) => (
                <li key={run.id}>
                  <button
                    type="button"
                    onClick={() => select(run.id)}
                    aria-current={run.id === selected ? "true" : undefined}
                    className={`w-full px-2 py-2 text-left text-sm hover:bg-slate-50 ${run.id === selected ? "bg-slate-50" : ""}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-slate-900">Run #{run.run_number}</span>
                      <StatusPill tone={STATUS_TONE[run.status]} label={humanize(run.status)} />
                    </div>
                    <div className="text-xs text-slate-500">
                      {MODE_LABELS[run.mode]} · {run.applications.toLocaleString()} apps · seed {run.seed}
                      {run.status === "running" && ` · ${run.percent_complete}%`}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
            {runs.data && (
              <Pagination total={runs.data.total} limit={RUNS_PAGE} offset={offset} onChange={setOffset} />
            )}
          </Panel>
        </div>
        <Panel title="Run details">
          {selected ? (
            <RunDetail id={selected} onSelect={select} />
          ) : (
            <p className="text-sm text-slate-500">Select a run, or start one, to see its progress and outcomes.</p>
          )}
        </Panel>
      </div>
    </div>
  );
}
