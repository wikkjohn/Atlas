import { RotateCcw } from "lucide-react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Panel } from "@/components/Panel";
import { formatTimestamp } from "@/features/dashboard/format";
import { humanize } from "@/services/format";
import { useEventSummary, useRetryDelivery, useStuckEvents } from "@/services/events";

/** Phase 74: the outbox — who publishes what, who it reaches, and what is stuck. */
export function EventsPanel() {
  const { can } = useAuth();
  const summary = useEventSummary();
  const stuck = useStuckEvents();
  const retry = useRetryDelivery();
  const s = summary.data;
  return (
    <Panel
      title="Event pipeline"
      subtitle="Departments integrate through events in an outbox: a publisher records the event in its own transaction, and each subscribing department gets a delivery, retried with back-off until it succeeds. After eight failures a delivery is dead until someone retries it. The events-dispatch schedule delivers what is due every minute."
    >
      <ErrorMessage error={summary.error ?? stuck.error ?? retry.error} className="mb-2" />
      {s && (
        <>
          <p className="mb-2 text-sm text-slate-700">
            {s.events.toLocaleString("en-US")} events · {s.waiting} waiting · {s.dead} dead
            {s.oldest_waiting_seconds !== null && ` · oldest waiting ${Math.round(s.oldest_waiting_seconds / 60)} min`}
          </p>
          <table aria-label="Subscribers" className="mb-3 min-w-full text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr>
                <th className="py-1">Topic</th>
                <th className="py-1">Subscriber</th>
                <th className="py-1">Department</th>
                <th className="py-1 text-right">Delivered</th>
                <th className="py-1 text-right">Waiting</th>
                <th className="py-1 text-right">Dead</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {s.subscribers.map((sub) => (
                <tr key={sub.name}>
                  <td className="py-1.5 font-mono text-xs">{sub.topic}</td>
                  <td className="py-1.5 font-mono text-xs">{sub.name}</td>
                  <td className="py-1.5">{humanize(sub.department)}</td>
                  <td className="py-1.5 text-right">{sub.deliveries.delivered ?? 0}</td>
                  <td className="py-1.5 text-right">{(sub.deliveries.pending ?? 0) + (sub.deliveries.failed ?? 0)}</td>
                  <td className="py-1.5 text-right">{sub.deliveries.dead ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {stuck.data && stuck.data.length > 0 && (
        <ul aria-label="Undelivered events" className="space-y-2">
          {stuck.data.flatMap((e) =>
            e.deliveries
              .filter((d) => d.status === "failed" || d.status === "dead")
              .map((d) => (
                <li key={d.id} className="flex flex-wrap items-start justify-between gap-2 rounded-lg border border-rose-200 bg-rose-50 p-2 text-xs text-rose-900">
                  <span>
                    <span className="font-mono">{e.topic}</span> → <span className="font-mono">{d.subscriber}</span> · {d.status}, {d.attempts} attempts · {d.last_error}
                    {d.status === "failed" && ` · next ${formatTimestamp(d.next_attempt_at)}`}
                  </span>
                  {can("jobs:manage") && (
                    <Button size="sm" variant="secondary" disabled={retry.isPending} onClick={() => retry.mutate(d.id)}>
                      <RotateCcw aria-hidden className="h-3.5 w-3.5" /> Retry
                    </Button>
                  )}
                </li>
              )),
          )}
        </ul>
      )}
    </Panel>
  );
}
