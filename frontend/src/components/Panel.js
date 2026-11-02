import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
export function Panel({ title, subtitle, actions, children, className = "" }) {
    return (_jsxs("section", { "aria-label": title, className: `rounded-xl border border-slate-200 bg-white shadow-sm ${className}`, children: [_jsxs("header", { className: "flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-3.5", children: [_jsxs("div", { children: [_jsx("h2", { className: "text-sm font-semibold text-slate-900", children: title }), subtitle && _jsx("p", { className: "mt-0.5 text-xs text-slate-500", children: subtitle })] }), actions] }), _jsx("div", { className: "p-5", children: children })] }));
}
