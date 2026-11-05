import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { SessionTable } from "@/features/security/SecurityPage";
import { useResetMfa, useRevokeUserSessions, useSetScopes, useUserSessions } from "@/services/security";
import type { UserAccount } from "@/types/enterprise";

const list = (text: string) =>
  text
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);

/** Phase 84: an administrator's view of one user's access — scopes, sessions, factor. */
export function UserAccessDialog({ user, onClose }: { user: UserAccount; onClose: () => void }) {
  const { user: me } = useAuth();
  const sessions = useUserSessions(user.id);
  const scopes = useSetScopes();
  const revoke = useRevokeUserSessions();
  const reset = useResetMfa();
  const [countries, setCountries] = useState((user.scope?.countries ?? []).join(", "));
  const [departments, setDepartments] = useState((user.scope?.departments ?? []).join(", "));
  const [saved, setSaved] = useState<string | null>(null);
  const self = user.id === me?.id;

  const save = (event: FormEvent) => {
    event.preventDefault();
    setSaved(null);
    scopes.mutate(
      { userId: user.id, countries: list(countries), departments: list(departments) },
      {
        onSuccess: (s) =>
          setSaved(
            `Saved: ${s.countries?.join(", ") ?? "all countries"}; ${s.departments?.join(", ") ?? "all departments"}.`,
          ),
      },
    );
  };

  return (
    <Modal title={`Access of ${user.username}`} onClose={onClose} wide>
      <div className="space-y-5 text-sm">
        <form onSubmit={save} aria-label="Scopes" className="space-y-3">
          <p className="text-xs text-slate-500">
            Limit where the user's permissions apply. Empty means not limited. Customers and accounts follow the
            customer's country; employees their country and department.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Countries (ISO codes, comma-separated)">
              {(p) => <input {...p} className={inputClass} value={countries} onChange={(e) => setCountries(e.target.value)} placeholder="e.g. GB, IE" />}
            </Field>
            <Field label="Departments (comma-separated)">
              {(p) => <input {...p} className={inputClass} value={departments} onChange={(e) => setDepartments(e.target.value)} placeholder="e.g. Customer Onboarding" />}
            </Field>
          </div>
          <div className="flex items-center gap-3">
            <Button type="submit" size="sm" disabled={scopes.isPending}>
              Save scopes
            </Button>
            {saved && <span role="status" className="text-xs text-emerald-700">{saved}</span>}
          </div>
          <ErrorMessage error={scopes.error} />
        </form>

        <section aria-label="Second factor" className="space-y-2">
          <h3 className="text-sm font-semibold text-slate-900">Second factor</h3>
          <p className="text-xs text-slate-600">
            {user.mfa_enabled ? "An authenticator is enrolled." : "No authenticator enrolled."}
          </p>
          {user.mfa_enabled && !self && (
            <Button size="sm" variant="secondary" disabled={reset.isPending} onClick={() => reset.mutate(user.id, { onSuccess: () => void sessions.refetch() })}>
              Reset authenticator (lost device)
            </Button>
          )}
          <ErrorMessage error={reset.error} />
        </section>

        <section aria-label="User sessions" className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-900">Sessions</h3>
            <Button size="sm" variant="secondary" disabled={revoke.isPending} onClick={() => revoke.mutate(user.id, { onSuccess: () => void sessions.refetch() })}>
              Sign out everywhere
            </Button>
          </div>
          <ErrorMessage error={sessions.error ?? revoke.error} />
          {sessions.data?.length === 0 && <p className="text-xs text-slate-500">No sessions.</p>}
          {sessions.data && sessions.data.length > 0 && <SessionTable sessions={sessions.data} />}
        </section>
      </div>
    </Modal>
  );
}
