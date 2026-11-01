import { FlaskConical, Play, Plus, ShieldAlert } from "lucide-react";
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
import { formatTimestamp } from "@/features/dashboard/format";
import {
  useActions,
  useAdapters,
  useAiTool,
  useAiTools,
  useInvocations,
  useInvokeTool,
  useRegisterTool,
  useSetToolStatus,
  useStartSuite,
  useSuiteRuns,
} from "@/services/aiTools";
import { humanize } from "@/services/format";
import { useScenarios, useSimulationRun } from "@/services/simulations";
import { useWorkflows } from "@/services/workflows";
import type { AiTool, InvocationStatus } from "@/types/aiTools";
import { type ExperimentMode, MODE_LABELS, type SimulationRunSummary } from "@/types/simulations";

const INVOCATION_TONE: Record<InvocationStatus, Tone> = {
  succeeded: "good",
  failed: "bad",
  timeout: "bad",
  invalid_input: "warn",
  invalid_output: "bad",
  blocked: "bad",
};
const RUN_TONE: Record<SimulationRunSummary["status"], Tone> = {
  queued: "neutral",
  running: "warn",
  completed: "good",
  failed: "bad",
};
const ALL_MODES: ExperimentMode[] = ["baseline", "ai_assisted", "ai_automated"];
const INVOCATIONS_PAGE = 10;
const TOOL_ID = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const SEMVER = /^\d+\.\d+\.\d+$/;

/** A valid synthetic application for the KYC test console (fictional applicant). */
const SAMPLE_INPUT = {
  application: {
    applicant_name: "Mia Novak",
    date_of_birth: "1990-04-12",
    country_code: "DE",
    account_type: "current",
    documents: [
      {
        document_type: "national_id",
        document_number: "N12345678",
        name_on_document: "Mia Novak",
        date_of_birth: "1990-04-12",
        expiry_date: "2031-06-30",
      },
      { document_type: "proof_of_address", document_number: "A76543218", name_on_document: "Mia Novak" },
    ],
    politically_exposed: false,
    expected_monthly_deposits: 4000,
  },
  screening: { sanctions_hit: false },
  as_of: "2026-01-05",
};

