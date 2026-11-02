import { Fragment as _Fragment, jsx as _jsx } from "react/jsx-runtime";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/app/auth";
import { BackendUnavailable } from "@/components/BackendUnavailable";
export function RequireAuth({ children }) {
    const { status, retry } = useAuth();
    const location = useLocation();
    if (status === "checking") {
        return (_jsx("div", { className: "flex h-full items-center justify-center text-sm text-slate-500", children: "Restoring your session\u2026" }));
    }
    if (status === "unreachable") {
        return (_jsx("div", { className: "mx-auto max-w-2xl px-4 py-16", children: _jsx(BackendUnavailable, { onRetry: retry, retrying: false }) }));
    }
    if (status === "anonymous") {
        return _jsx(Navigate, { to: "/login", replace: true, state: { from: location.pathname + location.search } });
    }
    return _jsx(_Fragment, { children: children });
}
