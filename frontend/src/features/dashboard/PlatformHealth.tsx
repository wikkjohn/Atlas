import { Database, GitBranch, Server, Zap } from "lucide-react";
import type { ReactNode } from "react";

import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { formatDuration, formatTimestamp } from "@/features/dashboard/format";
import type { useHealth, useSystemInfo, useSystemStatus } from "@/services/queries";
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

export function HealthTile({ title, icon, tone, label, detail }: HealthTileProps) {
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


interface PlatformQueries {
  health: ReturnType<typeof useHealth>;
  status: ReturnType<typeof useSystemStatus>;
  info: ReturnType<typeof useSystemInfo>;
}

const loading = "Loading…";

/** API, database, migrations and Redis at a glance (from the public health endpoints). */
export function HealthTiles({ health, status, info }: PlatformQueries) {
  const components = health.data?.components;
  const migrations = status.data?.database.migrations;
  const database = status.data?.database;
  return (
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
            ? "Optional cache (ATLAS_REDIS_URL unset)"
            : components
              ? "Optional cache and lightweight queue"
              : loading)
        }
      />
    </div>

  );
}

/** Platform build, database details, module registry and the data policy. */
export function PlatformDetails({ status, info }: Omit<PlatformQueries, "health">) {
  const database = status.data?.database;
  return (
    <>
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
