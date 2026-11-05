import { Layers, Plus } from "lucide-react";
import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { MODE_NAMES, VerdictPill } from "@/features/experiments/ExperimentResults";
import { pValue } from "@/features/experiments/SeriesPanel";
import { TIER_TONE } from "@/features/experiments/ThresholdsPanel";
import { useCreatePortfolio, usePortfolio, usePortfolioReassessment, usePortfolios } from "@/services/experiments";
import { humanize } from "@/services/format";
import { type ExperimentStatus, type PortfolioMetric, RISK_TIERS } from "@/types/experiments";

const STATUS_TONE: Record<ExperimentStatus, Tone> = { running: "warn", completed: "good", failed: "bad" };
const FINDING: Record<PortfolioMetric["finding"], { label: string; tone: Tone }> = {
  improved: { label: "Better", tone: "good" },
  worse: { label: "Worse", tone: "bad" },
  no_significant_difference: { label: "No significant difference", tone: "neutral" },
  too_few_cells: { label: "Too few cells", tone: "warn" },
};
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`);
const DEFAULT_FAMILY = "agb-review-assistants";

/** The cells re-judged under each scenario's thresholds in force now (Phase 80). */
function UnderScenarioThresholds({ id }: { id: string }) {
  const reassess = usePortfolioReassessment(id);
  const r = reassess.data;
  return (
    <section aria-label="Under scenario thresholds" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" disabled={reassess.isPending} onClick={() => reassess.mutate()}>
          Judge each cell by its scenario's thresholds
        </Button>
        {r && (
          <span className="flex items-center gap-2 text-xs text-slate-600">
            {r.cell_verdicts.successful} of {r.cells.length} cells successful (stored:{" "}
            {r.stored_cell_verdicts?.successful ?? "—"}) <VerdictPill verdict={r.verdict} />
          </span>
        )}
      </div>
      <ErrorMessage error={reassess.error} />
      {r && (
        <>
          <table aria-label="Cells by risk tier" className="text-xs">
            <thead className="text-left text-slate-500">
              <tr>
                <th className="pr-4 py-1">Risk tier</th>
                <th className="pr-4 py-1 text-right">Cells</th>
                <th className="pr-4 py-1 text-right">Successful now</th>
                <th className="pr-4 py-1 text-right">Stored</th>
              </tr>
            </thead>
            <tbody>
              {RISK_TIERS.filter((t) => r.by_tier[t]).map((t) => (
                <tr key={t}>
                  <td className="pr-4 py-1">
                    <StatusPill tone={TIER_TONE[t]} label={humanize(t)} />
                  </td>
                  <td className="pr-4 py-1 text-right">{r.by_tier[t]?.cells}</td>
                  <td className="pr-4 py-1 text-right">{r.by_tier[t]?.successful}</td>
                  <td className="pr-4 py-1 text-right">{r.by_tier[t]?.before}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {r.cells.some((c) => c.verdict !== c.stored_verdict) && (
            <p className="text-xs text-slate-600">
              Changed:{" "}
              {r.cells
                .filter((c) => c.verdict !== c.stored_verdict)
                .map((c) => `${c.scenario_id} (${c.country}) → ${humanize(c.verdict)}`)
                .join("; ")}
            </p>
          )}
          <p className="text-[11px] text-slate-500">{r.method}</p>
        </>
      )}
    </section>
  );
}

function PortfolioView({ id }: { id: string }) {
  const portfolio = usePortfolio(id);
  const [breakdown, setBreakdown] = useState("labour_hours");
  const p = portfolio.data;
  if (portfolio.error) return <ErrorMessage error={portfolio.error} />;
  if (!p) return <p className="text-sm text-slate-500">Loading…</p>;
  const stats = p.statistics;
  const chosen = stats?.metrics.find((m) => m.metric === breakdown) ?? stats?.metrics[0];
  const skipped = p.configuration.plan?.skipped ?? [];
  return (
    <section aria-label="Portfolio details" className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-slate-900">
          #{p.portfolio_number} {p.name}
        </h3>
        {p.verdict ? <VerdictPill verdict={p.verdict} /> : <StatusPill tone={STATUS_TONE[p.status]} label={humanize(p.status)} compact />}
      </div>
      <p className="text-xs text-slate-500">
        Family {p.family} · {MODE_NAMES[p.candidate_mode]} · countries {p.countries.join(", ")} · {p.seeds.length} seeds per cell ·{" "}
        {p.cells_completed} of {p.cells} cells evaluated
        {stats && ` · ${stats.workflows} workflows, ${stats.departments.length} departments`}
      </p>
      {p.failure_reason && <p className="text-sm text-red-700">{p.failure_reason}</p>}
      {stats && (
        <>
          <p className="text-sm text-slate-700">{stats.conclusion}</p>
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table aria-label="Effect across cells" className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
                <tr>
                  <th className="px-3 py-2">Metric</th>
                  <th className="px-3 py-2 text-right">Mean change per workflow</th>
                  <th className="px-3 py-2 text-right">{Math.round(stats.confidence * 100)}% interval</th>
                  <th className="px-3 py-2 text-right">p (adjusted)</th>
                  <th className="px-3 py-2 text-right">Cells better / worse / same</th>
                  <th className="px-3 py-2">Finding</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {stats.metrics.map((m) => (
                  <tr key={m.metric}>
                    <td className="px-3 py-2">{m.label}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{pct(m.mean_relative_change)}</td>
                    <td className="px-3 py-2 text-right text-xs tabular-nums">{m.ci_low === null ? "—" : `${pct(m.ci_low)} to ${pct(m.ci_high)}`}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{pValue(m.p_adjusted)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {m.cell_findings.improved} / {m.cell_findings.worse} / {m.cell_findings.no_significant_difference}
                    </td>
                    <td className="px-3 py-2">
                      <StatusPill tone={FINDING[m.finding].tone} label={FINDING[m.finding].label} compact />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {chosen && (
            <div className="space-y-2">
              <Field label="Breakdown of">
                {(f) => (
                  <select {...f} className={`${inputClass} max-w-xs`} value={chosen.metric} onChange={(e) => setBreakdown(e.target.value)}>
                    {stats.metrics.map((m) => (
                      <option key={m.metric} value={m.metric}>
                        {m.label}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
              <div className="grid gap-3 md:grid-cols-2">
                <table aria-label="By department" className="min-w-full text-sm">
                  <thead className="text-left text-xs text-slate-500 uppercase">
                    <tr>
                      <th className="px-2 py-1">Department</th>
                      <th className="px-2 py-1 text-right">Cells</th>
                      <th className="px-2 py-1 text-right">Mean change</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {chosen.by_department.map((d) => (
                      <tr key={d.department}>
                        <td className="px-2 py-1">{d.department}</td>
                        <td className="px-2 py-1 text-right">{d.cells}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{pct(d.mean_relative_change)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <table aria-label="By country" className="min-w-full text-sm">
                  <thead className="text-left text-xs text-slate-500 uppercase">
                    <tr>
                      <th className="px-2 py-1">Country</th>
                      <th className="px-2 py-1 text-right">Cells</th>
                      <th className="px-2 py-1 text-right">Mean change</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {chosen.by_country.map((c) => (
                      <tr key={c.country}>
                        <td className="px-2 py-1">{c.country}</td>
                        <td className="px-2 py-1 text-right">{c.cells}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{pct(c.mean_relative_change)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          <p className="text-xs text-slate-500">Method: {stats.method}</p>
          <UnderScenarioThresholds id={p.id} />
        </>
      )}
      {skipped.length > 0 && (
        <details className="text-xs text-slate-600">
          <summary className="cursor-pointer">{skipped.length} scenario(s) not in the portfolio</summary>
          <ul className="mt-1 list-disc pl-5">
            {skipped.map((s) => (
              <li key={s.scenario_id}>
                {s.scenario_id}: {s.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function NewPortfolioDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const create = useCreatePortfolio();
  const [name, setName] = useState("Review assistants across the bank");
  const [family, setFamily] = useState(DEFAULT_FAMILY);
  const [mode, setMode] = useState<"ai_assisted" | "ai_automated">("ai_assisted");
  const [countries, setCountries] = useState("GB, US, JP");
  const [applications, setApplications] = useState("40");
  const [employees, setEmployees] = useState("20");
  const [replicates, setReplicates] = useState("3");
  // Phase 83: optionally only some scenarios (e.g. retail-overdrafts-country, whose cells
  // each run their country's own workflow).
  const [scenarios, setScenarios] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const scenarioIds = scenarios
    .split(/[\s,]+/)
    .map((c) => c.trim())
    .filter(Boolean);
  const codes = countries
    .split(/[\s,]+/)
    .map((c) => c.trim().toUpperCase())
    .filter(Boolean);
  const whole = (raw: string, low: number, high: number) => {
    const v = Number(raw);
    return raw.trim() !== "" && Number.isInteger(v) && v >= low && v <= high;
  };
  const errors: Record<string, string | null> = {
    name: name.trim().length >= 3 ? null : "At least 3 characters.",
    family: family.trim().length >= 3 ? null : "A tool family.",
    countries:
      codes.length >= 1 && codes.length <= 150 && codes.every((c) => /^[A-Z]{2}$/.test(c)) && new Set(codes).size === codes.length
        ? null
        : "1 – 150 different country codes, e.g. GB, US.",
    scenarios: scenarioIds.every((id) => /^[a-z0-9-]+$/.test(id)) ? null : "Scenario ids, e.g. retail-overdrafts-country.",
    applications: whole(applications, 5, 10000) ? null : "5 – 10,000.",
    employees: whole(employees, 3, 500) ? null : "3 – 500.",
    replicates: whole(replicates, 2, 30) ? null : "2 – 30 seeds.",
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
        family: family.trim(),
        candidate_mode: mode,
        countries: codes,
        applications: Number(applications),
        employees: Number(employees),
        seed: 42,
        replicates: Number(replicates),
        ...(scenarioIds.length > 0 ? { scenario_ids: scenarioIds } : {}),
      },
      { onSuccess: (p) => onCreated(p.id) },
    );
  };
  return (
    <Modal title="New portfolio" onClose={onClose} wide>
      <form id="new-portfolio" aria-label="New portfolio" onSubmit={submit} className="space-y-4">
        <p className="text-xs text-slate-500">
          Runs a repeated-seed series for every scenario a tool of the family serves, in each country, then pools the cells: the mean
          change per cell with an interval, and how many cells got better or worse. Default cost assumptions and thresholds apply.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name" error={show("name")}>
            {(p) => <input {...p} className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />}
          </Field>
          <Field label="Tool family" error={show("family")}>
            {(p) => <input {...p} className={inputClass} value={family} onChange={(e) => setFamily(e.target.value)} />}
          </Field>
          <Field label="Candidate configuration">
            {(p) => (
              <select {...p} className={inputClass} value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
                <option value="ai_assisted">{MODE_NAMES.ai_assisted}</option>
                <option value="ai_automated">{MODE_NAMES.ai_automated}</option>
              </select>
            )}
          </Field>
          <Field label="Countries" error={show("countries")}>
            {(p) => <input {...p} className={inputClass} value={countries} onChange={(e) => setCountries(e.target.value)} />}
          </Field>
          <Field
            label="Only these scenarios (optional)"
            error={show("scenarios")}
            hint="A templated scenario runs each country's own workflow; its variants must be generated."
          >
            {(p) => <input {...p} className={inputClass} value={scenarios} onChange={(e) => setScenarios(e.target.value)} />}
          </Field>
          <div className="grid grid-cols-3 gap-2 sm:col-span-2">
            <Field label="Cases" error={show("applications")}>
              {(p) => <input {...p} type="number" className={inputClass} value={applications} onChange={(e) => setApplications(e.target.value)} />}
            </Field>
            <Field label="Staff" error={show("employees")}>
              {(p) => <input {...p} type="number" className={inputClass} value={employees} onChange={(e) => setEmployees(e.target.value)} />}
            </Field>
            <Field label="Seeds per cell" error={show("replicates")}>
              {(p) => <input {...p} type="number" className={inputClass} value={replicates} onChange={(e) => setReplicates(e.target.value)} />}
            </Field>
          </div>
        </div>
      </form>
      <ErrorMessage error={create.error} className="mt-3" />
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" form="new-portfolio" disabled={create.isPending}>
          <Layers aria-hidden className="h-4 w-4" /> Run portfolio
        </Button>
      </div>
    </Modal>
  );
}

/** Portfolios (Phase 78): a tool family across workflows, departments and countries. */
export function PortfolioPanel() {
  const { can } = useAuth();
  const list = usePortfolios();
  const [chosen, setChosen] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const selected = chosen ?? list.data?.items[0]?.id ?? null;
  return (
    <Panel
      title="Portfolios"
      actions={
        can("experiments:run") && (
          <Button variant="secondary" onClick={() => setCreating(true)}>
            <Plus aria-hidden className="h-4 w-4" /> New portfolio
          </Button>
        )
      }
    >
      <ErrorMessage error={list.error} />
      {list.data?.items.length === 0 && (
        <p className="text-sm text-slate-500">No portfolios yet. A portfolio tests a family of tools on every workflow it serves, in several countries.</p>
      )}
      <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
        <ul aria-label="Portfolios" className="divide-y divide-slate-100">
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
                    #{x.portfolio_number} {x.name}
                  </span>
                  {x.verdict ? <VerdictPill verdict={x.verdict} /> : <StatusPill tone={STATUS_TONE[x.status]} label={humanize(x.status)} compact />}
                </div>
                <div className="text-xs text-slate-500">
                  {x.family} · {x.cells} cells · {x.countries.join(", ")}
                </div>
              </button>
            </li>
          ))}
        </ul>
        {selected && <PortfolioView key={selected} id={selected} />}
      </div>
      {creating && (
        <NewPortfolioDialog
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
