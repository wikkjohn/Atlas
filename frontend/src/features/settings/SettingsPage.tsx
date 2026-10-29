import { Check, Plus, Search } from "lucide-react";
import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { SyntheticDataBadge } from "@/components/SyntheticDataBadge";
import { formatTimestamp } from "@/features/dashboard/format";
import { HealthTiles, PlatformDetails } from "@/features/dashboard/PlatformHealth";
import { JobsPanel } from "@/features/settings/JobsPanel";
import { ObservabilityPanel } from "@/features/settings/ObservabilityPanel";
import { SimulationHistoryPanel } from "@/features/settings/SimulationHistoryPanel";
import { useCreateUser, useRoles, useUpdateUser, useUsers } from "@/services/enterprise";
import { useHealth, useSystemInfo, useSystemStatus } from "@/services/queries";
import type { Role } from "@/types/enterprise";

const PAGE = 20;
const SERVICE_ROLES = new Set(["automated_policy", "system_scheduler"]);
const USERNAME = /^[a-z0-9][a-z0-9._-]{2,63}$/;
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

// --- Users ------------------------------------------------------------------------------------

function CreateUserDialog({ roles, onClose }: { roles: Role[]; onClose: () => void }) {
  const create = useCreateUser();
  const people = roles.filter((r) => !SERVICE_ROLES.has(r.code));
  const [form, setForm] = useState({
    username: "",
    email: "",
    display_name: "",
    password: "",
    role: "banking_employee",
  });
  const [submitted, setSubmitted] = useState(false);
  const errors = {
    username: USERNAME.test(form.username.trim().toLowerCase())
      ? null
      : "3–64 characters: lower-case letters, digits, dots, hyphens, underscores.",
    email: EMAIL.test(form.email.trim()) ? null : "A valid email address.",
    display_name: form.display_name.trim() ? null : "Required.",
    password: form.password.length >= 12 ? null : "At least 12 characters.",
  };
  const valid = Object.values(errors).every((e) => e === null);
  const show = (key: keyof typeof errors) => (submitted ? errors[key] : null);
  const set = (key: keyof typeof form) => (value: string) => setForm({ ...form, [key]: value });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (!valid) return;
    create.mutate(
      { ...form, username: form.username.trim().toLowerCase(), email: form.email.trim() },
      { onSuccess: onClose },
    );
  };

  return (
    <Modal title="Create a user" onClose={onClose}>
      <form id="create-user" aria-label="Create a user" onSubmit={submit} className="space-y-3">
        <Field label="Username" error={show("username")}>
          {(p) => <input {...p} autoComplete="off" className={inputClass} value={form.username} onChange={(e) => set("username")(e.target.value)} />}
        </Field>
        <Field label="Email" error={show("email")}>
          {(p) => <input {...p} type="email" className={inputClass} value={form.email} onChange={(e) => set("email")(e.target.value)} />}
        </Field>
        <Field label="Display name" error={show("display_name")}>
          {(p) => <input {...p} className={inputClass} value={form.display_name} onChange={(e) => set("display_name")(e.target.value)} />}
        </Field>
        <Field label="Initial password" hint="At least 12 characters; share it securely." error={show("password")}>
          {(p) => (
            <input {...p} type="password" autoComplete="new-password" className={inputClass} value={form.password} onChange={(e) => set("password")(e.target.value)} />
          )}
        </Field>
        <Field label="Role">
          {(p) => (
            <select {...p} className={inputClass} value={form.role} onChange={(e) => set("role")(e.target.value)}>
              {people.map((r) => (
                <option key={r.code} value={r.code}>
                  {r.name}
                </option>
              ))}
            </select>
          )}
        </Field>
      </form>
      <ErrorMessage error={create.error} className="mt-3" />
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" form="create-user" disabled={create.isPending}>
          Create user
        </Button>
      </div>
    </Modal>
  );
}

