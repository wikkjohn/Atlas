import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Archive, ArchiveRestore } from "lucide-react";
import { useState } from "react";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { formatTimestamp } from "@/features/dashboard/format";
import { formatBytes } from "@/services/format";
import { useHistoryAction } from "@/services/simulations";
/**
 * Where the run's workflow history is, and archiving or restoring it. Results and
 * per-case outcomes stay whatever happens to the history.
 */
export function RunHistory({ run, waiting, onQueued, }) {
    const { can } = useAuth();
    const action = useHistoryAction();
    const [queued, setQueued] = useState(null);
    const finished = run.status === "completed" || run.status === "failed";
    const manage = can("simulations:manage") && finished;
    const pending = waiting && queued !== null;
    const start = (kind) => action.mutate({ id: run.id, action: kind }, {
        onSuccess: (job) => {
            setQueued(job);
            onQueued(job);
        },
    });
    return (_jsxs("section", { "aria-label": "Workflow history", className: "rounded-lg border border-slate-200 p-3 text-sm", children: [_jsxs("div", { className: "flex flex-wrap items-start justify-between gap-3", children: [_jsxs("div", { className: "max-w-xl", children: [_jsx("h3", { className: "font-medium text-slate-900", children: "Workflow history" }), run.history_state === "present" && (_jsx("p", { className: "mt-0.5 text-xs text-slate-600", children: "Every case's executions, steps, events and AI calls are in the database. Archiving moves them to compressed files and frees the space; results and case outcomes stay." })), run.history_state === "archived" && run.archive && (_jsxs("p", { className: "mt-0.5 text-xs text-slate-600", children: ["Archived ", formatTimestamp(run.archive.created_at), run.archive.created_by_username && ` by ${run.archive.created_by_username}`, ":", " ", run.archive.rows.toLocaleString(), " rows in ", formatBytes(run.archive.bytes), " of files. Results and case outcomes are unaffected; restore to inspect individual cases again."] })), run.history_state === "purged" && (_jsxs("p", { className: "mt-0.5 text-xs text-slate-600", children: ["Removed by a reset of simulation history", run.archive && ` on ${formatTimestamp(run.archive.created_at)}`, ". Results and case outcomes remain; the detailed history cannot be restored."] }))] }), manage && run.history_state === "present" && (_jsxs(Button, { size: "sm", variant: "secondary", disabled: action.isPending || pending, onClick: () => start("archive"), children: [_jsx(Archive, { "aria-hidden": true, className: "h-3.5 w-3.5" }), " Archive history"] })), manage && run.history_state === "archived" && (_jsxs(Button, { size: "sm", variant: "secondary", disabled: action.isPending || pending, onClick: () => start("restore"), children: [_jsx(ArchiveRestore, { "aria-hidden": true, className: "h-3.5 w-3.5" }), " Restore history"] }))] }), pending && queued && (_jsxs("p", { role: "status", className: "mt-2 text-xs text-slate-500", children: ["Queued as job #", queued.job_number, "; this page updates when it has finished."] })), _jsx(ErrorMessage, { error: action.error, className: "mt-2" })] }));
}
