import {
  Banknote,
  Bot,
  Clock,
  FlaskConical,
  Globe2,
  PlayCircle,
  RefreshCw,
  Users,
  Wallet,
  Workflow,
  XCircle,
  CheckCircle2,
  Activity,
} from "lucide-react";
import type { ComponentType } from "react";
import { Link } from "react-router-dom";

import { useAuth } from "@/app/auth";
import { BackendUnavailable } from "@/components/BackendUnavailable";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { SyntheticDataBadge } from "@/components/SyntheticDataBadge";
import { formatTimestamp } from "@/features/dashboard/format";
import { HealthTiles } from "@/features/dashboard/PlatformHealth";
import { useAnalyticsOverview } from "@/services/analytics";
import { BackendUnreachableError } from "@/services/api";
import { humanize } from "@/services/format";
import { useHealth, useSystemInfo, useSystemStatus } from "@/services/queries";
import type { DashboardMetric } from "@/types/analytics";
import type { Permission } from "@/types/enterprise";
import { MODE_LABELS, type ExperimentMode } from "@/types/simulations";

const TILE: Record<string, { icon: ComponentType<{ className?: string }>; to: string; permission?: Permission }> = {
  employees: { icon: Users, to: "/employees", permission: "employees:read" },
  countries: { icon: Globe2, to: "/countries", permission: "countries:read" },
  workflows: { icon: Workflow, to: "/workflows", permission: "workflows:read" },
  active_simulations: { icon: PlayCircle, to: "/simulations", permission: "simulations:read" },
  completed_executions: { icon: CheckCircle2, to: "/workflows?tab=executions", permission: "workflows:read" },
  failed_executions: { icon: XCircle, to: "/workflows?tab=executions", permission: "workflows:read" },
  accounts: { icon: Banknote, to: "/accounts", permission: "accounts:read" },
  ai_tools: { icon: Bot, to: "/ai-lab", permission: "ai_tools:read" },
  experiments: { icon: FlaskConical, to: "/experiments", permission: "experiments:read" },
  avg_process_duration: { icon: Clock, to: "/simulations", permission: "simulations:read" },
  simulation_cost: { icon: Wallet, to: "/benchmarking", permission: "experiments:read" },
};

function formatMetric(m: DashboardMetric, currency: string): string {
  if (m.value === null) return "—";
  if (m.unit === "hours") return `${m.value.toFixed(2)} h`;
  if (m.unit === "currency") return `${m.value.toLocaleString(undefined, { maximumFractionDigits: 0 })} ${currency}`;
  return m.value.toLocaleString();
}

function MetricTile({ metric, currency }: { metric: DashboardMetric; currency: string }) {
  const { can } = useAuth();
  const tile = TILE[metric.key];
  const Icon = tile?.icon ?? Activity;
  const body = (
    <>
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-xs font-medium text-slate-500">
          <Icon aria-hidden className="h-4 w-4 text-slate-400" />
          {metric.label}
        </span>
        {metric.estimate && (
          <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-amber-800 uppercase">
            Estimate
          </span>
        )}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight text-slate-900 tabular-nums">
        {formatMetric(metric, metric.unit === "currency" ? "" : currency)}
      </div>
      <div className="mt-1 text-[11px] leading-snug text-slate-500">{metric.detail}</div>
    </>
  );
  // The cost estimate is wider so eleven tiles close the last row of four.
  const span = metric.key === "simulation_cost" ? "xl:col-span-2" : "";
  const className = `block rounded-xl border border-slate-200 bg-white p-4 shadow-sm ${span}`;
  const linked = tile && (!tile.permission || can(tile.permission));
  return linked ? (
    <Link to={tile.to} aria-label={`${metric.label}: ${formatMetric(metric, "")}`} className={`${className} transition hover:border-slate-300 hover:shadow`}>
      {body}
    </Link>
  ) : (
    <div role="group" aria-label={metric.label} className={className}>
      {body}
    </div>
  );
}

const OUTCOME_TONE: Record<string, Tone> = { completed: "good", waiting: "warn", running: "warn", failed: "bad", cancelled: "neutral" };