/** A synthetic held payment for the payment screener's test console. */
const SAMPLE_PAYMENT = {
  payment: { amount: 450000, currency: "GBP", reference: "Gift card codes", channel: "online", high_value: false },
  signals: { sanctions_hit: false, new_payee: true, recent_payments_24h: 0, share_of_balance: 0.6 },
  as_of: "2026-01-06",
};
/** A referred synthetic loan application whose declared income is twice the estimate. */
const SAMPLE_LOAN = {
  application: {
    amount: 1500000,
    currency: "EUR",
    term_months: 48,
    purpose: "vehicle",
    employment_status: "employed",
    monthly_income: 900000,
    monthly_debt_payments: 30000,
  },
  bureau: { score: 742, recent_defaults: 0, open_credit_lines: 2 },
  affordability: { annual_rate_bps: 890, monthly_payment: 37254, debt_to_income: 0.0747, committee_required: false },
  income: { estimated_monthly_income: 450000, declared_to_estimate: 2.0 },
  as_of: "2026-01-07",
};
/** An overdraft request from a customer overdrawn most days: the assistant's blind spot (Phase 30). */
const SAMPLE_OVERDRAFT = {
  limit: 150000,
  profile: {
    currency: "USD",
    balance: -42000,
    overdraft_limit: 75000,
    max_overdraft: 250000,
    monthly_credits: 380000,
    months_with_credits: 3,
    days_overdrawn: 81,
  },
  as_of: "2026-04-07",
};
/** Card testing at home: tiny test purchases, then crypto — the fraud assistant's blind spot (Phase 32). */
const SAMPLE_CARD_FRAUD = {
  profile: {
    currency: "USD",
    home_country: "US",
    daily_limit: 150000,
    blocked: {
      auth_code: "AUTH-00000042",
      merchant_name: "Coin Exchange",
      merchant_category: "6051",
      merchant_country: "US",
      abroad: false,
      amount: 12000,
      fraud_score: 70,
      fraud_signals: ["high_risk_category", "velocity"],
    },
    purchases_90d: 17,
    median_amount: 5200,
    high_risk_purchases_90d: 0,
    country_first_seen_hours: null,
    attempts_last_hour: [110, 95, 180, 60, 150],
  },
};
/** Prime figures, but the term ends when the applicant is 94: the underwriting assistant's blind spot (Phase 34). */
const SAMPLE_MORTGAGE = {
  profile: {
    currency: "GBP",
    product_code: "home-75",
    loan_amount: 18000000,
    term_years: 35,
    ltv_bps: 6000,
    monthly_payment: 87000,
    declared_monthly_income: 520000,
    income_estimate: 540000,
    payment_to_income_bps: 1673,
    payment_to_estimate_bps: 1611,
    declared_to_estimate_bps: 9629,
    credit_score: 781,
    recent_defaults: 0,
    valuation_method: "surveyor",
    model_to_price_bps: 10200,
    age_at_term_end: 94,
  },
};
/** A second near miss a year after a waiver: the covenant assistant's blind spot (Phase 36). */
const SAMPLE_COVENANT = {
  profile: {
    currency: "GBP",
    facility_type: "revolving",
    dscr_centi: 117,
    dscr_threshold_centi: 125,
    leverage_centi: 280,
    leverage_threshold_centi: 350,
    ebitda_change_bps: -150,
    previous_ebitda_change_bps: -2100,
    consecutive_declines: 2,
    utilisation_bps: 4500,
    periods_tested: 3,
    previous_breaches: 1,
    previous_waivers: 1,
  },
};
/** The same late presentation the bank rejected before: the document check assistant's blind spot (Phase 38). */
const SAMPLE_DOCUMENT_CHECK = {
  profile: {
    currency: "GBP",
    kind: "letter_of_credit",
    discrepancy: "late_presentation",
    discrepancy_count: 1,
    draw_share_bps: 4000,
    days_to_expiry: 75,
    funding_cover_bps: 25000,
    earlier_presentations: 1,
    earlier_rejected: 1,
    earlier_same_discrepancy: 1,
  },
};
/** A dealer's double-keyed placement: the back-office check assistant's blind spot (Phase 40). */
const SAMPLE_BACK_OFFICE = {
  profile: {
    kind: "placement",
    currency: "USD",
    rate_bps: 530,
    reference_rate_bps: 525,
    rate_against_bank_bps: -5,
    tenor_days: 30,
    rating: "AA",
    limit_utilisation_bps: 4200,
    coverage_after_bps: 48000,
    same_day_duplicates: 1,
  },
};
/** A customer request from a payer with four recent recalls, three refused: the recall assistant's blind spot (Phase 42). */
const SAMPLE_RECALL = {
  profile: {
    reason_code: "CUST",
    currency: "GBP",
    amount: 250000,
    high_value: false,
    days_since_settlement: 2,
    window_days: 5,
    days_left: 3,
    duplicate_matches: 0,
    payee_history: 0,
    payer_recalls_90d: 4,
    payer_refused_90d: 3,
  },
};
const SAMPLES: Record<string, unknown> = {
  rule_based_payment_screening: SAMPLE_PAYMENT,
  rule_based_credit_underwriting: SAMPLE_LOAN,
  rule_based_overdraft_affordability: SAMPLE_OVERDRAFT,
  rule_based_card_fraud_review: SAMPLE_CARD_FRAUD,
  rule_based_mortgage_underwriting: SAMPLE_MORTGAGE,
  rule_based_covenant_review: SAMPLE_COVENANT,
  rule_based_document_check: SAMPLE_DOCUMENT_CHECK,
  rule_based_back_office_check: SAMPLE_BACK_OFFICE,
  rule_based_recall_review: SAMPLE_RECALL,
};
const CONSOLE_ACTIONS = [
  "analyze_application",
  "analyze_payment",
  "analyze_credit_application",
  "recommend_decision",
  "complete_low_risk_review",
];

// --- Registration ---------------------------------------------------------------------------

