import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Play } from "lucide-react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { formatTimestamp } from "@/features/dashboard/format";
import { useCountries } from "@/services/enterprise";
import { useJobSchedules, useJobs, useRunSchedule, useUpdateSchedule } from "@/services/jobs";
import { humanize } from "@/services/format";
const STATUS_TONE = {
    queued: "neutral",
    running: "warn",
    succeeded: "good",
    failed: "bad",
    cancelled: "neutral",
};
export function every(seconds) {
    if (seconds % 86_400 === 0)
        return seconds === 86_400 ? "daily" : `every ${seconds / 86_400} days`;
    if (seconds % 3_600 === 0)
        return seconds === 3_600 ? "hourly" : `every ${seconds / 3_600} h`;
    return seconds === 60 ? "every minute" : `every ${Math.round(seconds / 60)} min`;
}
function duration(job) {
    const ms = job.result?.duration_ms;
    return typeof ms === "number" ? (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`) : "—";
}
function JobStatusPill({ job }) {
    return _jsx(StatusPill, { compact: true, tone: STATUS_TONE[job.status], label: humanize(job.status) });
}
export function JobsPanel() {
    const { can } = useAuth();
    const manage = can("jobs:manage");
    const schedules = useJobSchedules();
    const jobs = useJobs({ limit: 15 });
    const update = useUpdateSchedule();
    const run = useRunSchedule();
    const countries = useCountries();
    return (_jsxs(Panel, { title: "Background jobs", subtitle: "Reconciliation, loan servicing, workflow timers, simulations and experiments run as durable jobs. Worker processes (python -m app.cli worker) claim them; without one, the API runs the jobs it queues itself. Schedules queue at most one job at a time. A schedule with a business calendar runs on that country's business days only, moving past weekends and public holidays.", children: [_jsx(ErrorMessage, { error: schedules.error ?? jobs.error ?? update.error ?? run.error }), _jsxs("table", { "aria-label": "Job schedules", className: "min-w-full text-sm", children: [_jsx("thead", { className: "text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-2 py-1", children: "Schedule" }), _jsx("th", { className: "px-2 py-1", children: "Runs" }), _jsx("th", { className: "px-2 py-1", children: "Business days" }), _jsx("th", { className: "px-2 py-1", children: "Next" }), _jsx("th", { className: "px-2 py-1", children: "Last job" }), _jsx("th", { className: "px-2 py-1" })] }) }), _jsx("tbody", { className: "divide-y divide-slate-100", children: schedules.data?.map((s) => (_jsxs("tr", { children: [_jsxs("td", { className: "px-2 py-1.5", children: [_jsx("div", { className: "font-medium text-slate-900", children: s.name }), _jsx("div", { className: "text-xs text-slate-500", children: s.description })] }), _jsx("td", { className: "px-2 py-1.5 text-slate-700", children: every(s.interval_seconds) }), _jsx("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: manage ? (_jsxs("select", { "aria-label": `Business calendar of ${s.name}`, className: "rounded-md border border-slate-200 px-1.5 py-0.5 text-xs", value: s.business_calendar ?? "", disabled: update.isPending, onChange: (e) => update.mutate({ name: s.name, business_calendar: e.target.value }), children: [_jsx("option", { value: "", children: "Every day" }), countries.data?.items.map((c) => (_jsx("option", { value: c.iso_country_code, children: c.country_name }, c.id)))] })) : ((s.business_calendar ?? "Every day")) }), _jsx("td", { className: "px-2 py-1.5 text-xs text-slate-600", children: s.enabled ? formatTimestamp(s.next_run_at) : "Off" }), _jsx("td", { className: "px-2 py-1.5", children: s.last_job ? _jsx(JobStatusPill, { job: s.last_job }) : _jsx("span", { className: "text-xs text-slate-400", children: "\u2014" }) }), _jsx("td", { className: "px-2 py-1.5", children: manage && (_jsxs("div", { className: "flex items-center justify-end gap-2", children: [_jsxs("label", { className: "flex items-center gap-1 text-xs text-slate-600", children: [_jsx("input", { type: "checkbox", "aria-label": `Enable ${s.name}`, checked: s.enabled, disabled: update.isPending, onChange: (e) => update.mutate({ name: s.name, enabled: e.target.checked }) }), "On"] }), _jsxs(Button, { size: "sm", variant: "secondary", "aria-label": `Run ${s.name} now`, disabled: run.isPending, onClick: () => run.mutate(s.name), children: [_jsx(Play, { "aria-hidden": true, className: "h-3 w-3" }), " Run now"] })] })) })] }, s.id))) })] }), _jsx("h3", { className: "mt-5 mb-1 text-xs font-medium tracking-wide text-slate-500 uppercase", children: "Recent jobs" }), _jsx("table", { "aria-label": "Recent jobs", className: "min-w-full text-sm", children: _jsxs("tbody", { className: "divide-y divide-slate-100", children: [jobs.data?.items.map((j) => (_jsxs("tr", { children: [_jsxs("td", { className: "px-2 py-1.5 font-mono text-xs", children: ["#", j.job_number] }), _jsxs("td", { className: "px-2 py-1.5", children: [_jsx("div", { className: "text-slate-900", children: j.kind }), _jsxs("div", { className: "text-[11px] text-slate-400", children: [j.schedule_name ?? j.created_by_username ?? "system", " \u00B7 ", formatTimestamp(j.created_at)] })] }), _jsxs("td", { className: "px-2 py-1.5", children: [_jsx(JobStatusPill, { job: j }), j.last_error && _jsx("div", { className: "mt-0.5 max-w-xs truncate text-[11px] text-rose-700", title: j.last_error, children: j.last_error })] }), _jsxs("td", { className: "px-2 py-1.5 text-xs text-slate-600 tabular-nums", children: [j.attempts, "/", j.max_attempts, " attempts"] }), _jsx("td", { className: "px-2 py-1.5 text-right text-xs text-slate-600 tabular-nums", children: duration(j) })] }, j.id))), jobs.data?.items.length === 0 && (_jsx("tr", { children: _jsx("td", { className: "px-2 py-3 text-center text-xs text-slate-500", children: "No jobs yet." }) }))] }) })] }));
}
