import { FlaskConical } from "lucide-react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { StatusPill } from "@/components/StatusPill";
import { formatTimestamp } from "@/features/dashboard/format";
import { useRunTests, useTestRuns } from "@/services/workflows";
import type { TestRun } from "@/types/workflows";

const percent = (share: number) => `${Math.round(share * 100)} %`;

function RunDetails({ run }: { run: TestRun }) {
  const problems = run.cases.filter((c) => c.status !== "passed");
  return (
    <div className="space-y-2">
      <p role="status" className="text-sm text-slate-700">
        {run.passed} passed, {run.failed} failed{run.skipped ? `, ${run.skipped} skipped` : ""} · steps{" "}
        {percent(run.step_coverage)} · routes {percent(run.route_coverage)} · {formatTimestamp(run.ran_at)}
        {run.ran_by_username ? ` by ${run.ran_by_username}` : ""}
      </p>
      {problems.length > 0 && (
        <ul aria-label="Failing cases" className="space-y-1 text-xs text-rose-800">
          {problems.map((c) => (
            <li key={c.name}>
              <span className="font-medium">{c.status}:</span> {c.name} — {c.detail}
            </li>
          ))}
        </ul>
      )}
      {run.uncovered.length > 0 && (
        <ul aria-label="Uncovered routes" className="space-y-1 text-xs text-amber-800">
          {run.uncovered.map((u) => (
            <li key={u.route}>
              Not covered: <span className="font-mono">{u.route}</span> — {u.reason}
            </li>
          ))}
        </ul>
      )}
      <details className="text-xs text-slate-600">
        <summary className="cursor-pointer font-medium text-slate-700">All {run.cases.length} cases</summary>
        <table aria-label="Test cases" className="mt-2 min-w-full">
          <tbody className="divide-y divide-slate-100">
            {run.cases.map((c) => (
              <tr key={c.name}>
                <td className="py-1 pr-2">
                  <StatusPill tone={c.status === "passed" ? "good" : c.status === "failed" ? "bad" : "warn"} label={c.status} />
                </td>
                <td className="py-1 pr-2">{c.name}</td>
                <td className="py-1 pr-2 font-mono">{c.outcome ?? "—"}</td>
                <td className="py-1 text-slate-500">{c.detail || c.mocked.join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}

/** Path tests generated from a stored definition: run them, see the latest result. */
export function TestsPanel({ workflowId, version }: { workflowId: string; version: number }) {
  const { can } = useAuth();
  const runs = useTestRuns(workflowId);
  const run = useRunTests();
  const latest = run.data?.version === version ? run.data : runs.data?.find((r) => r.version === version);
  return (
    <section aria-label="Generated tests" className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Generated tests</h3>
          <p className="text-xs text-slate-500">
            Happy, every route, approval refusals and no-route probes, run through the engine and rolled back.
          </p>
        </div>
        {can("workflows:define") && (
          <Button size="sm" variant="secondary" disabled={run.isPending} onClick={() => run.mutate({ workflowId, version })}>
            <FlaskConical aria-hidden className="h-3.5 w-3.5" /> {run.isPending ? "Running…" : `Run tests on v${version}`}
          </Button>
        )}
      </div>
      <ErrorMessage error={run.error ?? runs.error} />
      {latest ? <RunDetails run={latest} /> : <p className="text-sm text-slate-500">Not tested yet.</p>}
    </section>
  );
}
