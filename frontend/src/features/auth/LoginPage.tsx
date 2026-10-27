import { type FormEvent, useState } from "react";
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
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

  const from = (location.state as { from?: string } | null)?.from ?? "/";
  if (status === "authenticated") return <Navigate to={from} replace />;

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username.trim(), password);
      navigate(from, { replace: true });
    } catch (caught) {
      setError(caught);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-full items-center justify-center bg-navy-900 px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gold-500 text-lg font-bold text-navy-950">
            A
          </div>
          <h1 className="mt-4 text-lg font-bold tracking-[0.2em] text-white">ATLAS GLOBAL BANK</h1>
          <p className="mt-1 text-sm text-slate-400">Enterprise simulation platform</p>
          <div className="mt-3 rounded-md bg-navy-950 px-1.5 py-1">
            <SyntheticDataBadge />
          </div>
        </div>
        <form
          onSubmit={onSubmit}
          aria-label="Sign in"
          className="space-y-4 rounded-xl bg-white p-6 shadow-xl"
        >
          {notice && (
            <p role="status" className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
              {notice}
            </p>
          )}
          <Field label="Username">
            {(props) => (
              <input
                {...props}
                className={inputClass}
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            )}
          </Field>
          <Field label="Password">
            {(props) => (
              <input
                {...props}
                type="password"
                className={inputClass}
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            )}
          </Field>
          {error !== null &&
            (error instanceof ApiError && error.status === 401 ? (
              <p role="alert" className="text-sm text-rose-600">
                Invalid username or password.
              </p>
            ) : (
              <ErrorMessage error={error} />
            ))}
          <Button type="submit" className="w-full" disabled={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </Button>
          <p className="text-center text-xs text-slate-500">
            Local demo accounts are created with <code className="font-mono">make seed</code>.
          </p>
        </form>
      </div>
    </div>
  );
}