export function OverviewPage() {
  const health = useHealth();
  const status = useSystemStatus();
  const info = useSystemInfo();
  const analytics = useAnalyticsOverview();

  const refreshAll = () => {
    void health.refetch();
    void status.refetch();
    void info.refetch();
    void analytics.refetch();
  };
  const refreshing = health.isFetching || status.isFetching || info.isFetching || analytics.isFetching;

  const header = (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Enterprise Overview</h1>
        <p className="mt-1 text-sm text-slate-500">
          ATLAS Global Bank at a glance — workforce, banking, workflows, simulations and AI experiments. Every figure is
          computed from the platform's synthetic records.
        </p>
      </div>
      <div className="flex items-center gap-3">
        <SyntheticDataBadge />
        {analytics.dataUpdatedAt > 0 && (
          <span className="text-xs text-slate-500">Updated {new Date(analytics.dataUpdatedAt).toLocaleTimeString()}</span>
        )}
        <button
          type="button"
          onClick={refreshAll}
          disabled={refreshing}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-60"
        >
          <RefreshCw aria-hidden className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>
    </div>
  );

  if (health.error instanceof BackendUnreachableError) {
    return (
      <>
        {header}
        <BackendUnavailable
          onRetry={refreshAll}
          retrying={refreshing}
          detail={health.error.cause instanceof Error ? health.error.cause.message : undefined}
        />
      </>
    );
  }

  const data = analytics.data;
  const currency = data?.cost_assumptions.currency_label ?? "";
  const outcomes = Object.entries(data?.workflow_outcomes ?? {});
  const totalLive = outcomes.reduce((sum, [, n]) => sum + n, 0);

  return (
    <>
      {header}
      {health.error && (
        <div role="alert" className="mb-6 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          Health check failed: {health.error.message}
        </div>
      )}
      <ErrorMessage error={analytics.error} className="mb-6" />

      <section aria-label="Key metrics" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {data
          ? data.metrics.map((m) => <MetricTile key={m.key} metric={m} currency={currency} />)
          : !analytics.error &&
            Array.from({ length: 8 }, (_, i) => (
              <div key={i} className="h-28 animate-pulse rounded-xl border border-slate-200 bg-white" />
            ))}
      </section>

      {data && (
        <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-3">
          <Panel title="Workflow operations" subtitle="Live WF-0001 cases (simulated cases are counted per run)">
            {totalLive === 0 ? (
              <p className="text-sm text-slate-500">No live workflow executions yet.</p>
            ) : (
              <ul aria-label="Live executions by status" className="space-y-2 text-sm">
                {outcomes
                  .sort(([a], [b]) => a.localeCompare(b))
                  .map(([state, n]) => (
                    <li key={state} className="flex items-center justify-between gap-3">
                      <StatusPill tone={OUTCOME_TONE[state] ?? "neutral"} label={humanize(state)} />
                      <span className="flex flex-1 items-center gap-2">
                        <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                          <span className="block h-full rounded-full bg-slate-400" style={{ width: `${(n / totalLive) * 100}%` }} />
                        </span>
                        <span className="w-10 text-right tabular-nums text-slate-700">{n}</span>
                      </span>
                    </li>
                  ))}
              </ul>
            )}
            <p className="mt-4 text-xs text-slate-600">
              <Link to="/workflows?tab=tasks" className="font-medium text-navy-700 hover:underline">
                {data.open_tasks} open task{data.open_tasks === 1 ? "" : "s"}
              </Link>{" "}
              waiting for an authorized person.
            </p>
          </Panel>

          <Panel title="Recent simulation runs">
            {data.recent_runs.length === 0 ? (
              <p className="text-sm text-slate-500">No simulation has been run yet.</p>
            ) : (
              <ul aria-label="Recent simulation runs" className="divide-y divide-slate-100 text-sm">
                {data.recent_runs.map((r) => (
                  <li key={r.id} className="flex items-center justify-between gap-2 py-2">
                    <Link to={`/simulations?run=${r.id}`} className="font-medium text-slate-900 hover:underline">
                      Run #{r.run_number}
                      <span className="ml-1 text-xs font-normal text-slate-500">
                        {MODE_LABELS[r.mode as ExperimentMode] ?? humanize(r.mode)} · {r.applications.toLocaleString()} apps
                      </span>
                    </Link>
                    <StatusPill tone={r.status === "completed" ? "good" : r.status === "failed" ? "bad" : "warn"} label={humanize(r.status)} compact />
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel title="Recent experiments">
            {data.recent_experiments.length === 0 ? (
              <p className="text-sm text-slate-500">No experiment has been run yet.</p>
            ) : (
              <ul aria-label="Recent experiments" className="divide-y divide-slate-100 text-sm">
                {data.recent_experiments.map((e) => (
                  <li key={e.id} className="flex items-center justify-between gap-2 py-2">
                    <Link to={`/experiments?experiment=${e.id}`} className="min-w-0 truncate font-medium text-slate-900 hover:underline">
                      #{e.experiment_number} {e.name}
                    </Link>
                    {e.verdict ? (
                      <StatusPill tone={e.verdict === "successful" ? "good" : "bad"} label={e.verdict === "successful" ? "Successful" : "Not successful"} compact />
                    ) : (
                      <StatusPill tone={e.status === "failed" ? "bad" : "warn"} label={humanize(e.status)} compact />
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      )}

      <section aria-label="Platform health" className="mt-6 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-900">Platform health</h2>
          <Link to="/settings" className="text-xs font-medium text-navy-700 hover:underline">
            System settings
          </Link>
        </div>
        <HealthTiles health={health} status={status} info={info} />
      </section>

      {data && (
        <p className="mt-6 text-xs text-slate-500">
          Figures as of {formatTimestamp(data.generated_at)}. The operating cost is an estimate from the default, stated
          assumptions ({currency}) applied to what the simulation runs recorded — not measured spending.
        </p>
      )}
    </>
  );
}
