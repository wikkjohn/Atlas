import { KeyRound, LogOut, ShieldCheck, Smartphone } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill } from "@/components/StatusPill";
import { formatTimestamp } from "@/features/dashboard/format";
import {
  useConfirmEnrolment,
  useEndOtherSessions,
  useEndSession,
  useMySessions,
  useRegenerateRecoveryCodes,
  useRemoveMfa,
  useStartEnrolment,
} from "@/services/security";
import { codeAt, currentStep, secondsLeft } from "@/services/totp";
import type { AuthSessionInfo } from "@/types/enterprise";

/** The page's stand-in for an authenticator app: the current code for a secret. */
export function SimulatedAuthenticator({ secret }: { secret: string }) {
  const [code, setCode] = useState("······");
  const [left, setLeft] = useState(secondsLeft());
  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      setLeft(secondsLeft());
      void codeAt(secret, currentStep()).then((c) => !cancelled && setCode(c));
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [secret]);
  return (
    <div aria-label="Simulated authenticator" className="rounded-xl border border-slate-200 bg-slate-50 p-3">
      <div className="flex items-center gap-2 text-xs font-medium text-slate-600">
        <Smartphone aria-hidden className="h-4 w-4" /> Simulated authenticator app
      </div>
      <div className="mt-1 flex items-baseline gap-3">
        <span data-testid="authenticator-code" className="font-mono text-2xl tracking-[0.3em] text-slate-900">
          {code}
        </span>
        <span className="text-[11px] text-slate-500">changes in {left} s</span>
      </div>
    </div>
  );
}

