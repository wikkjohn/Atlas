import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
export function PageHeader({ title, description, actions, }) {
    return (_jsxs("div", { className: "mb-6 flex flex-wrap items-end justify-between gap-4", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-xl font-semibold text-slate-900", children: title }), _jsx("p", { className: "mt-1 text-sm text-slate-500", children: description })] }), actions && _jsx("div", { className: "flex items-center gap-2", children: actions })] }));
}
