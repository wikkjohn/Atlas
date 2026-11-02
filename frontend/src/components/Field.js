import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useId } from "react";
/** Label + control + hint/error, wired up for accessibility. */
export function Field({ label, hint, error, children }) {
    const id = useId();
    const describedBy = error || hint ? `${id}-help` : undefined;
    return (_jsxs("div", { children: [_jsx("label", { htmlFor: id, className: "block text-xs font-medium text-slate-700", children: label }), _jsx("div", { className: "mt-1", children: children({ id, "aria-invalid": Boolean(error), "aria-describedby": describedBy }) }), (error || hint) && (_jsx("p", { id: describedBy, className: `mt-1 text-xs ${error ? "text-rose-600" : "text-slate-500"}`, children: error ?? hint }))] }));
}
export const inputClass = "block w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-navy-700 focus:ring-2 focus:ring-navy-700/20 focus:outline-none aria-[invalid=true]:border-rose-400 disabled:bg-slate-50";
