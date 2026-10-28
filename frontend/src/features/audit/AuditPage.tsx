import { Fragment, useState } from "react";

import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { formatTimestamp } from "@/features/dashboard/format";
import { useAuditEvents } from "@/services/enterprise";

const PAGE_SIZE = 50;
const ENTITY_TYPES = ["", "user", "country", "organization", "employee"];

export function AuditPage() {
  const [action, setAction] = useState("");
  const [entityType, setEntityType] = useState("");
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const events = useAuditEvents({
    action: action.trim() || undefined,
    entity_type: entityType || undefined,
    limit: PAGE_SIZE,
    offset,
  });

  return (
    <>
      <PageHeader
        title="Audit Center"
        description="Append-only record of security events and changes. Records cannot be edited or deleted — the database rejects it."
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          aria-label="Action"
          placeholder="Action, e.g. employee.* or auth.login_failed"
          className="w-80 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm"
          value={action}
          onChange={(e) => {
            setAction(e.target.value);
            setOffset(0);
          }}
        />
        <select
          aria-label="Entity type"
          className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm"
          value={entityType}
          onChange={(e) => {
            setEntityType(e.target.value);
            setOffset(0);
          }}
        >
          {ENTITY_TYPES.map((t) => (
            <option key={t} value={t}>
              {t ? t : "All entities"}
            </option>
          ))}
        </select>
      </div>
      <ErrorMessage error={events.error} className="mb-4" />
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="px-4 py-2.5">Time</th>
              <th className="px-4 py-2.5">Action</th>
              <th className="px-4 py-2.5">Actor</th>
              <th className="px-4 py-2.5">Entity</th>
              <th className="px-4 py-2.5">Correlation ID</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {events.data?.items.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                  No events match.
                </td>
              </tr>
            )}
            {events.data?.items.map((event) => (
              <Fragment key={event.id}>
                <tr
                  className="cursor-pointer hover:bg-slate-50"
                  aria-expanded={expanded === event.id}
                  onClick={() => setExpanded(expanded === event.id ? null : event.id)}
                >
                  <td className="px-4 py-2.5 whitespace-nowrap text-slate-600">
                    {formatTimestamp(event.timestamp)}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-slate-900">{event.action}</td>
                  <td className="px-4 py-2.5 text-slate-700">{event.actor_username ?? "system"}</td>
                  <td className="px-4 py-2.5 text-slate-600">
                    {event.entity_type}
                    {event.entity_id && (
                      <span className="ml-1 font-mono text-[11px] text-slate-400">
                        {event.entity_id.slice(0, 8)}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-[11px] text-slate-500">
                    {event.correlation_id ?? "—"}
                  </td>
                </tr>
                {expanded === event.id && (
                  <tr className="bg-slate-50">
                    <td colSpan={5} className="px-4 py-3">
                      <pre
                        aria-label="Event metadata"
                        className="overflow-x-auto rounded-lg bg-navy-950 p-3 font-mono text-xs text-slate-100"
                      >
                        {JSON.stringify(event.metadata, null, 2)}
                      </pre>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {events.data && (
        <div className="mt-3">
          <Pagination total={events.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
        </div>
      )}
    </>
  );
}
