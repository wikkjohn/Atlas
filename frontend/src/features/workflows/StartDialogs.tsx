import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { apiPost, newIdempotencyKey } from "@/services/api";
import { useAccounts } from "@/services/banking";
import { currencyDigits, formatExactMoney } from "@/services/format";
import { useStartExecution } from "@/services/workflows";
import type { Account } from "@/types/banking";
import type { FxQuote } from "@/types/fx";

interface DialogProps {
  onClose: () => void;
  onStarted: (id: string) => void;
}

/** A decimal amount typed by a user, in minor units (NaN when it is not a valid amount). */
function minorUnits(value: string, currency: string, allowZero = false): number {
  const amount = Number(value);
  if (!value.trim() || !Number.isFinite(amount) || amount < 0 || (amount === 0 && !allowZero)) return Number.NaN;
  return Math.round(amount * 10 ** currencyDigits(currency));
}

function accountLabel(a: Account): string {
  return `${a.account_number} · ${a.customer_name} (${formatExactMoney(a.balance, a.currency)})`;
}

const PICKER_PAGE = 50;

interface AccountPickerProps {
  label: string;
  searchLabel: string;
  value: Account | null;
  onChange: (account: Account | null) => void;
  /** Extra server-side filters, e.g. a currency or account type. */
  filters?: Record<string, string | null | undefined>;
  /** Client-side guard on the options (the server filters too). */
  allow?: (account: Account) => boolean;
  describe?: (account: Account) => string;
  error?: string | null;
}

/** Open accounts, searched on the server by number or customer name, so any account can be
 * chosen however many exist. The chosen account stays selected while the search changes. */
function AccountPicker({ label, searchLabel, value, onChange, filters, allow, describe = accountLabel, error }: AccountPickerProps) {
  const [q, setQ] = useState("");
  const accounts = useAccounts({ status: "open", q: q.trim() || null, limit: PICKER_PAGE, ...filters });
  const found = (accounts.data?.items ?? []).filter((a) => !allow || allow(a));
  const options = value && !found.some((a) => a.id === value.id) ? [value, ...found] : found;
  const total = accounts.data?.total ?? 0;
  return (
    <div className="space-y-1.5">
      <input
        aria-label={searchLabel}
        placeholder="Search by account number or customer"
        className={inputClass}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <Field label={label} error={error} hint={total > PICKER_PAGE ? `First ${PICKER_PAGE} of ${total.toLocaleString()} — search to narrow.` : undefined}>
        {(p) => (
          <select
            {...p}
            className={inputClass}
            value={value?.account_number ?? ""}
            onChange={(e) => onChange(options.find((a) => a.account_number === e.target.value) ?? null)}
          >
            <option value="">Select…</option>
            {options.map((a) => (
              <option key={a.id} value={a.account_number}>
                {describe(a)}
              </option>
            ))}
          </select>
        )}
      </Field>
      <ErrorMessage error={accounts.error} />
    </div>
  );
}

function StartFooter({ form, pending, label, onClose }: { form: string; pending: boolean; label: string; onClose: () => void }) {
  return (
    <>
      <Button variant="secondary" onClick={onClose}>
        Cancel
      </Button>
      <Button type="submit" form={form} disabled={pending}>
        {pending ? "Submitting…" : label}
      </Button>
    </>
  );
}

