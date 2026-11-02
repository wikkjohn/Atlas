import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Link } from "react-router-dom";
export function NotFoundPage() {
    return (_jsxs("div", { className: "mx-auto max-w-md py-16 text-center", children: [_jsx("p", { className: "text-sm font-semibold text-gold-500", children: "404" }), _jsx("h1", { className: "mt-2 text-xl font-semibold text-slate-900", children: "Page not found" }), _jsx("p", { className: "mt-2 text-sm text-slate-500", children: "This screen does not exist yet. Modules are added phase by phase." }), _jsx(Link, { to: "/", className: "mt-6 inline-block rounded-lg bg-navy-900 px-4 py-2 text-sm font-medium text-white hover:bg-navy-800", children: "Back to overview" })] }));
}
