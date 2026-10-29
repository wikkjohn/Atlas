import { Archive, ArchiveRestore } from "lucide-react";
import { useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { formatTimestamp } from "@/features/dashboard/format";
import { formatBytes } from "@/services/format";
import { useHistoryAction } from "@/services/simulations";
import type { QueuedJob, SimulationRunDetail } from "@/types/simulations";

/**
 * Where the run's workflow history is, and archiving or restoring it. Results and
 * per-case outcomes stay whatever happens to the history.
 */
export function RunHistory({
  run,
  waiting,
  onQueued,
}: {
  run: SimulationRunDetail;
  /** A queued archive or restore has not finished yet. */
  waiting: boolean;
  onQueued: (job: QueuedJob) => void;
}) {
  const { can } = useAuth();
  const action = useHistoryAction();
  const [queued, setQueued] = useState<QueuedJob | null>(null);
  const finished = run.status === "completed" || run.status === "failed";
  const manage = can("simulations:manage") && finished;
  const pending = waiting && queued !== null;

  const start = (kind: "archive" | "restore") =>
    action.mutate(
      { id: run.id, action: kind },
      {
        onSuccess: (job) => {
          setQueued(job);
          onQueued(job);
        },
      },
    );

  return (
    <section aria-label="Workflow history" className="rounded-lg border border-slate-200 p-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-xl">
          <h3 className="font-medium text-slate-900">Workflow history</h3>
          {run.history_state === "present" && (
            <p className="mt-0.5 text-xs text-slate-600">
              Every case's executions, steps, events and AI calls are in the database. Archiving moves them to
              compressed files and frees the space; results and case outcomes stay.
            </p>
          )}
          {run.history_state === "archived" && run.archive && (
            <p className="mt-0.5 text-xs text-slate-600">
              Archived {formatTimestamp(run.archive.created_at)}
              {run.archive.created_by_username && ` by ${run.archive.created_by_username}`}:{" "}
              {run.archive.rows.toLocaleString()} rows in {formatBytes(run.archive.bytes)} of files. Results and
              case outcomes are unaffected; restore to inspect individual cases again.
            </p>
          )}
          {run.history_state === "purged" && (
            <p className="mt-0.5 text-xs text-slate-600">
              Removed by a reset of simulation history{run.archive && ` on ${formatTimestamp(run.archive.created_at)}`}
              . Results and case outcomes remain; the detailed history cannot be restored.
            </p>
          )}
        </div>
        {manage && run.history_state === "present" && (
          <Button size="sm" variant="secondary" disabled={action.isPending || pending} onClick={() => start("archive")}>
            <Archive aria-hidden className="h-3.5 w-3.5" /> Archive history
          </Button>
        )}
        {manage && run.history_state === "archived" && (
          <Button size="sm" variant="secondary" disabled={action.isPending || pending} onClick={() => start("restore")}>
            <ArchiveRestore aria-hidden className="h-3.5 w-3.5" /> Restore history
          </Button>
        )}
      </div>
      {pending && queued && (
        <p role="status" className="mt-2 text-xs text-slate-500">
          Queued as job #{queued.job_number}; this page updates when it has finished.
        </p>
      )}
      <ErrorMessage error={action.error} className="mt-2" />
    </section>
  );
}
