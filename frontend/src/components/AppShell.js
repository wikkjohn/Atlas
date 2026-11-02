import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { LogOut, Menu, X } from "lucide-react";
import { useState, Suspense } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@/app/auth";
import { IMPLEMENTED_PHASE, NAV_ITEMS } from "@/app/navigation";
import { StatusPill } from "@/components/StatusPill";
import { SyntheticDataBadge } from "@/components/SyntheticDataBadge";
import { useHealth, useSystemInfo } from "@/services/queries";
function Brand() {
    return (_jsxs("div", { className: "flex items-center gap-3 px-5 py-5", children: [_jsx("div", { className: "flex h-9 w-9 items-center justify-center rounded-lg bg-gold-500 font-bold text-navy-950", children: "A" }), _jsxs("div", { className: "leading-tight", children: [_jsx("div", { className: "text-sm font-bold tracking-[0.18em] text-white", children: "ATLAS" }), _jsx("div", { className: "text-[10px] font-medium tracking-[0.22em] text-slate-400", children: "GLOBAL BANK" })] })] }));
}
function Navigation({ onNavigate }) {
    const { can } = useAuth();
    const items = NAV_ITEMS.filter((item) => !item.permission || can(item.permission));
    return (_jsx("nav", { "aria-label": "Primary", className: "flex-1 overflow-y-auto px-3 pb-4", children: _jsx("ul", { className: "space-y-0.5", children: items.map(({ label, path, icon: Icon, phase }) => {
                const available = phase <= IMPLEMENTED_PHASE;
                if (!available) {
                    return (_jsx("li", { children: _jsxs("span", { "aria-disabled": "true", title: `Delivered in Phase ${phase}`, className: "flex cursor-not-allowed items-center gap-3 rounded-lg px-3 py-2 text-sm text-slate-500", children: [_jsx(Icon, { "aria-hidden": true, className: "h-4 w-4" }), _jsx("span", { className: "flex-1 whitespace-nowrap", children: label }), _jsxs("span", { className: "rounded bg-navy-800 px-1.5 py-0.5 text-[10px] font-medium text-slate-400", children: ["Phase ", phase] })] }) }, path));
                }
                return (_jsx("li", { children: _jsxs(NavLink, { to: path, end: path === "/", onClick: onNavigate, className: ({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${isActive
                            ? "bg-navy-700 text-white"
                            : "text-slate-300 hover:bg-navy-800 hover:text-white"}`, children: [_jsx(Icon, { "aria-hidden": true, className: "h-4 w-4" }), label] }) }, path));
            }) }) }));
}
function ConnectionIndicator() {
    const health = useHealth();
    let tone = "neutral";
    let label = "Checking API…";
    if (health.isError) {
        tone = "bad";
        label = "API unreachable";
    }
    else if (health.data) {
        const db = health.data.components.database;
        if (db?.status !== "ok") {
            tone = "bad";
            label = "Database unavailable";
        }
        else if (health.data.status === "degraded") {
            tone = "warn";
            label = "Degraded";
        }
        else {
            tone = "good";
            label = "All systems operational";
        }
    }
    return (_jsx("div", { "data-testid": "connection-indicator", children: _jsx(StatusPill, { tone: tone, label: label, compact: true }) }));
}
function UserMenu() {
    const { user, logout } = useAuth();
    if (!user)
        return null;
    return (_jsxs("div", { className: "flex items-center gap-2 border-l border-slate-200 pl-3", children: [_jsxs("div", { className: "hidden text-right leading-tight md:block", children: [_jsx("div", { className: "text-xs font-medium text-slate-800", children: user.display_name }), _jsx("div", { className: "text-[11px] text-slate-500", children: user.role_name })] }), _jsx("button", { type: "button", onClick: () => logout(), "aria-label": "Sign out", title: "Sign out", className: "rounded-md p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800", children: _jsx(LogOut, { className: "h-4 w-4" }) })] }));
}
export function AppShell() {
    const [mobileOpen, setMobileOpen] = useState(false);
    const info = useSystemInfo();
    return (_jsxs("div", { className: "flex h-full", children: [_jsxs("aside", { className: "hidden w-68 shrink-0 flex-col bg-navy-900 lg:flex", children: [_jsx(Brand, {}), _jsx(Navigation, {}), _jsx("div", { className: "border-t border-navy-800 px-5 py-3 text-[11px] text-slate-500", children: info.data ? `v${info.data.version} · ${info.data.environment}` : "ATLAS platform" })] }), mobileOpen && (_jsxs("div", { className: "fixed inset-0 z-40 flex lg:hidden", children: [_jsx("button", { type: "button", "aria-label": "Close navigation", className: "absolute inset-0 bg-navy-950/60", onClick: () => setMobileOpen(false) }), _jsxs("aside", { className: "relative flex w-68 flex-col bg-navy-900", children: [_jsx("button", { type: "button", "aria-label": "Close navigation", className: "absolute top-5 right-3 text-slate-400 hover:text-white", onClick: () => setMobileOpen(false), children: _jsx(X, { className: "h-5 w-5" }) }), _jsx(Brand, {}), _jsx(Navigation, { onNavigate: () => setMobileOpen(false) })] })] })), _jsxs("div", { className: "flex min-w-0 flex-1 flex-col", children: [_jsxs("header", { className: "flex h-14 shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-4 lg:px-8", children: [_jsx("button", { type: "button", "aria-label": "Open navigation", className: "rounded-md p-1.5 text-slate-600 hover:bg-slate-100 lg:hidden", onClick: () => setMobileOpen(true), children: _jsx(Menu, { className: "h-5 w-5" }) }), _jsx("span", { className: "hidden text-sm font-bold tracking-[0.14em] text-slate-800 min-[440px]:inline lg:hidden", children: "ATLAS" }), _jsxs("div", { className: "ml-auto flex items-center gap-2 sm:gap-3", children: [_jsx("div", { className: "rounded-md bg-navy-900 px-1.5 py-1", children: _jsx(SyntheticDataBadge, {}) }), info.data && (_jsx("span", { className: "hidden text-xs text-slate-500 capitalize sm:inline", children: info.data.environment })), _jsx(ConnectionIndicator, {}), _jsx(UserMenu, {})] })] }), _jsx("main", { className: "flex-1 overflow-y-auto px-4 py-6 lg:px-8", children: _jsx(Suspense, { fallback: _jsx("p", { className: "text-sm text-slate-500", children: "Loading\u2026" }), children: _jsx(Outlet, {}) }) })] })] }));
}
