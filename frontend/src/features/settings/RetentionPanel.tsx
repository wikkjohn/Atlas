import { useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { formatTimestamp } from "@/features/dashboard/format";
import { useApplyRetention, useRetentionReview } from "@/services/governance";

const TONE: Record<string, Tone> = { delete: "warn", archive: "neutral", keep: "good", review: "neutral" };
const LABEL: Record<string, string> = { delete: "Delete", archive: "Archive", keep: "Keep", review: "Review" };

/** Phase 85: the retention schedule, how much is past its period, and applying it. */
export function RetentionPanel() {
  const { can } = useAuth();
  const review = useRetentionReview();
  const apply = useApplyRetention();
  const [outcome, setOutcome] = useState<string | null>(null);
  return (
    <Panel
      title="Data retention"
      subtitle="How long each kind of record is kept, and what happens after; applied daily by the retention-apply schedule"
      actions={
        can("retention:apply") ? (
          <Button
            size="sm"
            disabled={apply.isPending}
            onClick={() =>
              apply.mutate(undefined, {
                onSuccess: (r) => {
                  const parts = Object.entries(r.results).map(([k, v]) =>
                    "deleted" in v ? `${k}: ${v.deleted} deleted` : `${k}: ${v.archived ?? 0} archived`,
                  );
                  setOutcome(`Run #${r.run_number}: ${parts.join(", ")}.`);
                },
              })
            }
          >
            Apply the retention schedule
          </Button>
        ) : undefined
      }
    >
      <ErrorMessage error={review.error ?? apply.error} />
      {outcome && (
        <p role="status" className="mb-2 text-xs text-emerald-700">
          {outcome}
        </p>
      )}
      {review.data && (
        <>
          <table aria-label="Retention schedule" className="min-w-full text-xs">
            <thead className="text-left text-slate-500">
              <tr>
                <th className="py-1 pr-3 font-medium">Records</th>
                <th className="py-1 pr-3 font-medium">Kept</th>
                <th className="py-1 pr-3 font-medium">Then</th>
                <th className="py-1 pr-3 text-right font-medium">Rows</th>
                <th className="py-1 pr-3 text-right font-medium">Past the period</th>
              </tr>
            </thead>
            <tbody>
              {review.data.classes.map((c) => (
                <tr key={c.id} className="border-t border-slate-100 align-top">
                  <td className="py-1 pr-3">
                    <div className="font-medium text-slate-800">{c.name}</div>
                    <div className="text-[11px] text-slate-500">{c.purpose}</div>
                  </td>
                  <td className="py-1 pr-3">{c.retention}</td>
                  <td className="py-1 pr-3">
                    <StatusPill tone={TONE[c.action]} label={LABEL[c.action]} compact />
                    {c.applied_by && <div className="text-[11px] text-slate-500">by {c.applied_by}</div>}
                  </td>
                  <td className="py-1 pr-3 text-right tabular-nums">{c.rows.toLocaleString()}</td>
                  <td className="py-1 pr-3 text-right tabular-nums">{c.due.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-slate-500">
            {review.data.last_run
              ? `Last applied ${formatTimestamp(review.data.last_run.applied_at)} (run #${review.data.last_run.run_number}).`
              : "Not applied yet."}
          </p>
        </>
      )}
    </Panel>
  );
}
