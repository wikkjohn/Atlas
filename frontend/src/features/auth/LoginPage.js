import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { SyntheticDataBadge } from "@/components/SyntheticDataBadge";
import { ApiError } from "@/services/api";
export function LoginPage() {
    const { status, login, notice } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState(null);
    const [submitting, setSubmitting] = useState(false);
    const from = location.state?.from ?? "/";
    if (status === "authenticated")
        return _jsx(Navigate, { to: from, replace: true });
    const onSubmit = async (event) => {
        event.preventDefault();
        setError(null);
        setSubmitting(true);
        try {
            await login(username.trim(), password);
            navigate(from, { replace: true });
        }
        catch (caught) {
            setError(caught);
        }
        finally {
            setSubmitting(false);
        }
    };
    return (_jsx("div", { className: "flex min-h-full items-center justify-center bg-navy-900 px-4 py-12", children: _jsxs("div", { className: "w-full max-w-sm", children: [_jsxs("div", { className: "mb-8 flex flex-col items-center text-center", children: [_jsx("div", { className: "flex h-12 w-12 items-center justify-center rounded-xl bg-gold-500 text-lg font-bold text-navy-950", children: "A" }), _jsx("h1", { className: "mt-4 text-lg font-bold tracking-[0.2em] text-white", children: "ATLAS GLOBAL BANK" }), _jsx("p", { className: "mt-1 text-sm text-slate-400", children: "Enterprise simulation platform" }), _jsx("div", { className: "mt-3 rounded-md bg-navy-950 px-1.5 py-1", children: _jsx(SyntheticDataBadge, {}) })] }), _jsxs("form", { onSubmit: onSubmit, "aria-label": "Sign in", className: "space-y-4 rounded-xl bg-white p-6 shadow-xl", children: [notice && (_jsx("p", { role: "status", className: "rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800", children: notice })), _jsx(Field, { label: "Username", children: (props) => (_jsx("input", { ...props, className: inputClass, autoComplete: "username", value: username, onChange: (e) => setUsername(e.target.value), required: true })) }), _jsx(Field, { label: "Password", children: (props) => (_jsx("input", { ...props, type: "password", className: inputClass, autoComplete: "current-password", value: password, onChange: (e) => setPassword(e.target.value), required: true })) }), error !== null &&
                            (error instanceof ApiError && error.status === 401 ? (_jsx("p", { role: "alert", className: "text-sm text-rose-600", children: "Invalid username or password." })) : (_jsx(ErrorMessage, { error: error }))), _jsx(Button, { type: "submit", className: "w-full", disabled: submitting, children: submitting ? "Signing in…" : "Sign in" }), _jsxs("p", { className: "text-center text-xs text-slate-500", children: ["Local demo accounts are created with ", _jsx("code", { className: "font-mono", children: "make seed" }), "."] })] })] }) }));
}