export function StartPaymentDialog({ onClose, onStarted }: DialogProps) {
  const start = useStartExecution("WF-0002");
  const [key] = useState(newIdempotencyKey);
  const [debtor, setDebtor] = useState<Account | null>(null);
  const [creditor, setCreditor] = useState<Account | null>(null);
  const [form, setForm] = useState({ amount: "", reference: "" });
  const [submitted, setSubmitted] = useState(false);
  const set = (k: keyof typeof form, v: string) => setForm({ ...form, [k]: v });
  const payable = (a: Account) => a.id !== debtor?.id;
  const amount = debtor ? minorUnits(form.amount, debtor.currency) : Number.NaN;
  // A payee in another currency receives the amount converted at release (Phase 24).
  const converting = Boolean(debtor && creditor && debtor.currency !== creditor.currency);
  const estimate = useQuery({
    queryKey: ["fx", "quote", debtor?.currency, creditor?.currency, amount],
    queryFn: () =>
      apiPost<FxQuote>("/api/v1/fx/quote", { sell_currency: debtor!.currency, buy_currency: creditor!.currency, sell_amount: amount }),
    enabled: converting && !Number.isNaN(amount),
  });
  const errors = {
    debtor: debtor ? null : "Choose the paying account.",
    creditor: creditor && payable(creditor) ? null : "Choose a payee.",
    amount: Number.isNaN(amount) ? "Enter an amount above zero." : null,
    reference: form.reference.trim() ? null : "A reference is required.",
  };
  const show = (k: keyof typeof errors) => (submitted ? errors[k] : null);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (Object.values(errors).some(Boolean) || !debtor || !creditor) return;
    start.mutate(
      {
        idempotencyKey: key,
        input: {
          debtor_account_number: debtor.account_number,
          creditor_account_number: creditor.account_number,
          amount,
          currency: debtor.currency,
          reference: form.reference.trim(),
          channel: "branch",
        },
      },
      { onSuccess: (execution) => onStarted(execution.id) },
    );
  };

  return (
    <Modal
      wide
      title="New payment (WF-0002)"
      onClose={onClose}
      footer={<StartFooter form="wf0002-start" pending={start.isPending} label="Submit payment" onClose={onClose} />}
    >
      <form id="wf0002-start" aria-label="New payment" onSubmit={onSubmit} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <AccountPicker
          label="Paying account"
          searchLabel="Search paying accounts"
          value={debtor}
          onChange={(a) => {
            setDebtor(a);
            setCreditor(null);
          }}
          error={show("debtor")}
        />
        <AccountPicker
          label="Payee account"
          searchLabel="Search payees"
          value={creditor}
          onChange={setCreditor}
          allow={payable}
          describe={(a) => `${a.account_number} · ${a.customer_name} (${a.currency})`}
          error={show("creditor")}
        />
        <Field label={`Amount${debtor ? ` (${debtor.currency})` : ""}`} hint="High-value payments (10,000 or more) need a second approver." error={show("amount")}>
          {(p) => <input {...p} type="number" min={0} step="any" className={inputClass} value={form.amount} onChange={(e) => set("amount", e.target.value)} />}
        </Field>
        <Field label="Reference" error={show("reference")}>
          {(p) => <input {...p} maxLength={140} className={inputClass} value={form.reference} onChange={(e) => set("reference", e.target.value)} />}
        </Field>
      </form>
      {converting && (
        <p role="status" aria-label="Conversion estimate" className="mt-3 text-sm text-slate-700">
          {estimate.data
            ? `The payee receives about ${formatExactMoney(estimate.data.buy_amount, estimate.data.buy_currency)} at today's rate (${Number(estimate.data.customer_rate).toPrecision(6)}, ${estimate.data.margin_bps / 100} % margin); the rate on the release date applies.`
            : `The amount is converted from ${debtor!.currency} to ${creditor!.currency} when the payment is released.`}
        </p>
      )}
      <p className="mt-3 text-xs text-slate-500">
        Screening holds payments with scam indicators (for example a reference mentioning gift cards), payees on the synthetic
        watchlist and first payments that empty an account; fraud analysts decide them.
      </p>
      <ErrorMessage error={start.error} className="mt-4" />
    </Modal>
  );
}

const PURPOSES = [
  ["home_improvement", "Home improvement"],
  ["vehicle", "Vehicle"],
  ["education", "Education"],
  ["debt_consolidation", "Debt consolidation"],
  ["other", "Other"],
] as const;

