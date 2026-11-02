import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { X } from "lucide-react";
import { useEffect } from "react";
export function Modal({ title, onClose, children, footer, wide = false }) {
    useEffect(() => {
        const onKey = (event) => event.key === "Escape" && onClose();
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [onClose]);
    return (_jsxs("div", { className: "fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:items-center", children: [_jsx("div", { "aria-hidden": true, className: "fixed inset-0 bg-navy-950/50", onClick: onClose }), _jsxs("div", { role: "dialog", "aria-modal": "true", "aria-label": title, className: `relative w-full ${wide ? "max-w-2xl" : "max-w-lg"} rounded-xl bg-white shadow-xl`, children: [_jsxs("header", { className: "flex items-center justify-between border-b border-slate-100 px-5 py-3.5", children: [_jsx("h2", { className: "text-sm font-semibold text-slate-900", children: title }), _jsx("button", { type: "button", "aria-label": "Close", onClick: onClose, className: "rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600", children: _jsx(X, { className: "h-4 w-4" }) })] }), _jsx("div", { className: "px-5 py-4", children: children }), footer && (_jsx("footer", { className: "flex justify-end gap-2 border-t border-slate-100 px-5 py-3", children: footer }))] })] }));
}
