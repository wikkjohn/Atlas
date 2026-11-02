import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Button } from "@/components/Button";
export function Pagination({ total, limit, offset, onChange }) {
    if (total === 0)
        return null;
    const from = offset + 1;
    const to = Math.min(offset + limit, total);
    return (_jsxs("nav", { "aria-label": "Pagination", className: "flex items-center justify-between gap-3 text-xs text-slate-500", children: [_jsxs("span", { children: [from.toLocaleString(), "\u2013", to.toLocaleString(), " of ", total.toLocaleString()] }), _jsxs("div", { className: "flex gap-2", children: [_jsx(Button, { variant: "secondary", size: "sm", disabled: offset === 0, onClick: () => onChange(Math.max(0, offset - limit)), children: "Previous" }), _jsx(Button, { variant: "secondary", size: "sm", disabled: to >= total, onClick: () => onChange(offset + limit), children: "Next" })] })] }));
}