function RecoveryCodes({ codes }: { codes: string[] }) {
  return (
    <div aria-label="Recovery codes" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
      <p className="font-medium">Recovery codes — shown only now. Each works once if you lose the authenticator.</p>
      <ul className="mt-2 grid grid-cols-2 gap-1 font-mono sm:grid-cols-4">
        {codes.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
    </div>
  );
}

function SecondFactor() {
  const { user, refreshUser } = useAuth();
  const start = useStartEnrolment();
  const confirm = useConfirmEnrolment();
  const regenerate = useRegenerateRecoveryCodes();
  const remove = useRemoveMfa();
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const enabled = Boolean(user?.mfa_enabled);

  const onConfirm = (event: FormEvent) => {
    event.preventDefault();
    confirm.mutate(code.trim(), {
      onSuccess: (r) => {
        setCodes(r.recovery_codes);
        setCode("");
        start.reset();
        void refreshUser();
      },
    });
  };

  return (
    <Panel
      title="Second factor"
      subtitle="A time-based code (TOTP) from an authenticator, asked for at every sign-in"
      actions={<StatusPill tone={enabled ? "good" : "neutral"} label={enabled ? "Enabled" : "Not enrolled"} />}
    >
      <div className="space-y-3 text-sm">
        {codes && <RecoveryCodes codes={codes} />}
        {!enabled && !start.data && (
          <Button onClick={() => start.mutate()} disabled={start.isPending}>
            <KeyRound aria-hidden className="h-4 w-4" /> Set up an authenticator
          </Button>
        )}
        {!enabled && start.data && (
          <form onSubmit={onConfirm} aria-label="Confirm authenticator" className="space-y-3">
            <p className="text-xs text-slate-600">
              Add this secret to an authenticator app (or use the simulated one below), then enter the code it shows.
            </p>
            <p className="break-all rounded-md bg-slate-100 px-2 py-1 font-mono text-xs" aria-label="Secret">
              {start.data.secret}
            </p>
            <p className="break-all text-[11px] text-slate-500">{start.data.provisioning_uri}</p>
            <SimulatedAuthenticator secret={start.data.secret} />
            <Field label="Code from the authenticator">
              {(p) => <input {...p} className={`${inputClass} font-mono`} value={code} onChange={(e) => setCode(e.target.value)} required />}
            </Field>
            <Button type="submit" disabled={confirm.isPending}>
              Turn on
            </Button>
          </form>
        )}
        {enabled && (
          <div className="space-y-3">
            <p className="text-xs text-slate-600">
              Enrolled. {user?.mfa_recovery_codes_left ?? 0} recovery code(s) left.
            </p>
            <Field label="Current code (to change the factor)">
              {(p) => <input {...p} className={`${inputClass} font-mono`} value={code} onChange={(e) => setCode(e.target.value)} />}
            </Field>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="secondary"
                disabled={!code || regenerate.isPending}
                onClick={() =>
                  regenerate.mutate(code.trim(), {
                    onSuccess: (r) => {
                      setCodes(r.recovery_codes);
                      setCode("");
                      void refreshUser();
                    },
                  })
                }
              >
                New recovery codes
              </Button>
              <Button
                variant="secondary"
                disabled={!code || remove.isPending}
                onClick={() =>
                  remove.mutate(code.trim(), {
                    onSuccess: () => {
                      setCode("");
                      setCodes(null);
                      void refreshUser();
                    },
                  })
                }
              >
                Remove the authenticator
              </Button>
            </div>
          </div>
        )}
        <ErrorMessage error={start.error ?? confirm.error ?? regenerate.error ?? remove.error} />
      </div>
    </Panel>
  );
}

const REASONS: Record<string, string> = {
  signed_out: "signed out",
  idle: "inactive",
  expired: "expired",
  deactivated: "account deactivated",
  mfa_enrolled: "authenticator added",
  mfa_reset: "authenticator reset",
  mfa_failed: "too many wrong codes",
  revoked_by_administrator: "ended by an administrator",
};

export function SessionTable({ sessions, onEnd }: { sessions: AuthSessionInfo[]; onEnd?: (id: string) => void }) {
  return (
    <table aria-label="Sessions" className="min-w-full text-xs">
      <thead className="text-left text-slate-500">
        <tr>
          <th className="py-1 pr-3 font-medium">Signed in</th>
          <th className="py-1 pr-3 font-medium">How</th>
          <th className="py-1 pr-3 font-medium">Second factor</th>
          <th className="py-1 pr-3 font-medium">Last active</th>
          <th className="py-1 pr-3 font-medium">Status</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {sessions.map((s) => (
          <tr key={s.id} className="border-t border-slate-100">
            <td className="py-1 pr-3">{formatTimestamp(s.created_at)}</td>
            <td className="py-1 pr-3">{s.method === "sso" ? `SSO (${s.provider})` : "Password"}</td>
            <td className="py-1 pr-3">{s.mfa.replace("_", " ")}</td>
            <td className="py-1 pr-3">{formatTimestamp(s.last_seen_at)}</td>
            <td className="py-1 pr-3">
              {s.revoked_at ? (
                `Ended: ${REASONS[s.revoked_reason ?? ""] ?? s.revoked_reason}`
              ) : s.current ? (
                <StatusPill tone="good" label="This session" compact />
              ) : (
                "Active"
              )}
            </td>
            <td className="py-1 text-right">
              {onEnd && !s.revoked_at && !s.current && (
                <Button size="sm" variant="secondary" onClick={() => onEnd(s.id)}>
                  End
                </Button>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Sessions() {
  const sessions = useMySessions();
  const end = useEndSession();
  const others = useEndOtherSessions();
  return (
    <Panel
      title="Sessions"
      subtitle="Every sign-in; a session ends after 30 minutes unused or 12 hours at most"
      actions={
        <Button size="sm" variant="secondary" disabled={others.isPending} onClick={() => others.mutate()}>
          <LogOut aria-hidden className="h-4 w-4" /> Sign out everywhere else
        </Button>
      }
    >
      <ErrorMessage error={sessions.error ?? end.error ?? others.error} />
      {sessions.data && <SessionTable sessions={sessions.data} onEnd={(id) => end.mutate(id)} />}
    </Panel>
  );
}

function Scope() {
  const { user } = useAuth();
  const scope = user?.scope;
  return (
    <Panel title="Where you can act" subtitle="Set by an administrator; your role decides what you can do">
      <dl className="grid gap-2 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs text-slate-500">Countries</dt>
          <dd aria-label="Country scope">{scope?.countries?.join(", ") ?? "All countries"}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Departments</dt>
          <dd aria-label="Department scope">{scope?.departments?.join(", ") ?? "All departments"}</dd>
        </div>
      </dl>
    </Panel>
  );
}

export function SecurityPage() {
  const { user } = useAuth();
  return (
    <div className="space-y-4">
      <PageHeader title="Security" description="Your second factor, your sessions and where your access applies" />
      {user?.mfa_enrolment_required && (
        <p role="alert" className="flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
          <ShieldCheck aria-hidden className="h-4 w-4" />
          Your role requires a second factor. Set up an authenticator to continue.
        </p>
      )}
      <SecondFactor />
      <Sessions />
      <Scope />
    </div>
  );
}
