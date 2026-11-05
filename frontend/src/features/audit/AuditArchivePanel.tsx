import { Archive, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { inputClass } from "@/components/Field";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { formatTimestamp } from "@/features/dashboard/format";
import { useArchivedEvents, useAuditArchives, useCreateArchive, useVerifyArchive } from "@/services/governance";

/** Phase 85: old audit events moved to compressed files, each chained to the one before. */
export function AuditArchivePanel() {
  const { can } = useAuth();
  const archives = useAuditArchives();
  const create = useCreateArchive();
  const verify = useVerifyArchive();
  const [days, setDays] = useState("365");
  const [open, setOpen] = useState<string | null>(null);
  const [action, setAction] = useState("");
  const events = useArchivedEvents(open, action.trim());
  const [outcome, setOutcome] = useState<string | null>(null);

  return (
    <Panel
      title="Audit-log archive"
      subtitle="Events past the online period, in compressed files whose SHA-256 digests form a chain"
      className="mb-4"
    >
      {can("audit:archive") && (
        <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
          <label htmlFor="archive-days" className="text-xs text-slate-600">
            Archive events older than (days)
          </label>
          <input id="archive-days" className={`${inputClass} w-24`} value={days} onChange={(e) => setDays(e.target.value)} inputMode="numeric" />
          <Button
            size="sm"
            disabled={create.isPending || !/^\d+$/.test(days)}
            onClick={() =>
              create.mutate(Number(days), {
                onSuccess: (a) =>
                  setOutcome(a ? `Archive #${a.archive_number}: ${a.events} events moved.` : "No events are that old."),
              })
            }
          >
            <Archive aria-hidden className="h-4 w-4" /> Archive
          </Button>
          {outcome && (
            <span role="status" className="text-xs text-emerald-700">
              {outcome}
            </span>
          )}
        </div>
      )}
      <ErrorMessage error={archives.error ?? create.error ?? verify.error} />
      {archives.data?.length === 0 && <p className="text-sm text-slate-500">Nothing archived yet: every event is online.</p>}
      {archives.data && archives.data.length > 0 && (
        <table aria-label="Audit archives" className="min-w-full text-xs">
          <thead className="text-left text-slate-500">
            <tr>
              <th className="py-1 pr-3 font-medium">Archive</th>
              <th className="py-1 pr-3 font-medium">Events</th>
              <th className="py-1 pr-3 font-medium">Period</th>
              <th className="py-1 pr-3 font-medium">Digest</th>
              <th className="py-1 pr-3 font-medium">Verified</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {archives.data.map((a) => (
              <tr key={a.id} className="border-t border-slate-100">
                <td className="py-1 pr-3">#{a.archive_number}</td>
                <td className="py-1 pr-3 tabular-nums">{a.events}</td>
                <td className="py-1 pr-3">
                  {formatTimestamp(a.first_event_at)} – {formatTimestamp(a.last_event_at)}
                </td>
                <td className="py-1 pr-3 font-mono" title={a.sha256}>
                  {a.sha256.slice(0, 12)}…
                </td>
                <td className="py-1 pr-3">
                  {a.verification ? (
                    <StatusPill tone={a.verification.ok ? "good" : "bad"} label={a.verification.ok ? "Intact" : a.verification.problems.join("; ")} compact />
                  ) : (
                    "—"
                  )}
                </td>
                <td className="py-1 text-right whitespace-nowrap">
                  <Button size="sm" variant="secondary" aria-label={`Verify archive ${a.archive_number}`} disabled={verify.isPending} onClick={() => verify.mutate(a.id)}>
                    <ShieldCheck aria-hidden className="h-3.5 w-3.5" /> Verify
                  </Button>{" "}
                  <Button size="sm" variant="ghost" aria-label={`Search archive ${a.archive_number}`} onClick={() => setOpen(open === a.id ? null : a.id)}>
                    Search
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {open && (
        <section aria-label="Archived events" className="mt-3 space-y-2">
          <input aria-label="Archived action" placeholder="Action, e.g. auth.*" className={`${inputClass} w-72`} value={action} onChange={(e) => setAction(e.target.value)} />
          <ErrorMessage error={events.error} />
          {events.data && (
            <>
              <p className="text-xs text-slate-500">{events.data.total} matching event(s)</p>
              <ul className="space-y-1 font-mono text-[11px] text-slate-700">
                {events.data.items.map((e) => (
                  <li key={e.id}>
                    {formatTimestamp(e.timestamp)} · {e.action} · {e.entity_type} {e.entity_id ?? ""}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}
    </Panel>
  );
}
