import { Database, GitBranch, RefreshCw, Server, Zap } from "lucide-react";
import type { ReactNode } from "react";

import { BackendUnavailable } from "@/components/BackendUnavailable";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { formatDuration, formatTimestamp } from "@/features/dashboard/format";
import { BackendUnreachableError } from "@/services/api";
import { useHealth, useSystemInfo, useSystemStatus } from "@/services/queries";
import type { ComponentStatus, PlatformModule } from "@/types/system";

function componentTone(status: ComponentStatus | undefined): Tone {
  if (status === "ok") return "good";
  if (status === "disabled") return "neutral";
  return "bad";
}

function componentLabel(status: ComponentStatus | undefined): string {
  if (status === "ok") return "Connected";
  if (status === "disabled") return "Not configured";
  return "Unavailable";
}

interface HealthTileProps {
  title: string;
  icon: ReactNode;
  tone: Tone;
  label: string;
  detail: ReactNode;
}

function HealthTile({ title, icon, tone, label, detail }: HealthTileProps) {
  return (
    <div
      aria-label={title}
      role="group"
      className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-600">
          {icon}
          {title}
        </div>
        <StatusPill tone={tone} label={label} />
      </div>
      <div className="mt-3 min-h-5 text-xs text-slate-500">{detail}</div>
    </div>
  );
}

function DefinitionList({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
      {rows.map(([term, value]) => (
        <div key={term}>
          <dt className="text-xs font-medium tracking-wide text-slate-500 uppercase">{term}</dt>
          <dd className="mt-0.5 break-words text-slate-900">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function ModuleRoadmap({ modules }: { modules: PlatformModule[] }) {
  const sorted = [...modules].sort((a, b) => a.phase - b.phase);
  return (
    <div className="-mx-5 -my-5 overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
          <tr>
            <th className="px-5 py-2.5">Module</th>
            <th className="px-5 py-2.5">Phase</th>
            <th className="px-5 py-2.5">Status</th>
            <th className="px-5 py-2.5">Scope</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {sorted.map((module) => (
            <tr key={module.key}>
              <td className="px-5 py-2.5 font-medium whitespace-nowrap text-slate-900">
                {module.name}
              </td>
              <td className="px-5 py-2.5 text-slate-600">{module.phase}</td>
              <td className="px-5 py-2.5">
                <StatusPill
                  tone={module.status === "available" ? "good" : "neutral"}
                  label={module.status === "available" ? "Available" : "Planned"}
                />
              </td>
              <td className="px-5 py-2.5 text-slate-600">{module.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function OverviewPage() {
  const health = useHealth();
  const status = useSystemStatus();
  const info = useSystemInfo();

  const refreshAll = () => {
    void health.refetch();
    void status.refetch();
    void info.refetch();
  };
  const refreshing = health.isFetching || status.isFetching || info.isFetching;

  const header = (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Platform Overview</h1>
        <p className="mt-1 text-sm text-slate-500">
          Live health of the ATLAS Global Bank simulation platform. All business data on this
          platform is synthetic.
        </p>
      </div>
      <div className="flex items-center gap-3">
        {health.dataUpdatedAt > 0 && (
          <span className="text-xs text-slate-500">
            Checked {new Date(health.dataUpdatedAt).toLocaleTimeString()}
          </span>
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

  const components = health.data?.components;
  const migrations = status.data?.database.migrations;
  const database = status.data?.database;
  const loading = "Loading…";

  return (
    <>
      {header}

      {health.error && (
        <div role="alert" className="mb-6 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          Health check failed: {health.error.message}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <HealthTile
          title="API service"
          icon={<Server aria-hidden className="h-4 w-4" />}
          tone={components ? componentTone(components.application?.status) : "neutral"}
          label={components ? "Online" : "Checking"}
          detail={info.data ? `FastAPI · v${info.data.version}` : loading}
        />
        <HealthTile
          title="Database"
          icon={<Database aria-hidden className="h-4 w-4" />}
          tone={components ? componentTone(components.database?.status) : "neutral"}
          label={components ? componentLabel(components.database?.status) : "Checking"}
          detail={
            components?.database?.status === "ok"
              ? `PostgreSQL · ${components.database.latency_ms} ms round trip`
              : (components?.database?.error ?? loading)
          }
        />
        <HealthTile
          title="Schema migrations"
          icon={<GitBranch aria-hidden className="h-4 w-4" />}
          tone={migrations ? (migrations.up_to_date ? "good" : "warn") : database ? "bad" : "neutral"}
          label={
            migrations
              ? migrations.up_to_date
                ? "Up to date"
                : "Pending"
              : database
                ? "Unknown"
                : "Checking"
          }
          detail={
            migrations
              ? `Current ${migrations.current_revisions.join(", ") || "none"} · head ${migrations.head_revisions.join(", ")}`
              : database && !database.connected
                ? "Database unreachable"
                : loading
          }
        />
        <HealthTile
          title="Redis cache"
          icon={<Zap aria-hidden className="h-4 w-4" />}
          tone={components ? componentTone(components.redis?.status) : "neutral"}
          label={components ? componentLabel(components.redis?.status) : "Checking"}
          detail={
            components?.redis?.error ??
            (components?.redis?.status === "disabled"
              ? "Optional in Phase 1 (ATLAS_REDIS_URL unset)"
              : components
                ? "Optional cache and lightweight queue"
                : loading)
          }
        />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Panel title="Platform" subtitle="From GET /api/system/info">
          {info.data ? (
            <DefinitionList
              rows={[
                ["Name", info.data.name],
                ["Version", info.data.version],
                ["Environment", <span className="capitalize">{info.data.environment}</span>],
                ["API versions", info.data.api_versions.join(", ")],
                ["Build", info.data.build_sha ?? "Not supplied"],
                ["Runtime", `Python ${info.data.python_version}`],
                ["Started", formatTimestamp(info.data.started_at)],
                ["Uptime", formatDuration(status.data?.uptime_seconds ?? info.data.uptime_seconds)],
              ]}
            />
          ) : (
            <p className="text-sm text-slate-500">{info.error ? info.error.message : loading}</p>
          )}
        </Panel>

        <Panel title="Database" subtitle="From GET /api/system/status">
          {database ? (
            <DefinitionList
              rows={[
                ["Connection", database.connected ? "Connected" : `Unavailable — ${database.error}`],
                ["Database", database.database_name ?? "—"],
                ["Server", database.server_version ? `PostgreSQL ${database.server_version}` : "—"],
                ["Tables", database.table_count ?? "—"],
                ["Schema initialised", formatTimestamp(database.initialized_at)],
                ["Overall status", status.data?.status.replace("_", " ") ?? "—"],
              ]}
            />
          ) : (
            <p className="text-sm text-slate-500">
              {status.error ? status.error.message : loading}
            </p>
          )}
        </Panel>
      </div>

      <Panel
        className="mt-6"
        title="Module roadmap"
        subtitle="Modules registered in the backend and the phase that delivers each one"
      >
        {info.data ? (
          <ModuleRoadmap modules={info.data.modules} />
        ) : (
          <p className="text-sm text-slate-500">{info.error ? info.error.message : loading}</p>
        )}
      </Panel>

      {info.data && (
        <p className="mt-6 text-xs text-slate-500">
          <span className="font-semibold">Data policy:</span> {info.data.data_policy}
        </p>
      )}
    </>
  );
}
