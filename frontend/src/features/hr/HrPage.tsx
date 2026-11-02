import { useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { formatExactMoney, humanize, toMinorUnits } from "@/services/format";
import {
  useAddCandidate,
  useAssign,
  useCandidates,
  useCapacity,
  useCompleteTask,
  useCreateShift,
  useDecideLeave,
  useDecideRequisition,
  useDepartments,
  useHire,
  useHrSummary,
  useLeave,
  useLeaveSweep,
  useOffer,
  useOnboarding,
  useOpenRequisition,
  useRequestLeave,
  useRequisitions,
  useShifts,
} from "@/services/hr";
import type { Candidate, LeaveRequest, Requisition } from "@/types/hr";

const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const today = () => new Date().toISOString().slice(0, 10);
const REQ_TONE: Record<Requisition["status"], Tone> = { open: "warn", approved: "good", filled: "neutral", cancelled: "neutral" };
const CAND_TONE: Record<Candidate["status"], Tone> = { applied: "neutral", offered: "warn", hired: "good", declined: "neutral", rejected: "neutral" };
const LEAVE_TONE: Record<LeaveRequest["status"], Tone> = { requested: "warn", approved: "good", rejected: "neutral", cancelled: "neutral" };

function DepartmentSelect({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  const departments = useDepartments();
  return (
    <select aria-label={label} className={INPUT} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Choose a department</option>
      {departments.data?.map((d) => (
        <option key={d.id} value={d.id}>
          {d.name} ({d.country ?? "—"}, {d.headcount})
        </option>
      ))}
    </select>
  );
}

function CapacityPanel() {
  const [department, setDepartment] = useState("");
  const [on, setOn] = useState(today());
  const capacity = useCapacity(department, on);
  const c = capacity.data;
  return (
    <Panel title="Capacity" subtitle="Who can work in a department on a day: its staff, less those on approved leave; when shifts are rostered that day, only the rostered staff. A simulation run can take its staff from a department's capacity on the simulated day.">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        <DepartmentSelect label="Capacity department" value={department} onChange={setDepartment} />
        <input aria-label="Capacity date" type="date" className={INPUT} value={on} onChange={(e) => setOn(e.target.value)} />
      </div>
      <ErrorMessage error={capacity.error} />
      {c && (
        <p aria-label="Capacity result" className="text-sm text-slate-700">
          {c.available} available of {c.headcount} · {c.on_leave} on leave · {c.shifts} shifts, {c.rostered} rostered
          {Object.keys(c.available_by_role).length > 0 && ` · ${Object.entries(c.available_by_role).map(([role, n]) => `${n} ${role}`).join(", ")}`}
        </p>
      )}
    </Panel>
  );
}

function RequisitionsPanel() {
  const { can } = useAuth();
  const departments = useDepartments();
  const requisitions = useRequisitions();
  const candidates = useCandidates();
  const open = useOpenRequisition();
  const decide = useDecideRequisition();
  const addCandidate = useAddCandidate();
  const offer = useOffer();
  const hire = useHire();
  const [form, setForm] = useState({ department: "", title: "", role: "banking_employee", openings: "1", min: "", max: "", reason: "" });
  const [names, setNames] = useState<Record<string, string>>({});
  const [salaries, setSalaries] = useState<Record<string, string>>({});
  const currency = departments.data?.find((d) => d.id === form.department)?.currency ?? "USD";
  return (
    <Panel title="Requisitions and hiring" subtitle="A department asks to hire within a yearly salary band; someone other than the requester approves it (hr:approve). Candidates are offered a salary inside the band; an accepted offer hires them as employees with an onboarding checklist.">
      {can("hr:manage") && (
        <form
          aria-label="Open requisition"
          className="mb-3 flex flex-wrap items-end gap-2 text-xs"
          onSubmit={(e) => {
            e.preventDefault();
            open.mutate({
              department_id: form.department,
              job_title: form.title,
              role: form.role,
              openings: Number(form.openings),
              salary_min: toMinorUnits(Number(form.min), currency),
              salary_max: toMinorUnits(Number(form.max), currency),
              reason: form.reason,
            });
          }}
        >
          <DepartmentSelect label="Department" value={form.department} onChange={(v) => setForm({ ...form, department: v })} />
          <input aria-label="Job title" placeholder="Job title" className={INPUT} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <select aria-label="Role" className={INPUT} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            {["banking_employee", "department_manager", "compliance_officer"].map((r) => (
              <option key={r} value={r}>
                {humanize(r)}
              </option>
            ))}
          </select>
          <input aria-label="Openings" type="number" min={1} max={50} className={`w-16 ${INPUT}`} value={form.openings} onChange={(e) => setForm({ ...form, openings: e.target.value })} />
          <input aria-label="Salary from" type="number" placeholder={`From (${currency})`} className={`w-28 ${INPUT}`} value={form.min} onChange={(e) => setForm({ ...form, min: e.target.value })} />
          <input aria-label="Salary to" type="number" placeholder={`To (${currency})`} className={`w-28 ${INPUT}`} value={form.max} onChange={(e) => setForm({ ...form, max: e.target.value })} />
          <input aria-label="Reason" placeholder="Why the hire is needed" className={`w-64 ${INPUT}`} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          <Button size="sm" type="submit" disabled={!form.department || !form.title || !form.min || !form.max}>
            Open requisition
          </Button>
          {open.data && <span role="status">{open.data.requisition_number} opened</span>}
        </form>
      )}
      <ErrorMessage error={requisitions.error ?? open.error ?? decide.error ?? addCandidate.error ?? offer.error ?? hire.error} />
      <table aria-label="Requisitions" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {requisitions.data?.items.map((r) => (
            <tr key={r.id} className="align-top">
              <td className="px-2 py-1.5 font-mono text-xs">{r.requisition_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {r.job_title} · {r.department} · {humanize(r.role)} · {r.filled}/{r.openings} filled · {formatExactMoney(r.salary_min, r.currency)} to {formatExactMoney(r.salary_max, r.currency)}
                <ul className="mt-1 space-y-1">
                  {candidates.data
                    ?.filter((c) => c.requisition_number === r.requisition_number)
                    .map((c) => (
                      <li key={c.id} className="flex flex-wrap items-center gap-2">
                        <span className="font-mono">{c.candidate_number}</span> {c.name}
                        <StatusPill compact tone={CAND_TONE[c.status]} label={c.status} />
                        {c.offered_salary !== null && formatExactMoney(c.offered_salary, r.currency)}
                        {c.employee_number && <span className="font-mono">{c.employee_number}</span>}
                        {c.status === "applied" && can("hr:manage") && (
                          <>
                            <input aria-label={`Offer salary for ${c.candidate_number}`} type="number" className={`w-24 ${INPUT}`} value={salaries[c.id] ?? ""} onChange={(e) => setSalaries({ ...salaries, [c.id]: e.target.value })} />
                            <Button size="sm" variant="secondary" aria-label={`Offer ${c.candidate_number}`} disabled={!salaries[c.id]} onClick={() => offer.mutate({ id: c.id, salary: toMinorUnits(Number(salaries[c.id]), r.currency), start_date: today() })}>
                              Offer
                            </Button>
                          </>
                        )}
                        {c.status === "offered" && can("hr:manage") && (
                          <Button size="sm" aria-label={`Hire ${c.candidate_number}`} onClick={() => hire.mutate(c.id)}>
                            Hire
                          </Button>
                        )}
                      </li>
                    ))}
                </ul>
                {r.status === "approved" && can("hr:manage") && (
                  <div className="mt-1 flex items-center gap-1">
                    <input aria-label={`Candidate name for ${r.requisition_number}`} placeholder="First Last" className={`w-40 ${INPUT}`} value={names[r.id] ?? ""} onChange={(e) => setNames({ ...names, [r.id]: e.target.value })} />
                    <Button
                      size="sm"
                      variant="secondary"
                      aria-label={`Add candidate to ${r.requisition_number}`}
                      disabled={(names[r.id] ?? "").trim().split(/\s+/).length < 2}
                      onClick={() => {
                        const [first, ...rest] = (names[r.id] ?? "").trim().split(/\s+/);
                        addCandidate.mutate({ requisitionId: r.id, first_name: first, last_name: rest.join(" ") });
                      }}
                    >
                      Add candidate
                    </Button>
                  </div>
                )}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={REQ_TONE[r.status]} label={r.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {r.status === "open" && can("hr:approve") && (
                  <div className="flex justify-end gap-1">
                    <Button size="sm" aria-label={`Approve ${r.requisition_number}`} onClick={() => decide.mutate({ id: r.id, approve: true })}>
                      Approve
                    </Button>
                    <Button size="sm" variant="secondary" aria-label={`Cancel ${r.requisition_number}`} onClick={() => decide.mutate({ id: r.id, approve: false })}>
                      Cancel
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
          {requisitions.data && requisitions.data.items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No requisitions yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}

function LeavePanel() {
  const { can } = useAuth();
  const leave = useLeave();
  const request = useRequestLeave();
  const decide = useDecideLeave();
  const sweep = useLeaveSweep();
  const [form, setForm] = useState({ employee: "", kind: "annual", start: today(), end: today() });
  return (
    <Panel title="Leave" subtitle="Counted in the business days of the employee's country. Annual leave comes out of 25 days a year; no request may overlap another. Someone other than the requester decides (hr:manage); the sweep marks who is on leave today.">
      {can("hr:manage") && (
        <form
          aria-label="Request leave"
          className="mb-3 flex flex-wrap items-end gap-2 text-xs"
          onSubmit={(e) => {
            e.preventDefault();
            request.mutate({ employee_number: form.employee, kind: form.kind, start_date: form.start, end_date: form.end });
          }}
        >
          <input aria-label="Employee number" placeholder="AGB-0000001" className={`w-32 ${INPUT}`} value={form.employee} onChange={(e) => setForm({ ...form, employee: e.target.value })} />
          <select aria-label="Leave kind" className={INPUT} value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            {["annual", "sick", "unpaid"].map((k) => (
              <option key={k} value={k}>
                {humanize(k)}
              </option>
            ))}
          </select>
          <input aria-label="From" type="date" className={INPUT} value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} />
          <input aria-label="To" type="date" className={INPUT} value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} />
          <Button size="sm" type="submit" disabled={!form.employee}>
            Request leave
          </Button>
          <Button size="sm" variant="secondary" type="button" onClick={() => sweep.mutate()}>
            Run leave sweep
          </Button>
          {request.data && <span role="status">{request.data.leave_number}: {request.data.days} days</span>}
          {sweep.data && <span role="status">{sweep.data.on_leave} on leave today</span>}
        </form>
      )}
      <ErrorMessage error={leave.error ?? request.error ?? decide.error ?? sweep.error} />
      <table aria-label="Leave requests" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {leave.data?.items.map((l) => (
            <tr key={l.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{l.leave_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {l.employee_name} ({l.employee_number}) · {humanize(l.kind)} · {l.start_date} to {l.end_date} · {l.days} days
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={LEAVE_TONE[l.status]} label={l.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {l.status === "requested" && can("hr:manage") && (
                  <div className="flex justify-end gap-1">
                    <Button size="sm" aria-label={`Approve ${l.leave_number}`} onClick={() => decide.mutate({ id: l.id, approve: true })}>
                      Approve
                    </Button>
                    <Button size="sm" variant="secondary" aria-label={`Reject ${l.leave_number}`} onClick={() => decide.mutate({ id: l.id, approve: false })}>
                      Reject
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
          {leave.data && leave.data.items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No leave requests.</td>
            </tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}

function ShiftsPanel() {
  const { can } = useAuth();
  const [department, setDepartment] = useState("");
  const [on, setOn] = useState(today());
  const [form, setForm] = useState({ start: "9", hours: "8", required: "2" });
  const [who, setWho] = useState<Record<string, string>>({});
  const shifts = useShifts(department, on);
  const create = useCreateShift();
  const assign = useAssign();
  return (
    <Panel title="Shifts" subtitle="Rostering refuses anyone from another department, on leave that day, already on a shift at the same time, over 48 hours that week or with less than 11 hours' rest.">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        <DepartmentSelect label="Shift department" value={department} onChange={setDepartment} />
        <input aria-label="Shift date" type="date" className={INPUT} value={on} onChange={(e) => setOn(e.target.value)} />
        {can("hr:manage") && (
          <>
            <input aria-label="Start hour" type="number" min={0} max={23} className={`w-14 ${INPUT}`} value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} />
            <input aria-label="Hours" type="number" min={1} max={12} className={`w-14 ${INPUT}`} value={form.hours} onChange={(e) => setForm({ ...form, hours: e.target.value })} />
            <input aria-label="People needed" type="number" min={1} max={100} className={`w-14 ${INPUT}`} value={form.required} onChange={(e) => setForm({ ...form, required: e.target.value })} />
            <Button
              size="sm"
              disabled={!department}
              onClick={() => create.mutate({ department_id: department, on, start_hour: Number(form.start), hours: Number(form.hours), required: Number(form.required) })}
            >
              Add shift
            </Button>
          </>
        )}
      </div>
      <ErrorMessage error={shifts.error ?? create.error ?? assign.error} />
      <table aria-label="Shifts" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {shifts.data?.map((s) => (
            <tr key={s.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{s.shift_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {s.department} · {String(s.start_hour).padStart(2, "0")}:00 for {s.hours} h · {s.rostered.length}/{s.required} rostered
                {s.rostered.length > 0 && ` · ${s.rostered.join(", ")}`}
              </td>
              <td className="px-2 py-1.5 text-right">
                {can("hr:manage") && s.rostered.length < s.required && (
                  <div className="flex justify-end gap-1">
                    <input aria-label={`Employee for ${s.shift_number}`} placeholder="AGB-0000001" className={`w-28 ${INPUT}`} value={who[s.id] ?? ""} onChange={(e) => setWho({ ...who, [s.id]: e.target.value })} />
                    <Button size="sm" variant="secondary" aria-label={`Roster onto ${s.shift_number}`} disabled={!who[s.id]} onClick={() => assign.mutate({ id: s.id, employee_number: who[s.id] })}>
                      Roster
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
          {shifts.data && shifts.data.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No shifts that day.</td>
            </tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}

function OnboardingPanel() {
  const { can } = useAuth();
  const tasks = useOnboarding();
  const complete = useCompleteTask();
  const now = today();
  return (
    <Panel title="Onboarding" subtitle="Each new hire's checklist: contract and systems access on the start date, induction within a week, compliance training within 30 days, probation review at 90.">
      <ErrorMessage error={tasks.error ?? complete.error} />
      <table aria-label="Onboarding tasks" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {tasks.data?.map((t) => (
            <tr key={t.id}>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {t.employee_name} ({t.employee_number}) · {t.title} · due {t.due}
                {t.due < now && " · overdue"}
              </td>
              <td className="px-2 py-1.5 text-right">
                {can("hr:manage") && (
                  <Button size="sm" variant="secondary" aria-label={`Complete ${t.code} for ${t.employee_number}`} onClick={() => complete.mutate(t.id)}>
                    Done
                  </Button>
                )}
              </td>
            </tr>
          ))}
          {tasks.data && tasks.data.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No open onboarding tasks.</td>
            </tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}

/** Human resources (Phase 55): hiring, onboarding, leave, shifts and staffing capacity. */
export function HrPage() {
  const summary = useHrSummary();
  return (
    <>
      <PageHeader title="Human Resources" description="Requisitions approved by a second person, offers inside the salary band, onboarding checklists, leave in each country's business days, and shift rosters. A department's capacity on a day can staff a simulation run." />
      {summary.data && (
        <dl aria-label="HR summary" className="mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          {(
            [
              ["Requisitions to approve", summary.data.requisitions_to_approve],
              ["Recruiting", summary.data.requisitions_recruiting],
              ["Offers out", summary.data.offers_out],
              ["Leave to decide", summary.data.leave_to_decide],
              ["On leave today", summary.data.on_leave_today],
              ["Onboarding overdue", summary.data.onboarding_overdue],
              ["Shifts today", summary.data.shifts_today],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="rounded-lg border border-slate-200 bg-white p-3">
              <dt className="text-xs text-slate-500">{label}</dt>
              <dd className="text-lg font-semibold text-slate-900">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="flex flex-col gap-6">
        <CapacityPanel />
        <RequisitionsPanel />
        <LeavePanel />
        <ShiftsPanel />
        <OnboardingPanel />
      </div>
    </>
  );
}
