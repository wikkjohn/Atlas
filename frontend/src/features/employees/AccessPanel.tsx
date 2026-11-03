import { useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { formatTimestamp } from "@/features/dashboard/format";
import { useAccessGrants, useGrantAccess } from "@/services/events";

/** Phase 74: Information Security's access requests — raised by HR's hires through the
 * outbox; granting one tells HR, which closes the joiner's "Systems access" task. */
export function AccessPanel() {
  const { can } = useAuth();
  const [status, setStatus] = useState("requested");
  const grants = useAccessGrants(status);
  const grant = useGrantAccess();
  return (
    <section aria-label="Systems access" className="mb-4 rounded-xl border border-slate-200 bg-white p-4 text-xs text-slate-600 shadow-sm">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-900">Systems access</h2>
        <select aria-label="Access status" className="rounded-md border border-slate-200 px-2 py-1" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="requested">Requested</option>
          <option value="granted">Granted</option>
          <option value="revoked">Revoked</option>
          <option value="">All</option>
        </select>
      </div>
      <ErrorMessage error={grants.error ?? grant.error} />
      {grants.data?.length === 0 && <p>No {status || ""} access grants.</p>}
      <ul className="space-y-1">
        {grants.data?.map((g) => (
          <li key={g.id} className="flex flex-wrap items-center justify-between gap-2">
            <span>
              {g.grant_number} · {g.employee_name} ({g.employee_number}) · {g.profile} · {g.status}
              {g.granted_at && ` ${formatTimestamp(g.granted_at)}`}
              {g.revoked_at && ` ${formatTimestamp(g.revoked_at)}: ${g.revoke_reason}`}
            </span>
            {g.status === "requested" && can("users:manage") && (
              <Button size="sm" variant="secondary" disabled={grant.isPending} onClick={() => grant.mutate(g.id)}>
                Grant access
              </Button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