export function StartLoanDialog({ onClose, onStarted }: DialogProps) {
  const start = useStartExecution("WF-0003");
  const [key] = useState(newIdempotencyKey);
  const [account, setAccount] = useState<Account | null>(null);
  const [form, setForm] = useState({
    amount: "",
    term_months: "36",
    purpose: "home_improvement",
    monthly_income: "",
    monthly_debt_payments: "0",
    employment_status: "employed",
  });
  const [submitted, setSubmitted] = useState(false);
  const set = (k: keyof typeof form, v: string) => setForm({ ...form, [k]: v });
  const currency = account?.currency ?? "USD";
  const amount = minorUnits(form.amount, currency);
  const income = minorUnits(form.monthly_income, currency);
  const debts = minorUnits(form.monthly_debt_payments, currency, true);
  const errors = {
    account: account ? null : "Choose the customer's current account.",
    amount: Number.isNaN(amount) ? "Enter the amount to borrow." : null,
    monthly_income: Number.isNaN(income) ? "Enter the declared monthly income." : null,
    monthly_debt_payments: Number.isNaN(debts) ? "Enter 0 or the monthly repayments." : null,
  };
  const show = (k: keyof typeof errors) => (submitted ? errors[k] : null);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (Object.values(errors).some(Boolean) || !account) return;
    start.mutate(
      {
        idempotencyKey: key,
        input: {
          customer_number: account.customer_number,
          disbursement_account_number: account.account_number,
          amount,
          term_months: Number(form.term_months),
          purpose: form.purpose,
          monthly_income: income,
          monthly_debt_payments: debts,
          employment_status: form.employment_status,
        },
      },
      { onSuccess: (execution) => onStarted(execution.id) },
    );
  };

  return (
    <Modal
      wide
      title="New personal loan application (WF-0003)"
      onClose={onClose}
      footer={<StartFooter form="wf0003-start" pending={start.isPending} label="Submit application" onClose={onClose} />}
    >
      <form id="wf0003-start" aria-label="New personal loan application" onSubmit={onSubmit} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <AccountPicker
          label="Customer and disbursement account"
          searchLabel="Search customers"
          value={account}
          onChange={setAccount}
          filters={{ account_type: "current" }}
          allow={(a) => a.account_type === "current"}
          describe={(a) => `${a.customer_name} · ${a.account_number}`}
          error={show("account")}
        />
        <Field label={`Amount (${currency})`} hint="Personal loans: 1,000 to 50,000; above 25,000 the credit committee also decides." error={show("amount")}>
          {(p) => <input {...p} type="number" min={0} step="any" className={inputClass} value={form.amount} onChange={(e) => set("amount", e.target.value)} />}
        </Field>
        <Field label="Term">
          {(p) => (
            <select {...p} className={inputClass} value={form.term_months} onChange={(e) => set("term_months", e.target.value)}>
              {[12, 24, 36, 48, 60, 72, 84].map((m) => (
                <option key={m} value={m}>
                  {m} months
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Purpose">
          {(p) => (
            <select {...p} className={inputClass} value={form.purpose} onChange={(e) => set("purpose", e.target.value)}>
              {PURPOSES.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={`Monthly income (${currency})`} hint="As declared by the applicant." error={show("monthly_income")}>
          {(p) => <input {...p} type="number" min={0} step="any" className={inputClass} value={form.monthly_income} onChange={(e) => set("monthly_income", e.target.value)} />}
        </Field>
        <Field label={`Existing monthly repayments (${currency})`} error={show("monthly_debt_payments")}>
          {(p) => (
            <input {...p} type="number" min={0} step="any" className={inputClass} value={form.monthly_debt_payments} onChange={(e) => set("monthly_debt_payments", e.target.value)} />
          )}
        </Field>
        <Field label="Employment">
          {(p) => (
            <select {...p} className={inputClass} value={form.employment_status} onChange={(e) => set("employment_status", e.target.value)}>
              <option value="employed">Employed</option>
              <option value="self_employed">Self-employed</option>
              <option value="retired">Retired</option>
              <option value="unemployed">Unemployed</option>
            </select>
          )}
        </Field>
      </form>
      <p className="mt-3 text-xs text-slate-500">
        The credit bureau is synthetic: each customer's score is derived from their name and date of birth. Applications that
        break the credit policy are declined automatically; the rest go to an underwriter.
      </p>
      <ErrorMessage error={start.error} className="mt-4" />
    </Modal>
  );
}
