import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Database, GitBranch, Server, Zap } from "lucide-react";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { formatDuration, formatTimestamp } from "@/features/dashboard/format";
function componentTone(status) {
    if (status === "ok")
        return "good";
    if (status === "disabled")
        return "neutral";
    return "bad";
}
function componentLabel(status) {
    if (status === "ok")
        return "Connected";
    if (status === "disabled")
        return "Not configured";
    return "Unavailable";
}
export function HealthTile({ title, icon, tone, label, detail }) {
    return (_jsxs("div", { "aria-label": title, role: "group", className: "rounded-xl border border-slate-200 bg-white p-4 shadow-sm", children: [_jsxs("div", { className: "flex items-center justify-between", children: [_jsxs("div", { className: "flex items-center gap-2 text-sm font-medium text-slate-600", children: [icon, title] }), _jsx(StatusPill, { tone: tone, label: label })] }), _jsx("div", { className: "mt-3 min-h-5 text-xs text-slate-500", children: detail })] }));
}
function DefinitionList({ rows }) {
    return (_jsx("dl", { className: "grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2", children: rows.map(([term, value]) => (_jsxs("div", { children: [_jsx("dt", { className: "text-xs font-medium tracking-wide text-slate-500 uppercase", children: term }), _jsx("dd", { className: "mt-0.5 break-words text-slate-900", children: value })] }, term))) }));
}
function ModuleRoadmap({ modules }) {
    const sorted = [...modules].sort((a, b) => a.phase - b.phase);
    return (_jsx("div", { className: "-mx-5 -my-5 overflow-x-auto", children: _jsxs("table", { className: "min-w-full text-sm", children: [_jsx("thead", { className: "bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-5 py-2.5", children: "Module" }), _jsx("th", { className: "px-5 py-2.5", children: "Phase" }), _jsx("th", { className: "px-5 py-2.5", children: "Status" }), _jsx("th", { className: "px-5 py-2.5", children: "Scope" })] }) }), _jsx("tbody", { className: "divide-y divide-slate-100", children: sorted.map((module) => (_jsxs("tr", { children: [_jsx("td", { className: "px-5 py-2.5 font-medium whitespace-nowrap text-slate-900", children: module.name }), _jsx("td", { className: "px-5 py-2.5 text-slate-600", children: module.phase }), _jsx("td", { className: "px-5 py-2.5", children: _jsx(StatusPill, { tone: module.status === "available" ? "good" : "neutral", label: module.status === "available" ? "Available" : "Planned" }) }), _jsx("td", { className: "px-5 py-2.5 text-slate-600", children: module.description })] }, module.key))) })] }) }));
}
const loading = "Loading…";
/** API, database, migrations and Redis at a glance (from the public health endpoints). */
export function HealthTiles({ health, status, info }) {
    const components = health.data?.components;
    const migrations = status.data?.database.migrations;
    const database = status.data?.database;
    return (_jsxs("div", { className: "grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4", children: [_jsx(HealthTile, { title: "API service", icon: _jsx(Server, { "aria-hidden": true, className: "h-4 w-4" }), tone: components ? componentTone(components.application?.status) : "neutral", label: components ? "Online" : "Checking", detail: info.data ? `FastAPI · v${info.data.version}` : loading }), _jsx(HealthTile, { title: "Database", icon: _jsx(Database, { "aria-hidden": true, className: "h-4 w-4" }), tone: components ? componentTone(components.database?.status) : "neutral", label: components ? componentLabel(components.database?.status) : "Checking", detail: components?.database?.status === "ok"
                    ? `PostgreSQL · ${components.database.latency_ms} ms round trip`
                    : (components?.database?.error ?? loading) }), _jsx(HealthTile, { title: "Schema migrations", icon: _jsx(GitBranch, { "aria-hidden": true, className: "h-4 w-4" }), tone: migrations ? (migrations.up_to_date ? "good" : "warn") : database ? "bad" : "neutral", label: migrations
                    ? migrations.up_to_date
                        ? "Up to date"
                        : "Pending"
                    : database
                        ? "Unknown"
                        : "Checking", detail: migrations
                    ? `Current ${migrations.current_revisions.join(", ") || "none"} · head ${migrations.head_revisions.join(", ")}`
                    : database && !database.connected
                        ? "Database unreachable"
                        : loading }), _jsx(HealthTile, { title: "Redis cache", icon: _jsx(Zap, { "aria-hidden": true, className: "h-4 w-4" }), tone: components ? componentTone(components.redis?.status) : "neutral", label: components ? componentLabel(components.redis?.status) : "Checking", detail: components?.redis?.error ??
                    (components?.redis?.status === "disabled"
                        ? "Optional cache (ATLAS_REDIS_URL unset)"
                        : components
                            ? "Optional cache and lightweight queue"
                            : loading) })] }));
}
/** Platform build, database details, module registry and the data policy. */
export function PlatformDetails({ status, info }) {
    const database = status.data?.database;
    return (_jsxs(_Fragment, { children: [_jsxs("div", { className: "mt-6 grid grid-cols-1 gap-6 xl:grid-cols-2", children: [_jsx(Panel, { title: "Platform", subtitle: "From GET /api/system/info", children: info.data ? (_jsx(DefinitionList, { rows: [
                                ["Name", info.data.name],
                                ["Version", info.data.version],
                                ["Environment", _jsx("span", { className: "capitalize", children: info.data.environment })],
                                ["API versions", info.data.api_versions.join(", ")],
                                ["Build", info.data.build_sha ?? "Not supplied"],
                                ["Runtime", `Python ${info.data.python_version}`],
                                ["Started", formatTimestamp(info.data.started_at)],
                                ["Uptime", formatDuration(status.data?.uptime_seconds ?? info.data.uptime_seconds)],
                            ] })) : (_jsx("p", { className: "text-sm text-slate-500", children: info.error ? info.error.message : loading })) }), _jsx(Panel, { title: "Database", subtitle: "From GET /api/system/status", children: database ? (_jsx(DefinitionList, { rows: [
                                ["Connection", database.connected ? "Connected" : `Unavailable — ${database.error}`],
                                ["Database", database.database_name ?? "—"],
                                ["Server", database.server_version ? `PostgreSQL ${database.server_version}` : "—"],
                                ["Tables", database.table_count ?? "—"],
                                ["Schema initialised", formatTimestamp(database.initialized_at)],
                                ["Overall status", status.data?.status.replace("_", " ") ?? "—"],
                            ] })) : (_jsx("p", { className: "text-sm text-slate-500", children: status.error ? status.error.message : loading })) })] }), _jsx(Panel, { className: "mt-6", title: "Module roadmap", subtitle: "Modules registered in the backend and the phase that delivers each one", children: info.data ? (_jsx(ModuleRoadmap, { modules: info.data.modules })) : (_jsx("p", { className: "text-sm text-slate-500", children: info.error ? info.error.message : loading })) }), info.data && (_jsxs("p", { className: "mt-6 text-xs text-slate-500", children: [_jsx("span", { className: "font-semibold", children: "Data policy:" }), " ", info.data.data_policy] }))] }));
}
