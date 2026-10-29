import { useState } from "react";
import { Link } from "react-router-dom";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Modal } from "@/components/Modal";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { formatTimestamp } from "@/features/dashboard/format";
import { useLoan, useLoanSchedule, usePayOffLoan, usePayoffQuote, useRepayArrears } from "@/services/banking";
import { formatExactMoney, humanize } from "@/services/format";
import { useExecutions } from "@/services/workflows";
import type { ArrearsBucket, InstalmentStatus, Loan, LoanStatus } from "@/types/banking";

export const LOAN_TONE: Record<LoanStatus, Tone> = { active: "neutral", repaid: "good", written_off: "bad" };
export const BUCKET_TONE: Record<ArrearsBucket, Tone> = {
  current: "good",
  "1-29": "warn",
  "30-59": "warn",
  "60-89": "bad",
  "90+": "bad",
};
const INSTALMENT_TONE: Record<InstalmentStatus, Tone> = {
  scheduled: "neutral",
  due: "bad",
  paid: "good",
  prepaid: "good",
  written_off: "bad",
};

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="mt-0.5 text-sm text-slate-900 tabular-nums">{children}</dd>
    </div>
  );
}

function Actions({ loan }: { loan: Loan }) {
  const [confirmPayoff, setConfirmPayoff] = useState(false);
  const repay = useRepayArrears();
  const payoff = usePayOffLoan();
  const quote = usePayoffQuote(loan.id, confirmPayoff);
  const money = (amount: number) => formatExactMoney(amount, loan.currency);

  return (
    <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="flex flex-wrap items-center gap-2">
        {loan.arrears_amount > 0 && (
          <Button
            size="sm"
            disabled={repay.isPending}
            onClick={() => repay.mutate({ id: loan.id, body: {} })}
          >
            Repay arrears ({money(loan.arrears_amount)})
          </Button>
        )}
        {!confirmPayoff && (
          <Button size="sm" variant="secondary" onClick={() => setConfirmPayoff(true)}>
            Pay off early…
          </Button>
        )}
      </div>
      {confirmPayoff && (
        <div className="space-y-2 text-sm" aria-label="Payoff quote">
          {quote.data && (
            <p className="text-slate-700">
              Outstanding principal {money(quote.data.principal)} plus accrued interest{" "}
              {money(quote.data.accrued_interest)}: <strong>{money(quote.data.total)}</strong> from{" "}
              {loan.disbursement_account_number}, booked {quote.data.as_of}.
            </p>
          )}
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="danger"
              disabled={!quote.data || payoff.isPending}
              onClick={() => payoff.mutate({ id: loan.id, body: {} }, { onSuccess: () => setConfirmPayoff(false) })}
            >
              Confirm payoff
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirmPayoff(false)}>
              Cancel
            </Button>
          </div>
          <ErrorMessage error={quote.error} />
        </div>
      )}
      <ErrorMessage error={repay.error ?? payoff.error} />
    </div>
  );
}

/** The loan's WF-0004 collections cases (the case's business key is the loan id). */
function CollectionsCases({ loanId }: { loanId: string }) {
  const cases = useExecutions({ workflow_id: "WF-0004", business_key: loanId, limit: 5 });
  if (!cases.data?.items.length) return null;
  return (
    <div aria-label="Collections cases" className="text-sm">
      <div className="text-xs font-medium tracking-wide text-slate-500 uppercase">Collections cases (WF-0004)</div>
      <ul className="mt-1 space-y-1">
        {cases.data.items.map((c) => (
          <li key={c.id} className="flex items-center gap-2">
            <Link className="text-navy-700 underline" to={`/workflows?tab=executions&execution=${c.id}`}>
              Opened {formatTimestamp(c.started_at)}
            </Link>
            <span className="text-slate-600">
              {c.outcome ? humanize(c.outcome) : humanize(c.current_steps[0] ?? c.status)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function LoanDetail({ loanId, onClose }: { loanId: string; onClose: () => void }) {
  const { can } = useAuth();
  const loan = useLoan(loanId);
  const schedule = useLoanSchedule(loanId);
  const l = loan.data;
  const money = (amount: number) => (l ? formatExactMoney(amount, l.currency) : "");

  return (
    <Modal title={l ? `Loan ${l.loan_number}` : "Loan"} onClose={onClose} wide>
      <ErrorMessage error={loan.error ?? schedule.error} />
      {l && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill tone={LOAN_TONE[l.status]} label={humanize(l.status)} />
            {l.status === "active" && (
              <StatusPill
                tone={BUCKET_TONE[l.arrears_bucket]}
                label={l.days_past_due ? `${l.days_past_due} days past due` : "Up to date"}
              />
            )}
            <span className="text-sm text-slate-600">
              {l.customer_name} · {l.disbursement_account_number}
            </span>
          </div>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Fact label="Principal">{money(l.principal)}</Fact>
            <Fact label="Outstanding">{money(l.outstanding)}</Fact>
            <Fact label="Instalments paid">
              {l.instalments_paid} of {l.instalments_total}
            </Fact>
            <Fact label="Monthly">{money(l.monthly_payment)}</Fact>
            <Fact label="Next due">
              {l.next_due_date ? `${l.next_due_date} · ${money(l.next_due_amount ?? 0)}` : "—"}
            </Fact>
            <Fact label="In arrears">{l.arrears_amount ? money(l.arrears_amount) : "—"}</Fact>
            <Fact label="Closed">{l.closed_on ?? "—"}</Fact>
            {l.written_off_by_username && <Fact label="Written off by">{l.written_off_by_username}</Fact>}
          </dl>
          {l.status === "active" && can("loans:repay") && <Actions loan={l} />}
          {can("workflows:read") && <CollectionsCases loanId={l.id} />}
          <div className="max-h-80 overflow-y-auto rounded-lg border border-slate-200">
            <table aria-label="Repayment schedule" className="min-w-full text-sm">
              <thead className="sticky top-0 bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
                <tr>
                  <th className="px-3 py-1.5">#</th>
                  <th className="px-3 py-1.5">Due</th>
                  <th className="px-3 py-1.5 text-right">Principal</th>
                  <th className="px-3 py-1.5 text-right">Interest</th>
                  <th className="px-3 py-1.5 text-right">Instalment</th>
                  <th className="px-3 py-1.5">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {schedule.data?.map((i) => (
                  <tr key={i.number}>
                    <td className="px-3 py-1.5 tabular-nums">{i.number}</td>
                    <td className="px-3 py-1.5 tabular-nums">{i.due_date}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{money(i.principal)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{money(i.interest)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{money(i.amount)}</td>
                    <td className="px-3 py-1.5">
                      <StatusPill compact tone={INSTALMENT_TONE[i.status]} label={humanize(i.status)} />
                      {i.paid_on && <span className="ml-2 text-[11px] text-slate-400">{i.paid_on}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Modal>
  );
}
