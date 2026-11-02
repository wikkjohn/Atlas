import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { FlaskConical } from "lucide-react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { StatusPill } from "@/components/StatusPill";
import { formatTimestamp } from "@/features/dashboard/format";
import { useRunTests, useTestRuns } from "@/services/workflows";
const percent = (share) => `${Math.round(share * 100)} %`;
function RunDetails({ run }) {
    const problems = run.cases.filter((c) => c.status !== "passed");
    return (_jsxs("div", { className: "space-y-2", children: [_jsxs("p", { role: "status", className: "text-sm text-slate-700", children: [run.passed, " passed, ", run.failed, " failed", run.skipped ? `, ${run.skipped} skipped` : "", " \u00B7 steps", " ", percent(run.step_coverage), " \u00B7 routes ", percent(run.route_coverage), " \u00B7 ", formatTimestamp(run.ran_at), run.ran_by_username ? ` by ${run.ran_by_username}` : ""] }), problems.length > 0 && (_jsx("ul", { "aria-label": "Failing cases", className: "space-y-1 text-xs text-rose-800", children: problems.map((c) => (_jsxs("li", { children: [_jsxs("span", { className: "font-medium", children: [c.status, ":"] }), " ", c.name, " \u2014 ", c.detail] }, c.name))) })), run.uncovered.length > 0 && (_jsx("ul", { "aria-label": "Uncovered routes", className: "space-y-1 text-xs text-amber-800", children: run.uncovered.map((u) => (_jsxs("li", { children: ["Not covered: ", _jsx("span", { className: "font-mono", children: u.route }), " \u2014 ", u.reason] }, u.route))) })), _jsxs("details", { className: "text-xs text-slate-600", children: [_jsxs("summary", { className: "cursor-pointer font-medium text-slate-700", children: ["All ", run.cases.length, " cases"] }), _jsx("table", { "aria-label": "Test cases", className: "mt-2 min-w-full", children: _jsx("tbody", { className: "divide-y divide-slate-100", children: run.cases.map((c) => (_jsxs("tr", { children: [_jsx("td", { className: "py-1 pr-2", children: _jsx(StatusPill, { tone: c.status === "passed" ? "good" : c.status === "failed" ? "bad" : "warn", label: c.status }) }), _jsx("td", { className: "py-1 pr-2", children: c.name }), _jsx("td", { className: "py-1 pr-2 font-mono", children: c.outcome ?? "—" }), _jsx("td", { className: "py-1 text-slate-500", children: c.detail || c.mocked.join(", ") })] }, c.name))) }) })] })] }));
}
/** Path tests generated from a stored definition: run them, see the latest result. */
export function TestsPanel({ workflowId, version }) {
    const { can } = useAuth();
    const runs = useTestRuns(workflowId);
    const run = useRunTests();
    const latest = run.data?.version === version ? run.data : runs.data?.find((r) => r.version === version);
    return (_jsxs("section", { "aria-label": "Generated tests", className: "space-y-3 rounded-xl border border-slate-200 bg-white p-4", children: [_jsxs("div", { className: "flex flex-wrap items-center justify-between gap-2", children: [_jsxs("div", { children: [_jsx("h3", { className: "text-sm font-semibold text-slate-900", children: "Generated tests" }), _jsx("p", { className: "text-xs text-slate-500", children: "Happy, every route, approval refusals and no-route probes, run through the engine and rolled back." })] }), can("workflows:define") && (_jsxs(Button, { size: "sm", variant: "secondary", disabled: run.isPending, onClick: () => run.mutate({ workflowId, version }), children: [_jsx(FlaskConical, { "aria-hidden": true, className: "h-3.5 w-3.5" }), " ", run.isPending ? "Running…" : `Run tests on v${version}`] }))] }), _jsx(ErrorMessage, { error: run.error ?? runs.error }), latest ? _jsx(RunDetails, { run: latest }) : _jsx("p", { className: "text-sm text-slate-500", children: "Not tested yet." })] }));
}
