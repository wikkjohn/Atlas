import { AlertTriangle, CheckCircle2, Play, Search, XCircle } from "lucide-react";
import { type FormEvent, Fragment, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { formatMilliseconds as formatDuration, formatTimestamp } from "@/features/dashboard/format";
import { newIdempotencyKey } from "@/services/api";
import { useCountries } from "@/services/enterprise";
import { humanize } from "@/services/format";
import {
  syntheticDocumentNumber,
  useCompleteTask,
  useExecution,
  useExecutionHistory,
  useExecutions,
  useSignal,
  useStartExecution,
  useTasks,
  useWorkflowDefinition,
  useWorkflowMetrics,
  useWorkflows,
} from "@/services/workflows";
import type { ExecutionDetail, ExecutionStatus, StepRun, WorkflowTask } from "@/types/workflows";

type Tab = "catalogue" | "executions" | "tasks";
const PAGE_SIZE = 25;

const EXECUTION_TONE: Record<ExecutionStatus, Tone> = {
  running: "warn",
  waiting: "warn",
  completed: "good",
  failed: "bad",
  cancelled: "neutral",
};
const RUN_TONE: Record<StepRun["status"], Tone> = {
  pending: "warn",
  waiting: "warn",
  completed: "good",
  failed: "bad",
  cancelled: "neutral",
};

function TypeTag({ type }: { type: string }) {
  return (
    <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600">{type}</span>
  );
}

// --- Catalogue ------------------------------------------------------------------------------

function DefinitionView({ id }: { id: string }) {
  const definition = useWorkflowDefinition(id);
  const metrics = useWorkflowMetrics(id);
  const d = definition.data;
  const m = metrics.data;
  if (definition.error) return <ErrorMessage error={definition.error} />;
  if (!d) return <p className="text-sm text-slate-500">Loading…</p>;
  const metricFor = (stepId: string) => m?.steps.find((s) => s.step_id === stepId);

  return (
    <div className="space-y-5">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm text-slate-500">{d.workflow_id}</span>
          <h2 className="text-lg font-semibold text-slate-900">{d.name}</h2>
          <span className="text-xs text-slate-500">v{d.version}</span>
        </div>
        <p className="mt-1 text-sm text-slate-600">{d.description}</p>
        <p className="mt-1 text-xs text-slate-500">
          Owner: {d.business_owner} · Trigger: {d.trigger_type}
        </p>
      </div>
      {m && (
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          {(
            [
              ["Executions", Object.values(m.executions).reduce((a, b) => a + b, 0)],
              ["Approved", m.outcomes.approved ?? 0],
              ["Rejected", m.outcomes.rejected ?? 0],
              ["Avg duration", formatDuration(m.avg_execution_ms)],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="rounded-lg border border-slate-200 bg-white p-3">
              <dt className="text-xs text-slate-500">{label}</dt>
              <dd className="text-lg font-semibold text-slate-900">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table aria-label="Process steps" className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="px-4 py-2">Step</th>
              <th className="px-4 py-2">Routes to</th>
              <th className="px-4 py-2">Policy</th>
              <th className="px-4 py-2 text-right">Runs</th>
              <th className="px-4 py-2 text-right">p95</th>
              <th className="px-4 py-2 text-right">Failed</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {d.steps.map((step) => {
              const metric = metricFor(step.id);
              const routes = [
                ...(step.transitions ?? []).map((t) => t.to),
                ...(step.next ? [step.next] : []),
                ...(step.branches ?? []),
              ];
              const policy = step.approval
                ? `Needs ${step.approval.permissions.join(" + ")}; not ${step.approval.distinct_from.join(", ")}`
                : step.signal
                  ? `Waits for “${step.signal}”`
                  : step.retry
                    ? `Retry ×${step.retry.max_attempts}`
                    : "";
              const bottleneck = m?.bottleneck_step === step.id;
              return (
                <tr key={step.id} className={bottleneck ? "bg-amber-50" : undefined}>
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-2">
                      <TypeTag type={step.type} />
                      <span className="font-medium text-slate-900">{step.name}</span>
                      {bottleneck && (
                        <span className="inline-flex items-center gap-1 text-[11px] font-medium text-amber-700">
                          <AlertTriangle aria-hidden className="h-3 w-3" /> Bottleneck
                        </span>
                      )}
                    </div>
                    <div className="font-mono text-[11px] text-slate-400">{step.id}</div>
                  </td>
                  <td className="px-4 py-2 font-mono text-[11px] text-slate-600">{routes.join(", ") || "—"}</td>
                  <td className="px-4 py-2 text-xs text-slate-600">
                    {policy}
                    {step.timeout && (
                      <div className="text-slate-400">
                        Timeout {formatDuration(step.timeout.after_seconds * 1000)} → {step.timeout.action}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right text-slate-700">{metric?.runs ?? 0}</td>
                  <td className="px-4 py-2 text-right whitespace-nowrap text-slate-700">{formatDuration(metric?.p95_ms)}</td>
                  <td className={`px-4 py-2 text-right ${metric?.failed ? "font-medium text-rose-700" : "text-slate-500"}`}>
                    {metric?.failed ?? 0}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StartApplicationDialog({ onClose, onStarted }: { onClose: () => void; onStarted: (id: string) => void }) {
  const start = useStartExecution("WF-0001");
  const countries = useCountries({ operational_status: "active" });
  const [key] = useState(newIdempotencyKey);
  const [form, setForm] = useState({
    applicant_name: "",
    date_of_birth: "",
    country_code: "",
    account_type: "current",
    politically_exposed: false,
    expected_monthly_deposits: "0",
    passport: true,
    proof_of_address: true,
  });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm({ ...form, [k]: v });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const documents = [
      ...(form.passport
        ? [
            {
              document_type: "passport",
              document_number: syntheticDocumentNumber("passport"),
              name_on_document: form.applicant_name,
              date_of_birth: form.date_of_birth,
              expiry_date: `${new Date().getFullYear() + 5}-01-01`,
            },
          ]
        : []),
      ...(form.proof_of_address
        ? [
            {
              document_type: "proof_of_address",
              document_number: syntheticDocumentNumber("proof_of_address"),
              name_on_document: form.applicant_name,
            },
          ]
        : []),
    ];
    start.mutate(
      {
        idempotencyKey: key,
        input: {
          applicant_name: form.applicant_name,
          date_of_birth: form.date_of_birth,
          country_code: form.country_code,
          account_type: form.account_type,
          politically_exposed: form.politically_exposed,
          expected_monthly_deposits: Number(form.expected_monthly_deposits) || 0,
          documents,
        },
      },
      { onSuccess: (execution) => onStarted(execution.id) },
    );
  };

  return (
    <Modal
      wide
      title="New retail account application (WF-0001)"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="wf0001-start" disabled={start.isPending}>
            {start.isPending ? "Submitting…" : "Submit application"}
          </Button>
        </>
      }
    >
      <form id="wf0001-start" onSubmit={onSubmit} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Applicant name">
          {(p) => <input {...p} className={inputClass} required value={form.applicant_name} onChange={(e) => set("applicant_name", e.target.value)} />}
        </Field>
        <Field label="Date of birth">
          {(p) => <input {...p} type="date" className={inputClass} required value={form.date_of_birth} onChange={(e) => set("date_of_birth", e.target.value)} />}
        </Field>
        <Field label="Country">
          {(p) => (
            <select {...p} className={inputClass} required value={form.country_code} onChange={(e) => set("country_code", e.target.value)}>
              <option value="">Select…</option>
              {countries.data?.items.map((c) => (
                <option key={c.id} value={c.iso_country_code}>
                  {c.country_name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Account type">
          {(p) => (
            <select {...p} className={inputClass} value={form.account_type} onChange={(e) => set("account_type", e.target.value)}>
              <option value="current">Current</option>
              <option value="savings">Savings</option>
            </select>
          )}
        </Field>
        <Field label="Expected monthly deposits" hint="Whole units of the local currency.">
          {(p) => (
            <input {...p} type="number" min={0} className={inputClass} value={form.expected_monthly_deposits} onChange={(e) => set("expected_monthly_deposits", e.target.value)} />
          )}
        </Field>
        <fieldset className="space-y-1.5 text-sm">
          <legend className="text-xs font-medium text-slate-700">Declarations and documents</legend>
          {(
            [
              ["politically_exposed", "Politically exposed person"],
              ["passport", "Passport (synthetic)"],
              ["proof_of_address", "Proof of address (synthetic)"],
            ] as const
          ).map(([k, label]) => (
            <label key={k} className="flex items-center gap-2">
              <input type="checkbox" checked={form[k]} onChange={(e) => set(k, e.target.checked)} />
              {label}
            </label>
          ))}
        </fieldset>
      </form>
      <p className="mt-3 text-xs text-slate-500">
        Synthetic document numbers are generated with valid check digits. Leave a document out to see the workflow
        wait for it.
      </p>
      <ErrorMessage error={start.error} className="mt-4" />
    </Modal>
  );
}

function CatalogueTab({ onStarted }: { onStarted: (id: string) => void }) {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const workflows = useWorkflows(q || undefined);
  const [selected, setSelected] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const current = selected ?? workflows.data?.[0]?.workflow_id ?? null;

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[300px_1fr]">
      <div className="space-y-3">
        <div className="relative">
          <Search aria-hidden className="pointer-events-none absolute top-2 left-2.5 h-4 w-4 text-slate-400" />
          <input
            aria-label="Search workflows"
            placeholder="Search workflows"
            className="w-full rounded-lg border border-slate-200 bg-white py-1.5 pr-3 pl-8 text-sm"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <ErrorMessage error={workflows.error} />
        <ul aria-label="Workflows" className="space-y-2">
          {workflows.data?.map((w) => (
            <li key={w.workflow_id}>
              <button
                type="button"
                onClick={() => setSelected(w.workflow_id)}
                className={`w-full rounded-lg border p-3 text-left ${current === w.workflow_id ? "border-navy-700 bg-navy-900/5" : "border-slate-200 bg-white hover:bg-slate-50"}`}
              >
                <div className="font-mono text-[11px] text-slate-500">{w.workflow_id}</div>
                <div className="text-sm font-medium text-slate-900">{w.name}</div>
                <div className="text-xs text-slate-500">
                  v{w.version} · {w.step_count} steps
                </div>
              </button>
            </li>
          ))}
          {workflows.data?.length === 0 && <li className="text-sm text-slate-500">No workflows match.</li>}
        </ul>
        {current === "WF-0001" && can("workflows:start") && (
          <Button className="w-full" onClick={() => setStarting(true)}>
            <Play aria-hidden className="h-4 w-4" /> Start an application
          </Button>
        )}
      </div>
      <div>{current && <DefinitionView id={current} />}</div>
      {starting && (
        <StartApplicationDialog
          onClose={() => setStarting(false)}
          onStarted={(id) => {
            setStarting(false);
            onStarted(id);
          }}
        />
      )}
    </div>
  );
}

// --- Executions ------------------------------------------------------------------------------

function DocumentsSignal({ execution }: { execution: ExecutionDetail }) {
  const signal = useSignal(execution.id);
  const name = String((execution.context.input as { applicant_name?: string })?.applicant_name ?? "");
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">
      <p className="text-amber-900">This case is waiting for documents.</p>
      <Button
        size="sm"
        className="mt-2"
        disabled={signal.isPending}
        onClick={() =>
          signal.mutate({
            signal: "documents_submitted",
            payload: {
              documents: [
                { document_type: "proof_of_address", document_number: syntheticDocumentNumber("proof_of_address"), name_on_document: name },
                {
                  document_type: "passport",
                  document_number: syntheticDocumentNumber("passport"),
                  name_on_document: name,
                  date_of_birth: (execution.context.input as { date_of_birth?: string })?.date_of_birth,
                  expiry_date: `${new Date().getFullYear() + 5}-01-01`,
                },
              ],
            },
          })
        }
      >
        Submit synthetic documents
      </Button>
      <ErrorMessage error={signal.error} className="mt-2" />
    </div>
  );
}

function ExecutionView({ id, onClose }: { id: string; onClose: () => void }) {
  const { can } = useAuth();
  const execution = useExecution(id);
  const history = useExecutionHistory(id);
  const [showContext, setShowContext] = useState(false);
  const e = execution.data;

  return (
    <Modal wide title="Workflow execution" onClose={onClose}>
      <ErrorMessage error={execution.error} />
      {e && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="text-base font-semibold text-slate-900">
                {e.workflow_id} · {e.applicant ?? "—"}
              </h3>
              <p className="font-mono text-[11px] text-slate-500">
                {e.id} · started {formatTimestamp(e.started_at)} by {e.initiated_by_username}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <StatusPill tone={EXECUTION_TONE[e.status]} label={humanize(e.status)} />
              {e.outcome && <StatusPill tone={e.outcome === "approved" ? "good" : "bad"} label={humanize(e.outcome)} />}
            </div>
          </div>
          {e.error && (
            <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
              Failed at <strong>{String(e.error.step ?? "?")}</strong>: {String(e.error.message ?? e.error.code ?? "")}
            </div>
          )}
          {e.current_steps.includes("await_documents") && can("workflows:start") && <DocumentsSignal execution={e} />}
          <table aria-label="Step runs" className="min-w-full text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr>
                <th className="py-1">#</th>
                <th className="py-1">Step</th>
                <th className="py-1">Status</th>
                <th className="py-1">By</th>
                <th className="py-1 text-right">Duration</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {e.steps.map((s) => (
                <Fragment key={s.id}>
                  <tr>
                    <td className="py-1.5 font-mono text-[11px] text-slate-400">{s.sequence}</td>
                    <td className="py-1.5">
                      <span className="font-medium text-slate-800">{s.step_name}</span>{" "}
                      <TypeTag type={s.step_type} />
                      {s.branch && <span className="ml-1 text-[11px] text-slate-400">branch {s.branch}</span>}
                      {s.attempt > 1 && <span className="ml-1 text-[11px] text-amber-700">attempt {s.attempt}</span>}
                    </td>
                    <td className="py-1.5">
                      <StatusPill tone={RUN_TONE[s.status]} label={s.escalated_at ? "overdue" : s.status} />
                    </td>
                    <td className="py-1.5 text-xs text-slate-600">{s.actor_username ?? (s.step_type === "approval" || s.step_type === "human_task" ? "—" : "system")}</td>
                    <td className="py-1.5 text-right text-xs whitespace-nowrap text-slate-600">{formatDuration(s.duration_ms)}</td>
                  </tr>
                  {s.error && (
                    <tr>
                      <td />
                      <td colSpan={4} className="pb-2 text-xs text-rose-700">
                        {s.error.code}: {s.error.message}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
          <div className="flex gap-2">
            <Button size="sm" variant="secondary" onClick={() => setShowContext(!showContext)}>
              {showContext ? "Hide" : "Show"} context
            </Button>
          </div>
          {showContext && (
            <pre aria-label="Execution context" className="max-h-72 overflow-auto rounded-lg bg-navy-950 p-3 font-mono text-[11px] text-slate-100">
              {JSON.stringify(e.context, null, 2)}
            </pre>
          )}
          <section aria-label="History">
            <h4 className="mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase">History</h4>
            <ol className="max-h-48 space-y-0.5 overflow-auto font-mono text-[11px] text-slate-600">
              {history.data?.map((ev) => (
                <li key={ev.id}>
                  {formatTimestamp(ev.occurred_at)} · {ev.event_type}
                  {"step" in ev.data && ev.data.step ? ` · ${String(ev.data.step)}` : ""}
                </li>
              ))}
            </ol>
          </section>
        </div>
      )}
    </Modal>
  );
}

function ExecutionsTab({ onOpen }: { onOpen: (id: string) => void }) {
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const executions = useExecutions({ status: status || undefined, limit: PAGE_SIZE, offset });
  return (
    <>
      <div className="mb-4">
        <select
          aria-label="Execution status"
          className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">Any status</option>
          {["running", "waiting", "completed", "failed", "cancelled"].map((s) => (
            <option key={s} value={s}>
              {humanize(s)}
            </option>
          ))}
        </select>
      </div>
      <ErrorMessage error={executions.error} className="mb-4" />
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="px-4 py-2.5">Case</th>
              <th className="px-4 py-2.5">Status</th>
              <th className="px-4 py-2.5">Current step</th>
              <th className="px-4 py-2.5">Started</th>
              <th className="px-4 py-2.5 text-right">Duration</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {executions.data?.items.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                  No executions yet.
                </td>
              </tr>
            )}
            {executions.data?.items.map((x) => (
              <tr key={x.id} className="cursor-pointer hover:bg-slate-50" onClick={() => onOpen(x.id)}>
                <td className="px-4 py-2.5">
                  <button type="button" className="text-left font-medium text-slate-900 hover:underline">
                    {x.applicant ?? x.id.slice(0, 8)}
                  </button>
                  <div className="font-mono text-[11px] text-slate-500">{x.workflow_id}</div>
                </td>
                <td className="px-4 py-2.5">
                  <StatusPill tone={EXECUTION_TONE[x.status]} label={x.outcome ? `${x.status} · ${x.outcome}` : x.status} />
                </td>
                <td className="px-4 py-2.5 font-mono text-xs text-slate-600">{x.current_steps.join(", ") || "—"}</td>
                <td className="px-4 py-2.5 text-xs text-slate-600">
                  {formatTimestamp(x.started_at)}
                  <div className="text-slate-400">by {x.initiated_by_username}</div>
                </td>
                <td className="px-4 py-2.5 text-right text-xs text-slate-600">{formatDuration(x.duration_ms)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {executions.data && (
        <div className="mt-3">
          <Pagination total={executions.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
        </div>
      )}
    </>
  );
}

// --- Tasks ------------------------------------------------------------------------------------

function TaskRow({ task, onOpen }: { task: WorkflowTask; onOpen: (id: string) => void }) {
  const complete = useCompleteTask();
  const [note, setNote] = useState("");
  return (
    <li className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-900">{task.step_name}</p>
          <p className="text-sm text-slate-700">
            {task.applicant} · risk {task.risk_rating ?? "—"}
            {task.flags.length > 0 && <span className="text-rose-700"> · flags: {task.flags.join(", ")}</span>}
          </p>
          <p className="text-xs text-slate-500">
            Started by {task.initiated_by_username} · opened {formatTimestamp(task.opened_at)}
            {task.due_at && ` · due ${formatTimestamp(task.due_at)}`}
            {task.overdue && <span className="font-medium text-rose-700"> · overdue</span>}
          </p>
          <button type="button" className="mt-1 text-xs text-navy-700 hover:underline" onClick={() => onOpen(task.execution_id)}>
            Open case
          </button>
        </div>
        {task.can_act ? (
          <div className="flex flex-col items-end gap-2">
            <input
              aria-label={`Note for ${task.applicant}`}
              placeholder="Decision note"
              className="w-56 rounded-lg border border-slate-200 px-2 py-1 text-sm"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <div className="flex gap-1.5">
              <Button size="sm" disabled={complete.isPending} onClick={() => complete.mutate({ runId: task.run_id, decision: "approve", note })}>
                <CheckCircle2 aria-hidden className="h-3.5 w-3.5" /> Approve
              </Button>
              <Button size="sm" variant="secondary" disabled={complete.isPending} onClick={() => complete.mutate({ runId: task.run_id, decision: "reject", note })}>
                <XCircle aria-hidden className="h-3.5 w-3.5" /> Reject
              </Button>
            </div>
          </div>
        ) : (
          <p className="max-w-xs text-right text-xs text-slate-500">{task.blocked_reason}</p>
        )}
      </div>
      <ErrorMessage error={complete.error} className="mt-2" />
    </li>
  );
}

function TasksTab({ onOpen }: { onOpen: (id: string) => void }) {
  const [onlyMine, setOnlyMine] = useState(true);
  const tasks = useTasks(onlyMine);
  return (
    <>
      <label className="mb-4 flex items-center gap-2 text-sm text-slate-700">
        <input type="checkbox" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} />
        Only tasks I can act on
      </label>
      <ErrorMessage error={tasks.error} className="mb-4" />
      {tasks.data?.items.length === 0 && <p className="text-sm text-slate-500">No open tasks.</p>}
      <ul aria-label="Tasks" className="space-y-3">
        {tasks.data?.items.map((t) => (
          <TaskRow key={t.run_id} task={t} onOpen={onOpen} />
        ))}
      </ul>
    </>
  );
}

export function WorkflowExplorerPage() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab | null) ?? "catalogue";
  const openId = params.get("execution");
  const set = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    setParams(next);
  };
  const tabs: { id: Tab; label: string }[] = [
    { id: "catalogue", label: "Catalogue" },
    { id: "executions", label: "Executions" },
    { id: "tasks", label: "Task inbox" },
  ];

  return (
    <>
      <PageHeader
        title="Workflow Explorer"
        description="Executable business workflows: definitions, live executions, approvals and bottlenecks. Every case is persisted and auditable."
      />
      <div role="tablist" aria-label="Workflow views" className="mb-5 flex gap-1 border-b border-slate-200">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={tab === t.id}
            onClick={() => set({ tab: t.id === "catalogue" ? null : t.id })}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${tab === t.id ? "border-navy-900 text-navy-900" : "border-transparent text-slate-500 hover:text-slate-800"}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "catalogue" && <CatalogueTab onStarted={(id) => set({ tab: "executions", execution: id })} />}
      {tab === "executions" && <ExecutionsTab onOpen={(id) => set({ execution: id })} />}
      {tab === "tasks" && <TasksTab onOpen={(id) => set({ execution: id })} />}
      {openId && <ExecutionView key={openId} id={openId} onClose={() => set({ execution: null })} />}
    </>
  );
}