function UsersPanel({ roles }: { roles: Role[] }) {
  const { user: me, can } = useAuth();
  const manage = can("users:manage");
  const [kind, setKind] = useState<"people" | "service">("people");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const users = useUsers({ kind, q: q || null, limit: PAGE, offset });
  const update = useUpdateUser();
  const people = roles.filter((r) => !SERVICE_ROLES.has(r.code));

  return (
    <Panel
      title="Users"
      subtitle="Sign-ins and system principals. Roles grant permissions; the backend enforces them."
      actions={
        manage ? (
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus aria-hidden className="h-3.5 w-3.5" /> Create user
          </Button>
        ) : undefined
      }
    >
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <div role="tablist" aria-label="User kind" className="inline-flex rounded-lg border border-slate-200 p-0.5 text-xs">
          {(["people", "service"] as const).map((k) => (
            <button
              key={k}
              role="tab"
              type="button"
              aria-selected={kind === k}
              onClick={() => {
                setKind(k);
                setOffset(0);
              }}
              className={`rounded-md px-2.5 py-1 font-medium ${kind === k ? "bg-navy-900 text-white" : "text-slate-600 hover:bg-slate-50"}`}
            >
              {k === "people" ? "People" : "Service accounts"}
            </button>
          ))}
        </div>
        <div className="relative">
          <Search aria-hidden className="pointer-events-none absolute top-2 left-2.5 h-4 w-4 text-slate-400" />
          <input
            aria-label="Search users"
            placeholder="Search users"
            className={`${inputClass} pl-8`}
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
          />
        </div>
      </div>
      <ErrorMessage error={users.error ?? update.error} className="mb-3" />
      {kind === "service" && (
        <p className="mb-3 text-xs text-slate-500">
          Service accounts act inside the platform — simulated staff and the policy engine — and can never sign in. They
          keep their role; deactivating the policy engine switches automated approvals off.
        </p>
      )}
      <div className="overflow-x-auto rounded-xl border border-slate-200">
        <table aria-label="Users" className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="px-3 py-2">User</th>
              <th className="px-3 py-2">Role</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Last sign-in</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {(users.data?.items ?? []).map((u) => {
              const self = u.id === me?.id;
              return (
                <tr key={u.id}>
                  <td className="px-3 py-2">
                    <div className="font-medium text-slate-900">{u.display_name}</div>
                    <div className="text-xs text-slate-500">
                      {u.username} · {u.email}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    {manage && !u.is_service_account && !self ? (
                      <select
                        aria-label={`Role of ${u.username}`}
                        className={`${inputClass} py-1 text-xs`}
                        value={u.role}
                        disabled={update.isPending}
                        onChange={(e) => update.mutate({ id: u.id, role: e.target.value })}
                      >
                        {people.map((r) => (
                          <option key={r.code} value={r.code}>
                            {r.name}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className="text-slate-700">{u.role_name}</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <StatusPill tone={u.is_active ? "good" : "neutral"} label={u.is_active ? "Active" : "Inactive"} />
                      {manage && !self && (
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={update.isPending}
                          aria-label={`${u.is_active ? "Deactivate" : "Activate"} ${u.username}`}
                          onClick={() => update.mutate({ id: u.id, is_active: !u.is_active })}
                        >
                          {u.is_active ? "Deactivate" : "Activate"}
                        </Button>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-600">{u.is_service_account ? "Cannot sign in" : formatTimestamp(u.last_login_at)}</td>
                </tr>
              );
            })}
            {users.data?.items.length === 0 && (
              <tr>
                <td colSpan={4} className="px-3 py-6 text-center text-sm text-slate-500">
                  No users match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {users.data && <Pagination total={users.data.total} limit={PAGE} offset={offset} onChange={setOffset} />}
      {creating && <CreateUserDialog roles={roles} onClose={() => setCreating(false)} />}
    </Panel>
  );
}

// --- Roles ------------------------------------------------------------------------------------

function RolesMatrix({ roles }: { roles: Role[] }) {
  const permissions = [...new Set(roles.flatMap((r) => r.permissions))].sort();
  return (
    <Panel title="Roles and permissions" subtitle="Defined in code and enforced on every request">
      <div className="-mx-5 -my-5 overflow-x-auto">
        <table aria-label="Role permissions" className="min-w-full text-xs">
          <thead className="bg-slate-50 text-left font-medium text-slate-500">
            <tr>
              <th className="sticky left-0 bg-slate-50 px-3 py-2">Permission</th>
              {roles.map((r) => (
                <th key={r.code} scope="col" className="px-2 py-2 text-center whitespace-nowrap">
                  {r.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {permissions.map((p) => (
              <tr key={p}>
                <th scope="row" className="sticky left-0 bg-white px-3 py-1.5 text-left font-mono font-normal text-slate-700">
                  {p}
                </th>
                {roles.map((r) => (
                  <td key={r.code} className="px-2 py-1.5 text-center">
                    {r.permissions.includes(p) ? (
                      <Check aria-label={`${r.name}: ${p}`} className="mx-auto h-3.5 w-3.5 text-emerald-600" />
                    ) : (
                      <span aria-hidden className="text-slate-300">
                        ·
                      </span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

// --- Page ------------------------------------------------------------------------------------

export function SettingsPage() {
  const { can } = useAuth();
  const health = useHealth();
  const status = useSystemStatus();
  const info = useSystemInfo();
  const roles = useRoles();

  return (
    <div className="space-y-6">
      <PageHeader
        title="System Settings"
        description="Platform health, build and database details, observability, background jobs, simulation history, users, roles and permissions."
        actions={<SyntheticDataBadge />}
      />
      <HealthTiles health={health} status={status} info={info} />
      <PlatformDetails status={status} info={info} />
      <ErrorMessage error={roles.error} />
      {can("observability:read") && <ObservabilityPanel />}
      {can("jobs:read") && <JobsPanel />}
      {can("simulations:manage") && <SimulationHistoryPanel />}
      {can("users:read") && roles.data && <UsersPanel roles={roles.data} />}
      {roles.data && <RolesMatrix roles={roles.data} />}
    </div>
  );
}
