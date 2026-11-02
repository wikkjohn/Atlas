import { useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { SERVICE_PAGE, useCaseAction, useCases, useOpenCase, useProposeRedress, useResolveCase, useServiceSummary, useSweep } from "@/services/customerService";
import { formatExactMoney, humanize, toMinorUnits } from "@/services/format";
import { CHANNELS, TOPICS, type ServiceCase } from "@/types/customerService";

const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const PRIORITY_TONE: Record<ServiceCase["priority"], Tone> = { low: "neutral", normal: "neutral", high: "warn", urgent: "bad" };

/** "due in 3 h", "overdue 2 h" or "breached", against now. */
function dueLabel(due: string, breached: boolean): string {
  if (breached) return "breached";
  const hours = Math.round((new Date(due).getTime() - Date.now()) / 3_600_000);
  return hours >= 0 ? `due in ${hours} h` : `overdue ${-hours} h`;
}

function OpenCaseForm() {
  const open = useOpenCase();
  const [form, setForm] = useState({ customer_number: "", account_number: "", category: "request", channel: "phone", topic: "card", priority: "normal", subject: "", description: "" });
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  return (
    <form
      aria-label="Open case"
      className="mb-4 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4"
      onSubmit={(e) => {
        e.preventDefault();
        open.mutate({ ...form, account_number: form.account_number || undefined });
      }}
    >
      <label className="flex flex-col gap-0.5 text-slate-600">
        Customer number
        <input aria-label="Customer number" className={INPUT} value={form.customer_number} onChange={set("customer_number")} />
      </label>
      <label className="flex flex-col gap-0.5 text-slate-600">
        Account (optional)
        <input aria-label="Account number" className={INPUT} value={form.account_number} onChange={set("account_number")} />
      </label>
      <label className="flex flex-col gap-0.5 text-slate-600">
        Category
        <select aria-label="Category" className={INPUT} value={form.category} onChange={set("category")}>
          {["enquiry", "request", "complaint"].map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-0.5 text-slate-600">
        Priority
        <select aria-label="Priority" className={INPUT} value={form.priority} onChange={set("priority")}>
          {["low", "normal", "high", "urgent"].map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-0.5 text-slate-600">
        Channel
        <select aria-label="Channel" className={INPUT} value={form.channel} onChange={set("channel")}>
          {CHANNELS.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-0.5 text-slate-600">
        Topic
        <select aria-label="Topic" className={INPUT} value={form.topic} onChange={set("topic")}>
          {TOPICS.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label className="col-span-2 flex flex-col gap-0.5 text-slate-600">
        Subject
        <input aria-label="Subject" className={INPUT} maxLength={200} value={form.subject} onChange={set("subject")} />
      </label>
      <label className="col-span-2 flex flex-col gap-0.5 text-slate-600 sm:col-span-3">
        Description
        <input aria-label="Description" className={INPUT} maxLength={2000} value={form.description} onChange={set("description")} />
      </label>
      <div className="flex items-end gap-2">
        <Button size="sm" type="submit" disabled={open.isPending || !form.customer_number || !form.subject || !form.description}>
          Open case
        </Button>
      </div>
      {open.data && (
        <span role="status" className="col-span-2">
          {open.data.case_number} opened
        </span>
      )}
      <ErrorMessage error={open.error} />
    </form>
  );
}

function CaseActions({ c }: { c: ServiceCase }) {
  const { can } = useAuth();
  const action = useCaseAction();
  const redress = useProposeRedress();
  const resolve = useResolveCase();
  const [amount, setAmount] = useState("");
  const [outcome, setOutcome] = useState("upheld");
  if (c.status === "resolved") return null;
  const handle = can("service:handle");
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1">
      {handle && !c.first_responded_at && (
        <Button size="sm" aria-label={`Respond to ${c.case_number}`} onClick={() => action.mutate({ id: c.id, action: "respond" })}>
          Respond
        </Button>
      )}
      {handle && c.status === "open" && (
        <Button size="sm" variant="secondary" aria-label={`Await customer on ${c.case_number}`} onClick={() => action.mutate({ id: c.id, action: "await-customer" })}>
          Await customer
        </Button>
      )}
      {handle && c.status === "awaiting_customer" && (
        <Button size="sm" variant="secondary" aria-label={`Resume ${c.case_number}`} onClick={() => action.mutate({ id: c.id, action: "resume" })}>
          Customer replied
        </Button>
      )}
      {handle && c.category === "complaint" && c.redress_status !== "proposed" && c.redress_status !== "paid" && c.account_number && (
        <>
          <input aria-label={`Redress for ${c.case_number}`} type="number" min={0.01} step="0.01" placeholder="Redress" className={`w-24 text-xs ${INPUT}`} value={amount} onChange={(e) => setAmount(e.target.value)} />
          <Button
            size="sm"
            variant="secondary"
            aria-label={`Propose redress on ${c.case_number}`}
            disabled={!amount}
            onClick={() => redress.mutate({ id: c.id, amount: toMinorUnits(Number(amount), c.currency ?? "USD"), account_number: c.account_number ?? "" })}
          >
            Propose redress
          </Button>
        </>
      )}
      {c.redress_status === "proposed" && can("service:approve") && (
        <Button size="sm" aria-label={`Pay redress on ${c.case_number}`} onClick={() => action.mutate({ id: c.id, action: "redress/pay" })}>
          Pay redress
        </Button>
      )}
      {handle && c.redress_status === "proposed" && (
        <Button size="sm" variant="secondary" aria-label={`Withdraw redress on ${c.case_number}`} onClick={() => action.mutate({ id: c.id, action: "redress/withdraw" })}>
          Withdraw
        </Button>
      )}
      {handle && c.redress_status !== "proposed" && (
        <>
          {c.category === "complaint" && (
            <select aria-label={`Outcome for ${c.case_number}`} className={`text-xs ${INPUT}`} value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              {["upheld", "partly_upheld", "not_upheld"].map((v) => (
                <option key={v} value={v}>
                  {humanize(v)}
                </option>
              ))}
            </select>
          )}
          <Button
            size="sm"
            aria-label={`Resolve ${c.case_number}`}
            onClick={() => resolve.mutate({ id: c.id, resolution: c.category === "complaint" ? "Final response sent" : "Resolved", outcome: c.category === "complaint" ? outcome : undefined })}
          >
            Resolve
          </Button>
        </>
      )}
      <ErrorMessage error={action.error ?? redress.error ?? resolve.error} />
    </div>
  );
}

function CasesPanel() {
  const { can } = useAuth();
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState("unresolved");
  const cases = useCases(offset, status);
  const sweep = useSweep();
  return (
    <Panel title="Cases" subtitle="Enquiries, requests and complaints from every channel, most urgent first. First response and resolution fall due by priority (urgent 1 h / 8 h, high 4 h / 24 h, normal 8 h / 72 h, low 24 h / 120 h); a complaint is acknowledged within two days and answered within eight weeks. Waiting on the customer pauses the clock, except for a complaint's final response. The sweep (also a scheduled job) marks overdue cases breached and escalates them.">
      {can("service:handle") && <OpenCaseForm />}
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-600">
        <label className="flex items-center gap-1">
          Show
          <select
            aria-label="Case status"
            className={INPUT}
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}
          >
            <option value="unresolved">Unresolved</option>
            <option value="awaiting_customer">Awaiting customer</option>
            <option value="resolved">Resolved</option>
          </select>
        </label>
        {can("service:handle") && (
          <Button size="sm" variant="secondary" onClick={() => sweep.mutate()} disabled={sweep.isPending}>
            Run SLA sweep
          </Button>
        )}
        {sweep.data && (
          <span role="status">
            {sweep.data.response_breached} response and {sweep.data.resolution_breached} resolution breaches
          </span>
        )}
        <ErrorMessage error={sweep.error} />
      </div>
      <ErrorMessage error={cases.error} />
      <table aria-label="Cases" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {cases.data?.items.map((c) => (
            <tr key={c.id} className="align-top">
              <td className="px-2 py-1.5 font-mono text-xs">{c.case_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                <div className="font-medium text-slate-800">
                  {c.subject} · {humanize(c.category)}
                </div>
                <div>
                  {c.customer_name} ({c.customer_number}) · {c.channel} · {c.topic}
                  {c.account_number && ` · ${c.account_number}`}
                </div>
                {c.status !== "resolved" && (
                  <div>
                    Response {c.first_responded_at ? "sent" : dueLabel(c.first_response_due, c.response_breached)} · resolution {dueLabel(c.resolve_due, c.resolution_breached)}
                    {c.escalated && " · escalated"}
                  </div>
                )}
                {c.redress_amount !== null && c.currency && (
                  <div>
                    Redress {formatExactMoney(c.redress_amount, c.currency)} {c.redress_status}
                    {c.redress_entry && ` (${c.redress_entry})`}
                  </div>
                )}
                {c.resolution && (
                  <div>
                    {c.resolution}
                    {c.outcome && ` · ${humanize(c.outcome)}`}
                  </div>
                )}
                <CaseActions c={c} />
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={PRIORITY_TONE[c.priority]} label={c.priority} />
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={c.status === "resolved" ? "good" : c.response_breached || c.resolution_breached ? "bad" : "warn"} label={humanize(c.status)} />
              </td>
            </tr>
          ))}
          {cases.data && cases.data.items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No cases.</td>
            </tr>
          )}
        </tbody>
      </table>
      {(cases.data?.total ?? 0) > SERVICE_PAGE && (
        <nav aria-label="Case pages" className="mt-2 flex items-center justify-end gap-2 text-xs text-slate-600">
          <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(offset - SERVICE_PAGE, 0))}>
            Previous
          </Button>
          <Button size="sm" variant="secondary" disabled={offset + SERVICE_PAGE >= (cases.data?.total ?? 0)} onClick={() => setOffset(offset + SERVICE_PAGE)}>
            Next
          </Button>
        </nav>
      )}
    </Panel>
  );
}

/** Customer service (Phase 51): contact-centre cases, complaints and SLA timers. */
export function CustomerServicePage() {
  const summary = useServiceSummary();
  return (
    <>
      <PageHeader title="Customer Service" description="Contact-centre cases from every channel with SLA timers, escalation of overdue cases, and complaints with redress paid by a second person." />
      {summary.data && (
        <dl aria-label="Service summary" className="mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
          {(
            [
              ["Open cases", summary.data.open],
              ["Complaints open", summary.data.complaints_open],
              ["SLA breached", summary.data.breached],
              ["Redress to approve", summary.data.redress_to_approve],
              ["Avg first response", summary.data.avg_first_response_minutes === null ? "—" : `${summary.data.avg_first_response_minutes} min`],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="rounded-lg border border-slate-200 bg-white p-3">
              <dt className="text-xs text-slate-500">{label}</dt>
              <dd className="text-lg font-semibold text-slate-900">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <CasesPanel />
    </>
  );
}
