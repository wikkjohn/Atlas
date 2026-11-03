import { useState } from "react";
import { Link } from "react-router-dom";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { useCompleteRequest, useCoverage, useDecideRequest, useDepartmentRequests, useSubmitRequest, useThinDepartments } from "@/services/backoffice";
import { formatExactMoney, toMinorUnits } from "@/services/format";
import type { DepartmentRequest, ThinDepartment } from "@/types/backoffice";

const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const TONE: Record<DepartmentRequest["status"], Tone> = { submitted: "warn", approved: "good", rejected: "neutral", completed: "neutral" };
const usd = (dollars: number) => `US$${dollars.toLocaleString("en-US")}`;

function DepartmentGrid({ departments, selected, onSelect }: { departments: ThinDepartment[]; selected: string; onSelect: (code: string) => void }) {
  return (
    <ul aria-label="Departments" className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {departments.map((d) => (
        <li key={d.code}>
          <button
            type="button"
            aria-pressed={d.code === selected}
            onClick={() => onSelect(d.code)}
            className={`w-full rounded-lg border p-3 text-left text-sm ${d.code === selected ? "border-navy-600 bg-slate-50" : "border-slate-200 bg-white"}`}
          >
            <span className="block font-semibold text-slate-900">{d.name}</span>
            <span className="block text-xs text-slate-500">
              {d.counts.submitted} to decide · {d.counts.approved} to complete · {d.counts.completed} done
              {d.counts.overdue > 0 && ` · ${d.counts.overdue} overdue`}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function SubmitForm({ department }: { department: ThinDepartment }) {
  const submit = useSubmitRequest();
  const [form, setForm] = useState({ process: department.processes[0].code, title: "", details: "", amount: "" });
  const process = department.processes.find((p) => p.code === form.process) ?? department.processes[0];
  return (
    <form
      aria-label="Submit request"
      className="mb-3 flex flex-wrap items-end gap-2 text-xs"
      onSubmit={(e) => {
        e.preventDefault();
        submit.mutate({
          department: department.code,
          process: process.code,
          title: form.title,
          details: form.details,
          amount: process.amount_label ? toMinorUnits(Number(form.amount), "USD") : undefined,
        });
      }}
    >
      <select aria-label="Process" className={INPUT} value={form.process} onChange={(e) => setForm({ ...form, process: e.target.value })}>
        {department.processes.map((p) => (
          <option key={p.code} value={p.code}>
            {p.name}
          </option>
        ))}
      </select>
      <input aria-label="Title" placeholder="What the request is for" className={`w-56 ${INPUT}`} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
      <input aria-label="Details" placeholder="Details (optional)" className={`w-56 ${INPUT}`} value={form.details} onChange={(e) => setForm({ ...form, details: e.target.value })} />
      {process.amount_label && (
        <input aria-label="Amount" type="number" min={1} placeholder={`${process.amount_label} (US$)`} className={`w-36 ${INPUT}`} value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
      )}
      <Button size="sm" type="submit" disabled={form.title.trim().length < 5 || (!!process.amount_label && !form.amount)}>
        Submit request
      </Button>
      {submit.data && (
        <span role="status">
          {submit.data.request_number} {submit.data.status}
        </span>
      )}
      <ErrorMessage error={submit.error} />
    </form>
  );
}

function DepartmentPanel({ department }: { department: ThinDepartment }) {
  const { can } = useAuth();
  const requests = useDepartmentRequests(department.code);
  const decide = useDecideRequest();
  const complete = useCompleteRequest();
  return (
    <Panel title={department.name} subtitle={department.description}>
      <ul aria-label="Processes" className="mb-3 space-y-1 text-xs text-slate-600">
        {department.processes.map((p) => (
          <li key={p.code}>
            <span className="font-semibold text-slate-800">{p.name}</span> ({p.workflow_id}) · {p.description} {p.approval ? "Approved by a second person" : "No approval"} · target {p.sla_hours} h
            {p.budget_usd !== null && ` · budget ${usd(p.budget_usd)}`}
            {p.major_above_usd !== null && ` · executive above ${usd(p.major_above_usd)}`}
          </li>
        ))}
      </ul>
      {can("departments:request") && <SubmitForm key={department.code} department={department} />}
      <ErrorMessage error={requests.error ?? decide.error ?? complete.error} />
      <table aria-label="Requests" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {requests.data?.items.map((r) => (
            <tr key={r.id} className="align-top">
              <td className="px-2 py-1.5 font-mono text-xs">{r.request_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {r.process_name} · {r.title}
                {r.amount !== null && ` · ${formatExactMoney(r.amount, "USD")}`}
                {r.over_budget && <span className="font-semibold text-amber-700"> · over budget</span>}
                {r.needs_executive && " · executive approval"}
                {r.breached && <span className="font-semibold text-rose-700"> · completed late</span>}
                {r.note && ` · ${r.note}`}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={TONE[r.status]} label={r.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                <div className="flex flex-wrap justify-end gap-1">
                  {r.status === "submitted" && can("departments:approve") && (
                    <>
                      <Button size="sm" aria-label={`Approve ${r.request_number}`} onClick={() => decide.mutate({ id: r.id, approve: true })}>
                        Approve
                      </Button>
                      <Button size="sm" variant="secondary" aria-label={`Reject ${r.request_number}`} onClick={() => decide.mutate({ id: r.id, approve: false })}>
                        Reject
                      </Button>
                    </>
                  )}
                  {r.status === "approved" && can("departments:request") && (
                    <Button size="sm" variant="secondary" aria-label={`Complete ${r.request_number}`} onClick={() => complete.mutate(r.id)}>
                      Complete
                    </Button>
                  )}
                </div>
              </td>
            </tr>
          ))}
          {requests.data && requests.data.items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No requests yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}

function CoveragePanel() {
  const coverage = useCoverage();
  const c = coverage.data;
  return (
    <Panel title="Milestone D coverage" subtitle="Every department of the bank: its base processes (stored and code workflows), the simulation scenarios that exercise them, and its dashboard. Each needs at least three processes, a workload and a dashboard.">
      <ErrorMessage error={coverage.error} />
      {c && (
        <>
          <p role="status" className="mb-2 text-sm text-slate-700">
            {c.complete} of {c.total} departments complete
          </p>
          <table aria-label="Department coverage" className="min-w-full text-sm">
            <tbody className="divide-y divide-slate-100">
              {c.departments.map((d) => (
                <tr key={d.department}>
                  <td className="px-2 py-1.5 text-xs font-semibold text-slate-800">{d.department}</td>
                  <td className="px-2 py-1.5 text-xs text-slate-600">
                    {d.workflows.length} processes ({d.workflows.join(", ")}) · {d.scenarios.length} scenarios ({d.scenarios.join(", ")})
                  </td>
                  <td className="px-2 py-1.5 text-xs">{d.dashboard && <Link to={d.dashboard}>{d.thin ? "Departments" : "Dashboard"}</Link>}</td>
                  <td className="px-2 py-1.5">
                    <StatusPill compact tone={d.complete ? "good" : "bad"} label={d.complete ? "complete" : "incomplete"} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </Panel>
  );
}

/** Thin departments (Phase 61): sixteen departments, three processes each, one request lifecycle. */
export function DepartmentsPage() {
  const departments = useThinDepartments();
  const [selected, setSelected] = useState("legal");
  const department = departments.data?.find((d) => d.code === selected);
  return (
    <>
      <PageHeader title="Departments" description="Legal, internal audit, marketing, facilities and the bank's other support departments. Each has three processes: requests are decided by someone other than the requester where the process needs it, by an executive above its threshold, and completed against a target." />
      <ErrorMessage error={departments.error} />
      {departments.data && <DepartmentGrid departments={departments.data} selected={selected} onSelect={setSelected} />}
      {department && <DepartmentPanel key={department.code} department={department} />}
      <div className="mt-6">
        <CoveragePanel />
      </div>
    </>
  );
}
