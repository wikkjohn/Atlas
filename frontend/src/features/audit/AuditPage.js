import { Fragment as _Fragment, jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Fragment, useState } from "react";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { formatTimestamp } from "@/features/dashboard/format";
import { useAuditEvents } from "@/services/enterprise";
const PAGE_SIZE = 50;
const ENTITY_TYPES = ["", "user", "country", "organization", "employee"];
export function AuditPage() {
    const [action, setAction] = useState("");
    const [entityType, setEntityType] = useState("");
    const [offset, setOffset] = useState(0);
    const [expanded, setExpanded] = useState(null);
    const events = useAuditEvents({
        action: action.trim() || undefined,
        entity_type: entityType || undefined,
        limit: PAGE_SIZE,
        offset,
    });
    return (_jsxs(_Fragment, { children: [_jsx(PageHeader, { title: "Audit Center", description: "Append-only record of security events and changes. Records cannot be edited or deleted \u2014 the database rejects it." }), _jsxs("div", { className: "mb-4 flex flex-wrap items-center gap-3", children: [_jsx("input", { "aria-label": "Action", placeholder: "Action, e.g. employee.* or auth.login_failed", className: "w-80 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm", value: action, onChange: (e) => {
                            setAction(e.target.value);
                            setOffset(0);
                        } }), _jsx("select", { "aria-label": "Entity type", className: "rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm", value: entityType, onChange: (e) => {
                            setEntityType(e.target.value);
                            setOffset(0);
                        }, children: ENTITY_TYPES.map((t) => (_jsx("option", { value: t, children: t ? t : "All entities" }, t))) })] }), _jsx(ErrorMessage, { error: events.error, className: "mb-4" }), _jsx("div", { className: "overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm", children: _jsxs("table", { className: "min-w-full text-sm", children: [_jsx("thead", { className: "bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase", children: _jsxs("tr", { children: [_jsx("th", { className: "px-4 py-2.5", children: "Time" }), _jsx("th", { className: "px-4 py-2.5", children: "Action" }), _jsx("th", { className: "px-4 py-2.5", children: "Actor" }), _jsx("th", { className: "px-4 py-2.5", children: "Entity" }), _jsx("th", { className: "px-4 py-2.5", children: "Correlation ID" })] }) }), _jsxs("tbody", { className: "divide-y divide-slate-100", children: [events.data?.items.length === 0 && (_jsx("tr", { children: _jsx("td", { colSpan: 5, className: "px-4 py-6 text-center text-slate-500", children: "No events match." }) })), events.data?.items.map((event) => (_jsxs(Fragment, { children: [_jsxs("tr", { className: "cursor-pointer hover:bg-slate-50", "aria-expanded": expanded === event.id, onClick: () => setExpanded(expanded === event.id ? null : event.id), children: [_jsx("td", { className: "px-4 py-2.5 whitespace-nowrap text-slate-600", children: formatTimestamp(event.timestamp) }), _jsx("td", { className: "px-4 py-2.5 font-mono text-xs text-slate-900", children: event.action }), _jsx("td", { className: "px-4 py-2.5 text-slate-700", children: event.actor_username ?? "system" }), _jsxs("td", { className: "px-4 py-2.5 text-slate-600", children: [event.entity_type, event.entity_id && (_jsx("span", { className: "ml-1 font-mono text-[11px] text-slate-400", children: event.entity_id.slice(0, 8) }))] }), _jsx("td", { className: "px-4 py-2.5 font-mono text-[11px] text-slate-500", children: event.correlation_id ?? "—" })] }), expanded === event.id && (_jsx("tr", { className: "bg-slate-50", children: _jsx("td", { colSpan: 5, className: "px-4 py-3", children: _jsx("pre", { "aria-label": "Event metadata", className: "overflow-x-auto rounded-lg bg-navy-950 p-3 font-mono text-xs text-slate-100", children: JSON.stringify(event.metadata, null, 2) }) }) }))] }, event.id)))] })] }) }), events.data && (_jsx("div", { className: "mt-3", children: _jsx(Pagination, { total: events.data.total, limit: PAGE_SIZE, offset: offset, onChange: setOffset }) }))] }));
}
