import { Building2, KeyRound } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { type SignInStep, useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { SyntheticDataBadge } from "@/components/SyntheticDataBadge";
import { ApiError } from "@/services/api";
import { directorySignIn, startSso, useSsoProviders } from "@/services/security";

type Step = { kind: "password" } | { kind: "mfa"; challengeToken: string } | { kind: "sso"; provider: string; name: string };

function Unauthorized({ error, fallback }: { error: unknown; fallback: string }) {
  if (error === null) return null;
  if (error instanceof ApiError && error.status === 401) {
    return (
      <p role="alert" className="text-sm text-rose-600">
        {error.message.startsWith("Request failed") ? fallback : error.message}
      </p>
    );
  }
  return <ErrorMessage error={error} />;
}

/** Phase 84: the second step when the user has an authenticator enrolled. */
function MfaStep({ challengeToken, onDone, onCancel }: { challengeToken: string; onDone: () => void; onCancel: () => void }) {
  const { verifyMfa } = useAuth();
  const [code, setCode] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await verifyMfa(challengeToken, code.trim());
      onDone();
    } catch (caught) {
      setError(caught);
    } finally {
      setSubmitting(false);
    }
  };
  return (
    <form onSubmit={submit} aria-label="Second factor" className="space-y-4 rounded-xl bg-white p-6 shadow-xl">
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
        <KeyRound aria-hidden className="h-4 w-4" /> Enter your authenticator code
      </div>
      <p className="text-xs text-slate-500">
        The six-digit code from your authenticator, or one of your recovery codes.
      </p>
      <Field label="Code">
        {(props) => (
          <input
            {...props}
            className={`${inputClass} font-mono tracking-widest`}
            autoComplete="one-time-code"
            inputMode="text"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
          />
        )}
      </Field>
      <Unauthorized error={error} fallback="The code is not valid." />
      <Button type="submit" className="w-full" disabled={submitting}>
        {submitting ? "Checking…" : "Verify"}
      </Button>
      <button type="button" onClick={onCancel} className="w-full text-center text-xs text-slate-500 hover:underline">
        Start again
      </button>
    </form>
  );
}

/** Phase 84: the simulated ATLAS Corporate Directory, standing in for an identity
 * provider's own sign-in page. */
function DirectoryStep({ provider, name, onStep, onCancel }: { provider: string; name: string; onStep: (step: SignInStep) => void; onCancel: () => void }) {
  const { completeSso } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const request = await startSso(provider);
      const { id_token } = await directorySignIn(provider, {
        nonce: request.nonce,
        username: username.trim(),
        password,
        otp: otp.trim() || null,
      });
      onStep(await completeSso(provider, request.state, id_token));
    } catch (caught) {
      setError(caught);
    } finally {
      setSubmitting(false);
    }
  };
  return (
    <form onSubmit={submit} aria-label={name} className="space-y-4 rounded-xl border-4 border-sky-700 bg-white p-6 shadow-xl">
      <div>
        <div className="flex items-center gap-2 text-sm font-semibold text-sky-900">
          <Building2 aria-hidden className="h-4 w-4" /> {name}
        </div>
        <p className="mt-1 text-[11px] text-slate-500">
          Simulated identity provider: it signs you in and vouches for you to the bank.
        </p>
      </div>
      <Field label="Directory username">
        {(props) => <input {...props} className={inputClass} autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />}
      </Field>
      <Field label="Directory password">
        {(props) => <input {...props} type="password" className={inputClass} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />}
      </Field>
      <Field label="One-time code (if you have an authenticator)">
        {(props) => <input {...props} className={`${inputClass} font-mono`} autoComplete="one-time-code" value={otp} onChange={(e) => setOtp(e.target.value)} />}
      </Field>
      <Unauthorized error={error} fallback="The directory rejected the sign-in." />
      <Button type="submit" className="w-full" disabled={submitting}>
        {submitting ? "Signing in…" : "Continue to ATLAS Global Bank"}
      </Button>
      <button type="button" onClick={onCancel} className="w-full text-center text-xs text-slate-500 hover:underline">
        Back to the bank's sign-in
      </button>
    </form>
  );
}

export function LoginPage() {
  const { status, login, notice } = useAuth();
  const providers = useSsoProviders();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);
  const [step, setStep] = useState<Step>({ kind: "password" });

  const from = (location.state as { from?: string } | null)?.from ?? "/";
  if (status === "authenticated") return <Navigate to={from} replace />;

  const advance = (result: SignInStep) => {
    if (result.done) navigate(from, { replace: true });
    else setStep({ kind: "mfa", challengeToken: result.challengeToken });
  };

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      advance(await login(username.trim(), password));
    } catch (caught) {
      setError(caught);
    } finally {
      setSubmitting(false);
    }
  };

  const restart = () => setStep({ kind: "password" });

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
        {step.kind === "mfa" && <MfaStep challengeToken={step.challengeToken} onDone={() => navigate(from, { replace: true })} onCancel={restart} />}
        {step.kind === "sso" && <DirectoryStep provider={step.provider} name={step.name} onStep={advance} onCancel={restart} />}
        {step.kind === "password" && (
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
              (error instanceof ApiError && (error.status === 401 || error.status === 429) ? (
                <p role="alert" className="text-sm text-rose-600">
                  {/* The server's own words: a lockout or a rate limit says so (Phase 85). */}
                  {error.message.startsWith("Request failed") ? "Invalid username or password." : error.message}
                </p>
              ) : (
                <ErrorMessage error={error} />
              ))}
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "Signing in…" : "Sign in"}
            </Button>
            {providers.data?.map((p) => (
              <Button
                key={p.id}
                type="button"
                variant="secondary"
                className="w-full"
                onClick={() => setStep({ kind: "sso", provider: p.id, name: p.name })}
              >
                <Building2 aria-hidden className="h-4 w-4" /> Continue with {p.name}
                {p.simulated ? " (simulated SSO)" : " (SSO)"}
              </Button>
            ))}
            <p className="text-center text-xs text-slate-500">
              Local demo accounts are created with <code className="font-mono">make seed</code>.
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
