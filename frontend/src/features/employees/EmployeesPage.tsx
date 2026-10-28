import { Search, UserPlus } from "lucide-react";
import { type FormEvent, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { formatMoney, humanize, toMinorUnits, currencyDigits } from "@/services/format";
import {
  useCreateEmployee,
  useDirectReports,
  useEmployee,
  useEmployees,
  useOrganization,
  useOrganizations,
  useReportingChain,
  useRoles,
  useUpdateEmployee,
} from "@/services/enterprise";
import type { Employee, EmploymentStatus, Organization } from "@/types/enterprise";

const PAGE_SIZE = 25;
const STATUS_TONE: Record<EmploymentStatus, Tone> = {
  active: "good",
  on_leave: "warn",
  terminated: "neutral",
};

function Compensation({ employee }: { employee: Employee }) {
  if (employee.annual_compensation === null || !employee.compensation_currency) {
    return <span className="text-xs text-slate-400">Restricted</span>;
  }
  return <>{formatMoney(employee.annual_compensation, employee.compensation_currency)}</>;
}

/** Departments and teams, the only units staff can be assigned to. */
function useStaffableUnits() {
  const departments = useOrganizations({ organization_type: "department", status: "active" });
  const teams = useOrganizations({ organization_type: "team", status: "active" });
  const units = useMemo(
    () =>
      [...(departments.data?.items ?? []), ...(teams.data?.items ?? [])].sort((a, b) =>
        `${a.country_code}${a.name}`.localeCompare(`${b.country_code}${b.name}`),
      ),
    [departments.data, teams.data],
  );
  return { units, loading: departments.isLoading || teams.isLoading };
}

function unitLabel(unit: Organization) {
  return `${unit.country_code ?? "—"} · ${unit.name} (${unit.organization_type === "team" ? "team" : "department"})`;
}

function HireDialog({ onClose }: { onClose: () => void }) {
  const create = useCreateEmployee();
  const roles = useRoles();
  const { units } = useStaffableUnits();
  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    job_title: "",
    organization_id: "",
    manager_id: "",
    role: "banking_employee",
    salary: "",
  });
  const unit = units.find((u) => u.id === form.organization_id);
  const departmentId = unit?.organization_type === "team" ? unit.parent_organization_id : unit?.id;
  const colleagues = useEmployees(
    { department_id: departmentId ?? undefined, employment_status: "active", limit: 200 },
    Boolean(departmentId),
  );
  const currency = unit?.currency ?? null;
  const set = (key: keyof typeof form) => (value: string) => setForm({ ...form, [key]: value });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!currency) return;
    create.mutate(
      {
        first_name: form.first_name,
        last_name: form.last_name,
        job_title: form.job_title,
        organization_id: form.organization_id,
        manager_id: form.manager_id || null,
        role: form.role,
        annual_compensation: toMinorUnits(Number(form.salary), currency),
      },
      { onSuccess: onClose },
    );
  };

  return (
    <Modal
      wide
      title="Hire employee"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="hire-employee" disabled={create.isPending}>
            {create.isPending ? "Saving…" : "Hire"}
          </Button>
        </>
      }
    >
      <form id="hire-employee" onSubmit={onSubmit} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="First name">
          {(p) => (
            <input {...p} className={inputClass} required value={form.first_name} onChange={(e) => set("first_name")(e.target.value)} />
          )}
        </Field>
        <Field label="Last name">
          {(p) => (
            <input {...p} className={inputClass} required value={form.last_name} onChange={(e) => set("last_name")(e.target.value)} />
          )}
        </Field>
        <Field label="Job title">
          {(p) => (
            <input {...p} className={inputClass} required minLength={2} value={form.job_title} onChange={(e) => set("job_title")(e.target.value)} />
          )}
        </Field>
        <Field label="Unit" hint="Staff join a department or a team.">
          {(p) => (
            <select
              {...p}
              className={inputClass}
              required
              value={form.organization_id}
              onChange={(e) => setForm({ ...form, organization_id: e.target.value, manager_id: "" })}
            >
              <option value="">Select a unit…</option>
              {units.map((u) => (
                <option key={u.id} value={u.id}>
                  {unitLabel(u)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Manager" hint="Optional; anyone active in the same department.">
          {(p) => (
            <select
              {...p}
              className={inputClass}
              disabled={!departmentId}
              value={form.manager_id}
              onChange={(e) => set("manager_id")(e.target.value)}
            >
              <option value="">No manager</option>
              {colleagues.data?.items.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.full_name} — {c.job_title}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Platform role">
          {(p) => (
            <select {...p} className={inputClass} value={form.role} onChange={(e) => set("role")(e.target.value)}>
              {roles.data?.map((r) => (
                <option key={r.code} value={r.code}>
                  {r.name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field
          label={`Annual compensation${currency ? ` (${currency})` : ""}`}
          hint={currency ? "Whole units; recorded in the country's currency." : "Select a unit first."}
        >
          {(p) => (
            <input
              {...p}
              className={inputClass}
              type="number"
              min={0}
              step={1}
              required
              disabled={!currency}
              value={form.salary}
              onChange={(e) => set("salary")(e.target.value)}
            />
          )}
        </Field>
      </form>
      <p className="mt-3 text-xs text-slate-500">
        A synthetic email address in atlasbank.example and an employee number are assigned
        automatically.
      </p>
      <ErrorMessage error={create.error} className="mt-4" />
    </Modal>
  );
}

function EditForm({ employee, onDone }: { employee: Employee; onDone: () => void }) {
  const update = useUpdateEmployee();
  const { can } = useAuth();
  const colleagues = useEmployees({ department_id: employee.department_id, employment_status: "active", limit: 200 });
  const currency = employee.compensation_currency;
  const [form, setForm] = useState({
    job_title: employee.job_title,
    employment_status: employee.employment_status,
    manager_id: employee.manager?.id ?? "",
    salary:
      employee.annual_compensation !== null && currency
        ? String(employee.annual_compensation / 10 ** currencyDigits(currency))
        : "",
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const body: Record<string, unknown> = {
      job_title: form.job_title,
      employment_status: form.employment_status,
      manager_id: form.manager_id || null,
    };
    if (can("employees:read_compensation") && currency && form.salary !== "") {
      body.annual_compensation = toMinorUnits(Number(form.salary), currency);
    }
    update.mutate({ id: employee.id, body }, { onSuccess: onDone });
  };

  return (
    <form onSubmit={onSubmit} aria-label="Edit employee" className="space-y-4 rounded-lg border border-slate-200 p-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Job title">
          {(p) => (
            <input {...p} className={inputClass} required value={form.job_title} onChange={(e) => setForm({ ...form, job_title: e.target.value })} />
          )}
        </Field>
        <Field label="Employment status">
          {(p) => (
            <select
              {...p}
              className={inputClass}
              value={form.employment_status}
              onChange={(e) => setForm({ ...form, employment_status: e.target.value as EmploymentStatus })}
            >
              <option value="active">Active</option>
              <option value="on_leave">On leave</option>
              <option value="terminated">Terminated</option>
            </select>
          )}
        </Field>
        <Field label="Manager">
          {(p) => (
            <select {...p} className={inputClass} value={form.manager_id} onChange={(e) => setForm({ ...form, manager_id: e.target.value })}>
              <option value="">No manager</option>
              {colleagues.data?.items
                .filter((c) => c.id !== employee.id)
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.full_name} — {c.job_title}
                  </option>
                ))}
            </select>
          )}
        </Field>
        {currency && (
          <Field label={`Annual compensation (${currency})`}>
            {(p) => (
              <input
                {...p}
                className={inputClass}
                type="number"
                min={0}
                value={form.salary}
                onChange={(e) => setForm({ ...form, salary: e.target.value })}
              />
            )}
          </Field>
        )}
      </div>
      <ErrorMessage error={update.error} />
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={update.isPending}>
          Save changes
        </Button>
      </div>
    </form>
  );
}

function EmployeeProfile({ id, onClose, onOpen }: { id: string; onClose: () => void; onOpen: (id: string) => void }) {
  const { can } = useAuth();
  const employee = useEmployee(id);
  const chain = useReportingChain(id);
  const reports = useDirectReports(id);
  const [editing, setEditing] = useState(false);
  const e = employee.data;

  return (
    <Modal wide title="Employee profile" onClose={onClose}>
      <ErrorMessage error={employee.error} />
      {e && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="text-lg font-semibold text-slate-900">{e.full_name}</h3>
              <p className="text-sm text-slate-600">
                {e.job_title} · {e.organization_name}
              </p>
              <p className="mt-0.5 font-mono text-xs text-slate-500">
                {e.employee_number} · {e.email}
              </p>
            </div>
            <StatusPill tone={STATUS_TONE[e.employment_status]} label={humanize(e.employment_status)} />
          </div>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4">
            {(
              [
                ["Department", e.department_name],
                ["Country", e.country_code],
                ["Platform role", humanize(e.role)],
                ["Compensation", <Compensation employee={e} />],
              ] as const
            ).map(([term, value]) => (
              <div key={term}>
                <dt className="text-xs font-medium tracking-wide text-slate-500 uppercase">{term}</dt>
                <dd className="mt-0.5 text-slate-900">{value}</dd>
              </div>
            ))}
          </dl>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <section aria-label="Reporting chain">
              <h4 className="mb-1.5 text-xs font-semibold tracking-wide text-slate-500 uppercase">Reports to</h4>
              {chain.data?.length === 0 && <p className="text-sm text-slate-500">Top of reporting line.</p>}
              <ol className="space-y-1 text-sm">
                {chain.data?.map((m) => (
                  <li key={m.id}>
                    <button type="button" className="text-navy-700 hover:underline" onClick={() => onOpen(m.id)}>
                      {m.full_name}
                    </button>
                    <span className="text-slate-500"> · {m.job_title}</span>
                  </li>
                ))}
              </ol>
            </section>
            <section aria-label="Direct reports">
              <h4 className="mb-1.5 text-xs font-semibold tracking-wide text-slate-500 uppercase">
                Direct reports {reports.data && `(${reports.data.length})`}
              </h4>
              {reports.data?.length === 0 && <p className="text-sm text-slate-500">None.</p>}
              <ul className="space-y-1 text-sm">
                {reports.data?.map((r) => (
                  <li key={r.id}>
                    <button type="button" className="text-navy-700 hover:underline" onClick={() => onOpen(r.id)}>
                      {r.full_name}
                    </button>
                    <span className="text-slate-500"> · {r.job_title}</span>
                  </li>
                ))}
              </ul>
            </section>
          </div>
          {can("employees:manage") &&
            (editing ? (
              <EditForm employee={e} onDone={() => setEditing(false)} />
            ) : (
              <Button variant="secondary" onClick={() => setEditing(true)}>
                Edit employee
              </Button>
            ))}
        </div>
      )}
    </Modal>
  );
}

export function EmployeesPage() {
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [hiring, setHiring] = useState(false);
  const [profileId, setProfileId] = useState<string | null>(null);
  const organizationId = params.get("organization_id");
  const status = params.get("employment_status") ?? "";
  const offset = Number(params.get("offset") ?? 0);
  const filterUnit = useOrganization(organizationId);

  const employees = useEmployees({
    q: params.get("q") ?? undefined,
    organization_id: organizationId ?? undefined,
    employment_status: status || undefined,
    limit: PAGE_SIZE,
    offset,
  });

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    if (!("offset" in changes)) next.delete("offset");
    setParams(next);
  };

  return (
    <>
      <PageHeader
        title="Employees"
        description="Synthetic workforce registry. Compensation is recorded in each country's currency and visible only to permitted roles."
        actions={
          can("employees:manage") && (
            <Button onClick={() => setHiring(true)}>
              <UserPlus aria-hidden className="h-4 w-4" />
              Hire employee
            </Button>
          )
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <form
          role="search"
          onSubmit={(e) => {
            e.preventDefault();
            update({ q: search.trim() || null });
          }}
          className="relative"
        >
          <Search aria-hidden className="pointer-events-none absolute top-2 left-2.5 h-4 w-4 text-slate-400" />
          <input
            aria-label="Search employees"
            placeholder="Name, email, number or title"
            className="w-72 rounded-lg border border-slate-200 bg-white py-1.5 pr-3 pl-8 text-sm"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </form>
        <select
          aria-label="Employment status"
          className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm"
          value={status}
          onChange={(e) => update({ employment_status: e.target.value || null })}
        >
          <option value="">Any status</option>
          <option value="active">Active</option>
          <option value="on_leave">On leave</option>
          <option value="terminated">Terminated</option>
        </select>
        {organizationId && (
          <span className="inline-flex items-center gap-2 rounded-full bg-navy-900/5 px-3 py-1 text-xs text-navy-900">
            Unit: {filterUnit.data?.name ?? "…"}
            <button type="button" aria-label="Clear unit filter" className="font-bold" onClick={() => update({ organization_id: null })}>
              ×
            </button>
          </span>
        )}
      </div>
      <ErrorMessage error={employees.error} className="mb-4" />
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="px-4 py-2.5">Employee</th>
              <th className="px-4 py-2.5">Job title</th>
              <th className="px-4 py-2.5">Unit</th>
              <th className="px-4 py-2.5">Country</th>
              <th className="px-4 py-2.5">Status</th>
              <th className="px-4 py-2.5 text-right">Compensation</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {employees.isLoading && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-slate-500">
                  Loading…
                </td>
              </tr>
            )}
            {employees.data?.items.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-slate-500">
                  No employees match.
                </td>
              </tr>
            )}
            {employees.data?.items.map((e) => (
              <tr key={e.id} className="cursor-pointer hover:bg-slate-50" onClick={() => setProfileId(e.id)}>
                <td className="px-4 py-2.5">
                  <button type="button" className="text-left font-medium text-slate-900 hover:underline" onClick={() => setProfileId(e.id)}>
                    {e.full_name}
                  </button>
                  <div className="font-mono text-[11px] text-slate-500">{e.employee_number}</div>
                </td>
                <td className="px-4 py-2.5 text-slate-700">{e.job_title}</td>
                <td className="px-4 py-2.5 text-slate-600">{e.organization_name}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-slate-600">{e.country_code}</td>
                <td className="px-4 py-2.5">
                  <StatusPill tone={STATUS_TONE[e.employment_status]} label={humanize(e.employment_status)} />
                </td>
                <td className="px-4 py-2.5 text-right whitespace-nowrap text-slate-900">
                  <Compensation employee={e} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {employees.data && (
        <div className="mt-3">
          <Pagination
            total={employees.data.total}
            limit={PAGE_SIZE}
            offset={offset}
            onChange={(next) => update({ offset: next ? String(next) : null })}
          />
        </div>
      )}
      {hiring && <HireDialog onClose={() => setHiring(false)} />}
      {profileId && (
        <EmployeeProfile key={profileId} id={profileId} onClose={() => setProfileId(null)} onOpen={setProfileId} />
      )}
    </>
  );
}
