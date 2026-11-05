import { ChevronRight } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";

import { ErrorMessage } from "@/components/ErrorMessage";
import { inputClass } from "@/components/Field";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { SyntheticDataBadge } from "@/components/SyntheticDataBadge";
import { formatMilliseconds, formatTimestamp } from "@/features/dashboard/format";
import { useDrilldown } from "@/services/analytics";
import { humanize } from "@/services/format";
import type { DrilldownFigures, DrilldownQuery } from "@/types/analytics";

const BREAKDOWN_LABEL = { country: "Country", department: "Department", workflow: "Workflow" } as const;
const PERIODS = [
  { value: "", label: "All time" },
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "365", label: "Last year" },
];

function percent(rate: number | null): string {
  return rate === null ? "—" : `${(rate * 100).toFixed(1)}%`;
}

function seconds(value: number | null): string {
  return value === null ? "—" : formatMilliseconds(value * 1000);
}

/** The query for the place one level down from `query`, through `key`. */
function childParams(params: URLSearchParams, by: "country" | "department" | "workflow", key: string) {
  const next = new URLSearchParams(params);
  next.set(by === "workflow" ? "workflow" : by, key);
  return `?${next.toString()}`;
}

function Figures({ figures }: { figures: DrilldownFigures }) {
  const items: [string, string][] = [
    ["Executions", figures.executions.toLocaleString()],
    ["Completed", figures.completed.toLocaleString()],
    ["Failed", figures.failed.toLocaleString()],
    ["Failure rate", percent(figures.failure_rate)],
    ["In progress", figures.active.toLocaleString()],
    ["Open tasks", figures.open_tasks.toLocaleString()],
    ["Average duration", seconds(figures.avg_duration_s)],
    ["Last started", formatTimestamp(figures.last_started_at)],
  ];
  return (
    <dl aria-label="Summary" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {items.map(([label, value]) => (
        <div key={label} className="rounded-md border border-slate-200 bg-white px-3 py-2">
          <dt className="text-xs text-slate-500">{label}</dt>
          <dd className="text-lg font-semibold tabular-nums text-slate-800">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Phase 88: workflow executions from the whole bank down to one workflow. */
export function DrilldownPage() {
  const [params, setParams] = useSearchParams();
  const query: DrilldownQuery = {
    country: params.get("country") ?? undefined,
    department: params.get("department") ?? undefined,
    workflow_id: params.get("workflow") ?? undefined,
    realm: (params.get("realm") as DrilldownQuery["realm"]) ?? "all",
    days: params.get("days") ? Number(params.get("days")) : undefined,
  };
  if (!["all", "live", "simulation"].includes(query.realm)) query.realm = "all";
  const drill = useDrilldown(query);
  const data = drill.data;

  const setFilter = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next);
  };

  // A breadcrumb keeps the path up to its level and the filters.
  const crumbHref = (index: number) => {
    const next = new URLSearchParams();
    for (const name of ["realm", "days"]) {
      const value = params.get(name);
      if (value) next.set(name, value);
    }
    const keys = ["country", "department", "workflow"];
    data?.path.slice(1, index + 1).forEach((crumb, i) => next.set(keys[i], crumb.key));
    const text = next.toString();
    return text ? `?${text}` : "?";
  };

  return (
    <>
      <PageHeader
        title="Drill-down"
        description="Workflow executions across the bank, then by country, department and workflow. Country comes from the execution's input or the workflow's single catalogue country; department from the catalogue."
        actions={<SyntheticDataBadge />}
      />
      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-2">
          <span className="text-xs text-slate-600">History</span>
          <select aria-label="History" className={inputClass} value={query.realm} onChange={(e) => setFilter("realm", e.target.value === "all" ? "" : e.target.value)}>
            <option value="all">Live and simulated</option>
            <option value="live">Live bank</option>
            <option value="simulation">Simulations</option>
          </select>
        </label>
        <label className="flex items-center gap-2">
          <span className="text-xs text-slate-600">Period</span>
          <select aria-label="Period" className={inputClass} value={params.get("days") ?? ""} onChange={(e) => setFilter("days", e.target.value)}>
            {PERIODS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <ErrorMessage error={drill.error} />
      {data && (
        <>
          <nav aria-label="Drill-down path" className="mb-3 flex flex-wrap items-center gap-1 text-sm">
            {data.path.map((crumb, i) => (
              <span key={`${crumb.level}-${crumb.key}`} className="flex items-center gap-1">
                {i > 0 && <ChevronRight aria-hidden className="h-3.5 w-3.5 text-slate-400" />}
                {i < data.path.length - 1 ? (
                  <Link className="text-sky-700 hover:underline" to={crumbHref(i)}>
                    {crumb.label}
                  </Link>
                ) : (
                  <span aria-current="page" className="font-medium text-slate-800">
                    {crumb.label}
                  </span>
                )}
              </span>
            ))}
          </nav>
          {data.scope && (
            <p role="note" className="mb-3 text-xs text-amber-800">
              Limited to your scope
              {data.scope.countries ? `: countries ${data.scope.countries.join(", ")}` : ""}
              {data.scope.departments ? `; departments ${data.scope.departments.join(", ")}` : ""}. Executions outside it, or without a country or department, are not counted.
            </p>
          )}
          <Panel title={data.path[data.path.length - 1].label} subtitle={`${humanize(data.level)} level`} className="mb-4">
            <Figures figures={data.summary} />
          </Panel>
          {data.breakdown_by && (
            <Panel title={`By ${BREAKDOWN_LABEL[data.breakdown_by].toLowerCase()}`} subtitle={data.truncated ? "The 500 largest groups" : `${data.breakdown.length} group(s)`}>
              {data.breakdown.length === 0 ? (
                <p className="text-sm text-slate-500">No executions here.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table aria-label={`Executions by ${data.breakdown_by}`} className="min-w-full text-sm">
                    <thead className="text-left text-xs text-slate-500">
                      <tr>
                        <th className="py-1 pr-3 font-medium">{BREAKDOWN_LABEL[data.breakdown_by]}</th>
                        <th className="py-1 pr-3 text-right font-medium">Executions</th>
                        <th className="py-1 pr-3 text-right font-medium">Failure rate</th>
                        <th className="py-1 pr-3 text-right font-medium">In progress</th>
                        <th className="py-1 pr-3 text-right font-medium">Open tasks</th>
                        <th className="py-1 pr-3 text-right font-medium">Avg duration</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.breakdown.map((row) => (
                        <tr key={row.key} className="border-t border-slate-100">
                          <td className="py-1 pr-3">
                            <Link className="text-sky-700 hover:underline" to={childParams(params, data.breakdown_by!, row.key)}>
                              {row.label}
                            </Link>
                            {data.breakdown_by === "workflow" && <span className="ml-2 font-mono text-xs text-slate-400">{row.key}</span>}
                          </td>
                          <td className="py-1 pr-3 text-right tabular-nums">{row.executions.toLocaleString()}</td>
                          <td className="py-1 pr-3 text-right tabular-nums">{percent(row.failure_rate)}</td>
                          <td className="py-1 pr-3 text-right tabular-nums">{row.active.toLocaleString()}</td>
                          <td className="py-1 pr-3 text-right tabular-nums">{row.open_tasks.toLocaleString()}</td>
                          <td className="py-1 pr-3 text-right tabular-nums">{seconds(row.avg_duration_s)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>
          )}
          {data.steps && (
            <div className="grid gap-4 lg:grid-cols-3">
              <Panel title="By step" subtitle="Runs, failures, waiting work and time taken" className="lg:col-span-2">
                <div className="overflow-x-auto">
                  <table aria-label="Steps" className="min-w-full text-sm">
                    <thead className="text-left text-xs text-slate-500">
                      <tr>
                        <th className="py-1 pr-3 font-medium">Step</th>
                        <th className="py-1 pr-3 font-medium">Type</th>
                        <th className="py-1 pr-3 text-right font-medium">Runs</th>
                        <th className="py-1 pr-3 text-right font-medium">Failed</th>
                        <th className="py-1 pr-3 text-right font-medium">Waiting</th>
                        <th className="py-1 pr-3 text-right font-medium">Average</th>
                        <th className="py-1 pr-3 text-right font-medium">95th percentile</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.steps.map((s) => (
                        <tr key={s.step_id} className="border-t border-slate-100">
                          <td className="py-1 pr-3 font-mono text-xs">{s.step_id}</td>
                          <td className="py-1 pr-3">{humanize(s.step_type)}</td>
                          <td className="py-1 pr-3 text-right tabular-nums">{s.runs.toLocaleString()}</td>
                          <td className="py-1 pr-3 text-right tabular-nums">{s.failed.toLocaleString()}</td>
                          <td className="py-1 pr-3 text-right tabular-nums">{s.waiting.toLocaleString()}</td>
                          <td className="py-1 pr-3 text-right tabular-nums">{formatMilliseconds(s.avg_ms)}</td>
                          <td className="py-1 pr-3 text-right tabular-nums">{formatMilliseconds(s.p95_ms)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>
              <Panel title="Outcomes">
                <ul aria-label="Outcomes" className="space-y-1 text-sm">
                  {Object.entries(data.outcomes ?? {}).map(([outcome, count]) => (
                    <li key={outcome} className="flex justify-between gap-3">
                      <span>{outcome === "none" ? "No outcome yet" : humanize(outcome)}</span>
                      <span className="tabular-nums">{count.toLocaleString()}</span>
                    </li>
                  ))}
                </ul>
              </Panel>
            </div>
          )}
        </>
      )}
    </>
  );
}
