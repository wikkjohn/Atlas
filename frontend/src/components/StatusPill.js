import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
const TONES = {
    good: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
    warn: "bg-amber-50 text-amber-800 ring-amber-600/20",
    bad: "bg-rose-50 text-rose-700 ring-rose-600/20",
    neutral: "bg-slate-100 text-slate-600 ring-slate-500/20",
};
const DOTS = {
    good: "bg-emerald-500",
    warn: "bg-amber-500",
    bad: "bg-rose-500",
    neutral: "bg-slate-400",
};
export function StatusPill({ tone, label, compact = false }) {
    return (_jsxs("span", { className: `inline-flex shrink-0 items-center gap-1.5 rounded-full whitespace-nowrap px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[tone]}`, children: [_jsx("span", { "aria-hidden": true, className: `h-1.5 w-1.5 rounded-full ${DOTS[tone]}` }), compact ? _jsx("span", { className: "sr-only sm:not-sr-only", children: label }) : label] }));
}