function RegisterToolDialog({ onClose, onRegistered }: { onClose: () => void; onRegistered: (id: string) => void }) {
  const adapters = useAdapters();
  const actions = useActions();
  const workflows = useWorkflows();
  const register = useRegisterTool();
  const [form, setForm] = useState({
    tool_id: "",
    tool_name: "",
    tool_version: "1.0.0",
    provider: "",
    description: "",
    adapter: "rule_based_kyc",
  });
  const [chosenActions, setChosenActions] = useState<string[]>(["analyze_application", "recommend_decision"]);
  const [chosenWorkflows, setChosenWorkflows] = useState<string[]>(["WF-0001"]);
  const [configuration, setConfiguration] = useState("{}");
  const [submitted, setSubmitted] = useState(false);

  const adapter = adapters.data?.find((a) => a.key === form.adapter);
  let parsedConfig: Record<string, unknown> | null = null;
  try {
    const value: unknown = JSON.parse(configuration);
    parsedConfig = value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
  } catch {
    parsedConfig = null;
  }
  const errors = {
    tool_id: TOOL_ID.test(form.tool_id) ? null : "Lower-case letters, digits and single hyphens.",
    tool_name: form.tool_name.trim().length >= 3 ? null : "At least 3 characters.",
    tool_version: SEMVER.test(form.tool_version) ? null : "A semantic version such as 1.0.0.",
    provider: form.provider.trim().length >= 2 ? null : "Required.",
    actions: chosenActions.length > 0 ? null : "Grant at least one action.",
    configuration: parsedConfig ? null : "Must be a JSON object.",
  };
  const valid = Object.values(errors).every((e) => e === null);
  const show = (error: string | null) => (submitted ? error : null);
  const set = (key: keyof typeof form) => (value: string) => setForm({ ...form, [key]: value });
  const toggle = (list: string[], value: string) =>
    list.includes(value) ? list.filter((v) => v !== value) : [...list, value];

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (!valid || !parsedConfig) return;
    register.mutate(
      {
        ...form,
        allowed_actions: chosenActions,
        compatible_workflows: chosenWorkflows,
        permissions: [],
        configuration: parsedConfig,
      },
      { onSuccess: (tool) => onRegistered(tool.id) },
    );
  };

  return (
    <Modal title="Register an AI tool" onClose={onClose}>
      <form id="register-tool" aria-label="Register an AI tool" onSubmit={submit} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Tool ID" error={show(errors.tool_id)}>
            {(p) => <input {...p} className={inputClass} value={form.tool_id} onChange={(e) => set("tool_id")(e.target.value)} />}
          </Field>
          <Field label="Version" error={show(errors.tool_version)}>
            {(p) => (
              <input {...p} className={inputClass} value={form.tool_version} onChange={(e) => set("tool_version")(e.target.value)} />
            )}
          </Field>
        </div>
        <Field label="Name" error={show(errors.tool_name)}>
          {(p) => <input {...p} className={inputClass} value={form.tool_name} onChange={(e) => set("tool_name")(e.target.value)} />}
        </Field>
        <Field label="Provider" error={show(errors.provider)}>
          {(p) => <input {...p} className={inputClass} value={form.provider} onChange={(e) => set("provider")(e.target.value)} />}
        </Field>
        <Field label="Description">
          {(p) => (
            <textarea {...p} rows={2} className={inputClass} value={form.description} onChange={(e) => set("description")(e.target.value)} />
          )}
        </Field>
        <Field label="Implementation (adapter)" hint={adapter?.description}>
          {(p) => (
            <select {...p} className={inputClass} value={form.adapter} onChange={(e) => set("adapter")(e.target.value)}>
              {(adapters.data ?? []).map((a) => (
                <option key={a.key} value={a.key}>
                  {a.name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <fieldset>
          <legend className="text-xs font-medium text-slate-700">Allowed actions</legend>
          <div className="mt-1 space-y-1">
            {(actions.data ?? []).map((a) => {
              const supported = a.grantable && (adapter?.supported_actions.includes(a.action) ?? false);
              return (
                <label key={a.action} className={`flex items-start gap-2 text-xs ${supported ? "text-slate-700" : "text-slate-400"}`}>
                  <input
                    type="checkbox"
                    disabled={!supported}
                    checked={chosenActions.includes(a.action)}
                    onChange={() => setChosenActions(toggle(chosenActions, a.action))}
                  />
                  <span>
                    <span className="font-mono">{a.action}</span>
                    {!a.grantable && " (never grantable)"} — {a.description}
                  </span>
                </label>
              );
            })}
          </div>
          {show(errors.actions) && <p className="mt-1 text-xs text-rose-600">{errors.actions}</p>}
        </fieldset>
        <fieldset>
          <legend className="text-xs font-medium text-slate-700">Compatible workflows</legend>
          <div className="mt-1 flex flex-wrap gap-3">
            {(workflows.data ?? []).map((w) => (
              <label key={w.workflow_id} className="flex items-center gap-2 text-xs text-slate-700">
                <input
                  type="checkbox"
                  checked={chosenWorkflows.includes(w.workflow_id)}
                  onChange={() => setChosenWorkflows(toggle(chosenWorkflows, w.workflow_id))}
                />
                {w.workflow_id} {w.name}
              </label>
            ))}
          </div>
        </fieldset>
        <Field label="Configuration (JSON)" hint="Validated by the adapter; omitted values use its defaults." error={show(errors.configuration)}>
          {(p) => (
            <textarea {...p} rows={3} className={`${inputClass} font-mono text-xs`} value={configuration} onChange={(e) => setConfiguration(e.target.value)} />
          )}
        </Field>
      </form>
      <ErrorMessage error={register.error} className="mt-3" />
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" form="register-tool" disabled={register.isPending}>
          Register tool
        </Button>
      </div>
    </Modal>
  );
}

// --- Test console -----------------------------------------------------------------------------

function TestConsole({ tool }: { tool: AiTool }) {
  const invoke = useInvokeTool(tool.id);
  const [action, setAction] = useState(tool.allowed_actions[0] ?? "analyze_application");
  const [input, setInput] = useState(JSON.stringify(SAMPLES[tool.adapter] ?? SAMPLE_INPUT, null, 2));
  let parsed: Record<string, unknown> | null = null;
  try {
    parsed = JSON.parse(input) as Record<string, unknown>;
  } catch {
    parsed = null;
  }
  const result = invoke.data;
  const output = result?.output as { recommendation?: string; explanation?: string; risk_classification?: string } | null;

  return (
    <form
      aria-label="Test console"
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (parsed) invoke.mutate({ action, input: parsed });
      }}
    >
      <Field label="Action" hint="Actions the tool was not granted are refused and recorded.">
        {(p) => (
          <select {...p} className={inputClass} value={action} onChange={(e) => setAction(e.target.value)}>
            {CONSOLE_ACTIONS.map((a) => (
              <option key={a} value={a}>
                {a}
                {tool.allowed_actions.includes(a) ? "" : " (not granted)"}
              </option>
            ))}
          </select>
        )}
      </Field>
      <Field label="Request (synthetic data)" error={parsed ? null : "Not valid JSON."}>
        {(p) => (
          <textarea {...p} rows={8} className={`${inputClass} font-mono text-xs`} value={input} onChange={(e) => setInput(e.target.value)} />
        )}
      </Field>
      <Button type="submit" disabled={invoke.isPending || !parsed}>
        <Play aria-hidden className="h-4 w-4" /> Invoke
      </Button>
      <ErrorMessage error={invoke.error} />
      {result && (
        <div role="status" className="rounded-lg border border-slate-200 p-3 text-sm">
          <div className="flex items-center gap-2">
            <StatusPill tone={INVOCATION_TONE[result.status]} label={humanize(result.status)} />
            <span className="text-xs text-slate-500">{result.duration_ms} ms</span>
          </div>
          {output?.recommendation && (
            <p className="mt-2">
              <span className="font-medium">Recommendation: {humanize(output.recommendation)}</span> ·{" "}
              {humanize(output.risk_classification ?? "")} risk
            </p>
          )}
          {output?.explanation && <p className="mt-1 text-xs text-slate-600">{output.explanation}</p>}
          {result.error && <pre className="mt-2 overflow-x-auto text-xs text-rose-700">{JSON.stringify(result.error, null, 2)}</pre>}
        </div>
      )}
    </form>
  );
}

// --- Experiments ------------------------------------------------------------------------------

function SuiteResults({ batchId }: { batchId: string }) {
  const suite = useSuiteRuns(batchId);
  const runs = [...(suite.data?.items ?? [])].sort((a, b) => a.run_number - b.run_number);
  return (
    <div className="space-y-2">
      <ErrorMessage error={suite.error} />
      <div className="overflow-x-auto rounded-xl border border-slate-200">
        <table aria-label="Experiment runs" className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="px-3 py-2">Configuration</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2 text-right">Accuracy</th>
              <th className="px-3 py-2 text-right">Manual reviews</th>
              <th className="px-3 py-2 text-right">Review hours</th>
              <th className="px-3 py-2 text-right">Policy approvals</th>
              <th className="px-3 py-2 text-right">AI failures</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {runs.map((run) => (
              <SuiteRow key={run.id} run={run} />
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-slate-500">
        Simulated measurements on synthetic data. AI-assisted review times and accuracy rest on the scenario's stated
        assumptions; costs and the formal comparison come with Benchmarking (Phase 7).
      </p>
    </div>
  );
}

function SuiteRow({ run }: { run: SimulationRunSummary }) {
  const detail = useSimulationRun(run.id);
  const res = detail.data?.results;
  const status = detail.data?.status ?? run.status;
  return (
    <tr>
      <td className="px-3 py-2">
        <Link className="font-medium text-navy-700 hover:underline" to={`/simulations?run=${run.id}`}>
          {MODE_LABELS[run.mode]}
        </Link>
        <div className="text-[11px] text-slate-500">Run #{run.run_number}</div>
      </td>
      <td className="px-3 py-2">
        <StatusPill tone={RUN_TONE[status]} label={humanize(status)} />
        {status === "running" && <span className="ml-1 text-xs text-slate-500">{detail.data?.percent_complete}%</span>}
      </td>
      <td className="px-3 py-2 text-right">
        {res?.ground_truth.accuracy != null ? `${(res.ground_truth.accuracy * 100).toFixed(1)}%` : "—"}
      </td>
      <td className="px-3 py-2 text-right">{res?.manual_reviews ?? "—"}</td>
      <td className="px-3 py-2 text-right">{res?.review_labor_hours != null ? res.review_labor_hours.toFixed(1) : "—"}</td>
      <td className="px-3 py-2 text-right">{res?.ai?.automated_approvals ?? "—"}</td>
      <td className="px-3 py-2 text-right">{res?.ai ? res.ai.failed_invocations : "—"}</td>
    </tr>
  );
}

function ExperimentForm({ tool, onStarted }: { tool: AiTool; onStarted: (batchId: string) => void }) {
  const scenarios = useScenarios();
  const start = useStartSuite();
  const candidates = (scenarios.data ?? []).filter(
    (s) => s.modes.length > 1 && tool.compatible_workflows.includes(s.workflow_id),
  );
  const [scenarioKey, setScenarioKey] = useState("");
  const scenario = candidates.find((s) => `${s.scenario_id}@${s.version}` === scenarioKey) ?? candidates[0];
  const [modes, setModes] = useState<ExperimentMode[]>(ALL_MODES);
  const [applications, setApplications] = useState("100");
  const [employees, setEmployees] = useState("25");
  const [seed, setSeed] = useState("42");
  const seedValue = Number(seed);
  const sizeOk = Number(applications) >= 1 && Number(applications) <= 10000 && Number(employees) >= 3 && Number(employees) <= 500;
  const valid =
    Boolean(scenario) && modes.length > 0 && Number.isInteger(seedValue) && seedValue >= 0 && sizeOk && tool.status === "active";

  if (candidates.length === 0) {
    return <p className="text-sm text-slate-500">No scenario with AI modes uses a workflow this tool is compatible with.</p>;
  }
  return (
    <form
      aria-label="Configure an experiment"
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!valid || !scenario) return;
        start.mutate(
          {
            scenario_id: scenario.scenario_id,
            scenario_version: scenario.version,
            profile: "custom",
            applications: Number(applications),
            employees: Number(employees),
            seed: seedValue,
            modes,
            tool_id: tool.tool_id,
            tool_version: tool.tool_version,
          },
          { onSuccess: (runs) => runs[0]?.batch_id && onStarted(runs[0].batch_id) },
        );
      }}
    >
      <Field label="Workflow and scenario">
        {(p) => (
          <select
            {...p}
            className={inputClass}
            value={scenario ? `${scenario.scenario_id}@${scenario.version}` : ""}
            onChange={(e) => setScenarioKey(e.target.value)}
          >
            {candidates.map((s) => (
              <option key={`${s.scenario_id}@${s.version}`} value={`${s.scenario_id}@${s.version}`}>
                {s.workflow_id} — {s.name} (v{s.version})
              </option>
            ))}
          </select>
        )}
      </Field>
      <fieldset>
        <legend className="text-xs font-medium text-slate-700">Configurations</legend>
        <div className="mt-1 flex flex-wrap gap-3">
          {ALL_MODES.map((m) => (
            <label key={m} className="flex items-center gap-2 text-xs text-slate-700">
              <input
                type="checkbox"
                checked={modes.includes(m)}
                onChange={() => setModes(modes.includes(m) ? modes.filter((x) => x !== m) : ALL_MODES.filter((x) => x === m || modes.includes(x)))}
              />
              {MODE_LABELS[m]}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="grid grid-cols-3 gap-3">
        <Field label="Cases" hint="1 – 10,000">
          {(p) => <input {...p} type="number" className={inputClass} value={applications} onChange={(e) => setApplications(e.target.value)} />}
        </Field>
        <Field label="Staff" hint="3 – 500">
          {(p) => <input {...p} type="number" className={inputClass} value={employees} onChange={(e) => setEmployees(e.target.value)} />}
        </Field>
        <Field label="Seed">
          {(p) => <input {...p} inputMode="numeric" className={inputClass} value={seed} onChange={(e) => setSeed(e.target.value)} />}
        </Field>
      </div>
      <Button type="submit" disabled={!valid || start.isPending}>
        <FlaskConical aria-hidden className="h-4 w-4" /> Start test runs
      </Button>
      <ErrorMessage error={start.error} />
    </form>
  );
}

// --- Tool detail ------------------------------------------------------------------------------

function ToolDetail({ id }: { id: string }) {
  const { can } = useAuth();
  const tool = useAiTool(id);
  const setStatus = useSetToolStatus();
  const [offset, setOffset] = useState(0);
  const invocations = useInvocations(id, offset, INVOCATIONS_PAGE);
  const [params, setParams] = useSearchParams();
  const suite = params.get("suite");
  const t = tool.data;
  if (tool.error) return <ErrorMessage error={tool.error} />;
  if (!t) return <p className="text-sm text-slate-500">Loading…</p>;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold text-slate-900">{t.tool_name}</h2>
            <span className="text-xs text-slate-500">v{t.tool_version}</span>
            <StatusPill tone={t.status === "active" ? "good" : "neutral"} label={humanize(t.status)} />
          </div>
          <p className="mt-1 text-sm text-slate-600">{t.description}</p>
          <p className="mt-1 text-xs text-slate-500">
            {t.provider} · adapter <span className="font-mono">{t.adapter}</span> · {t.invocations} invocations, {t.failures}{" "}
            not successful
          </p>
        </div>
        {can("ai_tools:manage") && (
          <Button
            variant="secondary"
            size="sm"
            disabled={setStatus.isPending}
            onClick={() => setStatus.mutate({ id: t.id, status: t.status === "active" ? "disabled" : "active" })}
          >
            {t.status === "active" ? "Disable" : "Enable"}
          </Button>
        )}
      </div>
      <ErrorMessage error={setStatus.error} />

      <section aria-label="Capabilities" className="grid gap-3 text-sm sm:grid-cols-2">
        <div className="rounded-lg border border-slate-200 p-3">
          <h3 className="mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase">Allowed actions</h3>
          <ul className="space-y-0.5 font-mono text-xs">
            {t.allowed_actions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
          <p className="mt-2 flex items-start gap-1 text-[11px] text-slate-500">
            <ShieldAlert aria-hidden className="mt-0.5 h-3 w-3 shrink-0" />
            Advisory only: the tool cannot approve accounts. The workflow policy engine and authorized people decide.
          </p>
        </div>
        <div className="rounded-lg border border-slate-200 p-3">
          <h3 className="mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase">Compatible workflows</h3>
          <p className="text-xs">{t.compatible_workflows.join(", ") || "None"}</p>
          <h3 className="mt-2 mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase">Configuration</h3>
          <pre className="overflow-x-auto text-[11px] text-slate-600">{JSON.stringify(t.configuration, null, 2)}</pre>
        </div>
        <details className="rounded-lg border border-slate-200 p-3 sm:col-span-2">
          <summary className="cursor-pointer text-xs font-semibold text-slate-700">Input and output schemas</summary>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            <pre className="max-h-64 overflow-auto text-[11px] text-slate-600">{JSON.stringify(t.input_schema, null, 2)}</pre>
            <pre className="max-h-64 overflow-auto text-[11px] text-slate-600">{JSON.stringify(t.output_schema, null, 2)}</pre>
          </div>
        </details>
      </section>

      {can("simulations:run") && (
        <section aria-label="Experiment" className="space-y-3">
          <h3 className="text-sm font-semibold text-slate-900">Run an experiment</h3>
          <p className="text-xs text-slate-500">
            Runs the chosen configurations one after another on the same seeded applications and staff. A: conventional
            rules and human review. B: the tool prepares summaries; people still decide. C: the policy engine may approve
            low-risk cases the tool recommends; everything else stays with people.
          </p>
          <ExperimentForm tool={t} onStarted={(batch) => setParams({ tool: t.id, suite: batch })} />
        </section>
      )}
      {suite && <SuiteResults batchId={suite} />}

      {can("ai_tools:invoke") && (
        <section aria-label="Try the tool" className="space-y-2">
          <h3 className="text-sm font-semibold text-slate-900">Test console</h3>
          <TestConsole tool={t} />
        </section>
      )}

      <section aria-label="Recorded invocations">
        <h3 className="mb-2 text-sm font-semibold text-slate-900">Recorded invocations</h3>
        <ErrorMessage error={invocations.error} />
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table aria-label="Invocations" className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
              <tr>
                <th className="px-3 py-2">When</th>
                <th className="px-3 py-2">Action</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Result</th>
                <th className="px-3 py-2">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {(invocations.data?.items ?? []).map((i) => (
                <tr key={i.id}>
                  <td className="px-3 py-2 text-xs">{formatTimestamp(i.created_at)}</td>
                  <td className="px-3 py-2 font-mono text-xs">{i.action}</td>
                  <td className="px-3 py-2">
                    <StatusPill tone={INVOCATION_TONE[i.status]} label={humanize(i.status)} />
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {typeof i.output?.recommendation === "string"
                      ? humanize(i.output.recommendation)
                      : typeof i.error?.message === "string"
                        ? i.error.message
                        : "—"}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-500">
                    {i.simulation_run_id ? "Simulation" : i.execution_id ? "Workflow" : "Test console"}
                  </td>
                </tr>
              ))}
              {invocations.data?.items.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-center text-sm text-slate-500">
                    No invocations yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {invocations.data && (
          <Pagination total={invocations.data.total} limit={INVOCATIONS_PAGE} offset={offset} onChange={setOffset} />
        )}
      </section>
    </div>
  );
}

// --- Page ------------------------------------------------------------------------------------

export function AiLabPage() {
  const { can } = useAuth();
  const tools = useAiTools();
  const [params, setParams] = useSearchParams();
  const [registering, setRegistering] = useState(false);
  const selected = params.get("tool") ?? tools.data?.items[0]?.id ?? null;

  return (
    <div>
      <PageHeader
        title="AI Innovation Lab"
        description="Register AI tools behind one provider-independent contract, try them, and test them inside banking workflows against a baseline."
        actions={
          <>
            <SyntheticDataBadge />
            {can("ai_tools:manage") && (
              <Button onClick={() => setRegistering(true)}>
                <Plus aria-hidden className="h-4 w-4" /> Register a tool
              </Button>
            )}
          </>
        }
      />
      <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
        <Panel title="Tool registry">
          <ErrorMessage error={tools.error} />
          {tools.data?.items.length === 0 && <p className="text-sm text-slate-500">No tools are registered yet.</p>}
          <ul aria-label="AI tools" className="divide-y divide-slate-100">
            {(tools.data?.items ?? []).map((tool) => (
              <li key={tool.id}>
                <button
                  type="button"
                  onClick={() => setParams({ tool: tool.id })}
                  aria-current={tool.id === selected ? "true" : undefined}
                  className={`w-full px-2 py-2 text-left text-sm hover:bg-slate-50 ${tool.id === selected ? "bg-slate-50" : ""}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-slate-900">{tool.tool_name}</span>
                    <StatusPill tone={tool.status === "active" ? "good" : "neutral"} label={humanize(tool.status)} compact />
                  </div>
                  <div className="text-xs text-slate-500">
                    {tool.tool_id} {tool.tool_version} · {tool.invocations} calls
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </Panel>
        <Panel title="Tool details">
          {selected ? <ToolDetail key={selected} id={selected} /> : <p className="text-sm text-slate-500">Register a tool to begin.</p>}
        </Panel>
      </div>
      {registering && (
        <RegisterToolDialog
          onClose={() => setRegistering(false)}
          onRegistered={(id) => {
            setRegistering(false);
            setParams({ tool: id });
          }}
        />
      )}
    </div>
  );
}
