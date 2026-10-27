import { CheckCircle2, Search, XCircle } from "lucide-react";
import { type FormEvent, Fragment, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useAuth } from "@/app/auth";
import {
  ACCOUNT_TYPE_LABELS,
  AccountStatusBadge,
  RequestStatusBadge,
  RiskBadge,
} from "@/components/BankingBadges";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { formatTimestamp } from "@/features/dashboard/format";
import { newIdempotencyKey } from "@/services/api";
import {
  useAccount,
  useAccountRequests,
  useAccounts,
  useAccountStatus,
  useDecideRequest,
  useJournalEntries,
  useLedgerAccounts,
  useMovement,
  useReconciliation,
  useTransactions,
} from "@/services/banking";
import { currencyDigits, formatMoney, toMinorUnits } from "@/services/format";
import type { Account, AccountRequest } from "@/types/banking";

const PAGE_SIZE = 25;
type Tab = "accounts" | "requests" | "ledger";

/** Exact amount with the currency's minor digits (statements need precision). */
function exactMoney(minor: number, currency: string): string {
  const digits = currencyDigits(currency);
  try {
    return new Intl.NumberFormat("en", {
      style: "currency",
      currency,
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(minor / 10 ** digits);
  } catch {
    return `${minor} ${currency}`;
  }
}

function MovementForm({ account, kind }: { account: Account; kind: "deposits" | "withdrawals" }) {
  const movement = useMovement(account.id);
  const [amount, setAmount] = useState("");
  // One key per intended transaction: a retry after a failure reuses it, so the ledger
  // can never post the same deposit twice. A fresh key is taken after success.
  const [key, setKey] = useState(newIdempotencyKey);
  const label = kind === "deposits" ? "Deposit" : "Withdraw";

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    movement.mutate(
      { kind, amount: toMinorUnits(Number(amount), account.currency), idempotencyKey: key },
      {
        onSuccess: () => {
          setAmount("");
          setKey(newIdempotencyKey());
        },
      },
    );
  };

  return (
    <form onSubmit={onSubmit} aria-label={label} className="space-y-2">
      <div className="flex items-end gap-2">
        <Field label={`${label} (${account.currency})`}>
          {(p) => (
            <input
              {...p}
              className={inputClass}
              type="number"
              min={1 / 10 ** currencyDigits(account.currency)}
              step={1 / 10 ** currencyDigits(account.currency)}
              required
              value={amount}
              onChange={(e) => {
                setAmount(e.target.value);
                setKey(newIdempotencyKey());
              }}
            />
          )}
        </Field>
        <Button type="submit" variant={kind === "deposits" ? "primary" : "secondary"} disabled={movement.isPending}>
          {label}
        </Button>
      </div>
      {movement.data && (
        <p role="status" className="text-xs text-emerald-700">
          Posted {movement.data.entry_number}
          {movement.data.replayed ? " (already posted — not repeated)" : ""}.
        </p>
      )}
      <ErrorMessage error={movement.error} />
    </form>
  );
}

function StatusActions({ account }: { account: Account }) {
  const change = useAccountStatus(account.id);
  const [reason, setReason] = useState("");
  if (account.status === "closed") return null;
  const actions: { action: "freeze" | "unfreeze" | "close"; label: string }[] =
    account.status === "open"
      ? [
          { action: "freeze", label: "Freeze" },
          { action: "close", label: "Close account" },
        ]
      : [
          { action: "unfreeze", label: "Unfreeze" },
          { action: "close", label: "Close account" },
        ];
  return (
    <section aria-label="Account controls" className="space-y-2 rounded-lg border border-slate-200 p-4">
      <h4 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">Controls</h4>
      <Field label="Reason" hint="Recorded in the audit log.">
        {(p) => <input {...p} className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} />}
      </Field>
      <div className="flex gap-2">
        {actions.map(({ action, label }) => (
          <Button
            key={action}
            size="sm"
            variant={action === "close" ? "danger" : "secondary"}
            disabled={reason.trim().length < 3 || change.isPending}
            onClick={() => change.mutate({ action, reason: reason.trim() }, { onSuccess: () => setReason("") })}
          >
            {label}
          </Button>
        ))}
      </div>
      <ErrorMessage error={change.error} />
    </section>
  );
}

function AccountDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { can } = useAuth();
  const account = useAccount(id);
  const transactions = useTransactions(id);
  const a = account.data;

  return (
    <Modal wide title="Account" onClose={onClose}>
      <ErrorMessage error={account.error} />
      {a && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="font-mono text-lg font-semibold text-slate-900">{a.account_number}</h3>
              <p className="text-sm text-slate-600">
                {a.customer_name} · {ACCOUNT_TYPE_LABELS[a.account_type]} · opened {formatTimestamp(a.opened_at)}
              </p>
              <p className="font-mono text-[11px] text-slate-500">Ledger account {a.ledger_account_code}</p>
            </div>
            <div className="text-right">
              <AccountStatusBadge status={a.status} />
              <p aria-label="Balance" className="mt-1 text-2xl font-semibold text-slate-900">
                {exactMoney(a.balance, a.currency)}
              </p>
              <p className="text-[11px] text-slate-500">Derived from posted ledger entries</p>
            </div>
          </div>
          {can("accounts:transact") && a.status === "open" && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <MovementForm account={a} kind="deposits" />
              <MovementForm account={a} kind="withdrawals" />
            </div>
          )}
          <section aria-label="Transactions">
            <h4 className="mb-1.5 text-xs font-semibold tracking-wide text-slate-500 uppercase">Transactions</h4>
            {transactions.data?.items.length === 0 && <p className="text-sm text-slate-500">No postings yet.</p>}
            <table className="min-w-full text-sm">
              <tbody className="divide-y divide-slate-100">
                {transactions.data?.items.map((t) => (
                  <tr key={`${t.entry_id}-${t.direction}`}>
                    <td className="py-1.5 text-xs whitespace-nowrap text-slate-500">{formatTimestamp(t.posted_at)}</td>
                    <td className="py-1.5 font-mono text-xs text-slate-500">{t.entry_number}</td>
                    <td className="py-1.5 text-slate-700">{t.description}</td>
                    <td
                      className={`py-1.5 text-right font-medium whitespace-nowrap ${t.direction === "credit" ? "text-emerald-700" : "text-slate-900"}`}
                    >
                      {t.direction === "credit" ? "+" : "−"}
                      {exactMoney(t.amount, a.currency)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          {can("accounts:manage") && <StatusActions key={a.status} account={a} />}
        </div>
      )}
    </Modal>
  );
}

function AccountsTab({ onOpen }: { onOpen: (id: string) => void }) {
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const accounts = useAccounts({ q: q || undefined, status: status || undefined, limit: PAGE_SIZE, offset });

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <form
          role="search"
          className="relative"
          onSubmit={(e) => {
            e.preventDefault();
            setQ(search.trim());
            setOffset(0);
          }}
        >
          <Search aria-hidden className="pointer-events-none absolute top-2 left-2.5 h-4 w-4 text-slate-400" />
          <input
            aria-label="Search accounts"
            placeholder="Account number or customer"
            className="w-64 rounded-lg border border-slate-200 bg-white py-1.5 pr-3 pl-8 text-sm"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </form>
        <select
          aria-label="Account status"
          className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">Any status</option>
          <option value="open">Open</option>
          <option value="frozen">Frozen</option>
          <option value="closed">Closed</option>
        </select>
      </div>
      <ErrorMessage error={accounts.error} className="mb-4" />
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="px-4 py-2.5">Account</th>
              <th className="px-4 py-2.5">Customer</th>
              <th className="px-4 py-2.5">Type</th>
              <th className="px-4 py-2.5">Status</th>
              <th className="px-4 py-2.5 text-right">Balance</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {accounts.data?.items.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                  No accounts match.
                </td>
              </tr>
            )}
            {accounts.data?.items.map((a) => (
              <tr key={a.id} className="cursor-pointer hover:bg-slate-50" onClick={() => onOpen(a.id)}>
                <td className="px-4 py-2.5">
                  <button type="button" className="font-mono text-sm text-slate-900 hover:underline">
                    {a.account_number}
                  </button>
                </td>
                <td className="px-4 py-2.5 text-slate-700">{a.customer_name}</td>
                <td className="px-4 py-2.5 text-slate-600">{ACCOUNT_TYPE_LABELS[a.account_type]}</td>
                <td className="px-4 py-2.5">
                  <AccountStatusBadge status={a.status} />
                </td>
                <td className="px-4 py-2.5 text-right font-medium whitespace-nowrap text-slate-900">
                  {formatMoney(a.balance, a.currency)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {accounts.data && (
        <div className="mt-3">
          <Pagination total={accounts.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
        </div>
      )}
    </>
  );
}

function RequestActions({ request }: { request: AccountRequest }) {
  const { user, can } = useAuth();
  const decide = useDecideRequest();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  if (request.status !== "pending" || !can("accounts:approve")) return null;
  if (request.requested_by === user?.id) {
    return <span className="text-xs text-slate-400" title="Four-eyes rule">Needs another approver</span>;
  }
  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex gap-1.5">
        <Button
          size="sm"
          disabled={decide.isPending}
          onClick={() => decide.mutate({ id: request.id, decision: "approve", body: { note: null } })}
        >
          <CheckCircle2 aria-hidden className="h-3.5 w-3.5" />
          Approve
        </Button>
        <Button size="sm" variant="secondary" onClick={() => setRejecting(true)}>
          <XCircle aria-hidden className="h-3.5 w-3.5" />
          Reject
        </Button>
      </div>
      {decide.error && <ErrorMessage error={decide.error} className="max-w-xs text-left text-xs" />}
      {rejecting && (
        <Modal
          title="Reject account request"
          onClose={() => setRejecting(false)}
          footer={
            <Button
              variant="danger"
              disabled={reason.trim().length < 3 || decide.isPending}
              onClick={() =>
                decide.mutate(
                  { id: request.id, decision: "reject", body: { reason: reason.trim() } },
                  { onSuccess: () => setRejecting(false) },
                )
              }
            >
              Reject request
            </Button>
          }
        >
          <Field label="Reason">
            {(p) => <input {...p} className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} />}
          </Field>
        </Modal>
      )}
    </div>
  );
}

function RequestsTab() {
  const [status, setStatus] = useState("pending");
  const [offset, setOffset] = useState(0);
  const requests = useAccountRequests({ status: status || undefined, limit: PAGE_SIZE, offset });

  return (
    <>
      <div className="mb-4 flex items-center gap-3">
        <select
          aria-label="Request status"
          className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setOffset(0);
          }}
        >
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="">All</option>
        </select>
        <p className="text-xs text-slate-500">
          Approval opens the account. Requesters cannot approve their own requests; high-risk customers need a
          compliance approver.
        </p>
      </div>
      <ErrorMessage error={requests.error} className="mb-4" />
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="px-4 py-2.5">Customer</th>
              <th className="px-4 py-2.5">Account</th>
              <th className="px-4 py-2.5">Requested</th>
              <th className="px-4 py-2.5">Status</th>
              <th className="px-4 py-2.5 text-right">Decision</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {requests.data?.items.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                  No requests.
                </td>
              </tr>
            )}
            {requests.data?.items.map((r) => (
              <tr key={r.id}>
                <td className="px-4 py-2.5">
                  <div className="font-medium text-slate-900">{r.customer_name}</div>
                  <div className="mt-0.5 flex items-center gap-2">
                    <span className="font-mono text-[11px] text-slate-500">{r.customer_number}</span>
                    <RiskBadge rating={r.customer_risk_rating} />
                  </div>
                </td>
                <td className="px-4 py-2.5 text-slate-700">
                  {ACCOUNT_TYPE_LABELS[r.account_type]} · {r.currency}
                </td>
                <td className="px-4 py-2.5 text-xs text-slate-600">
                  {r.requested_by_username}
                  <div className="text-slate-400">{formatTimestamp(r.created_at)}</div>
                </td>
                <td className="px-4 py-2.5">
                  <RequestStatusBadge status={r.status} />
                  {r.decided_by_username && (
                    <div className="mt-0.5 text-[11px] text-slate-500">by {r.decided_by_username}</div>
                  )}
                </td>
                <td className="px-4 py-2.5 text-right">
                  <RequestActions request={r} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {requests.data && (
        <div className="mt-3">
          <Pagination total={requests.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
        </div>
      )}
    </>
  );
}

function LedgerTab() {
  const [currency, setCurrency] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const reconciliation = useReconciliation();
  const accounts = useLedgerAccounts({ currency: currency || undefined, q: "1000", limit: 20 });
  const entries = useJournalEntries({ currency: currency || undefined, limit: 25 });
  const report = reconciliation.data;

  return (
    <div className="space-y-6">
      <section aria-label="Reconciliation" className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Reconciliation</h2>
            <p className="text-xs text-slate-500">
              Verifies every entry balances, currencies match, and debits equal credits per currency. Each run is
              audited.
            </p>
          </div>
          <Button onClick={() => reconciliation.mutate()} disabled={reconciliation.isPending}>
            {reconciliation.isPending ? "Running…" : "Run reconciliation"}
          </Button>
        </div>
        <ErrorMessage error={reconciliation.error} className="mt-3" />
        {report && (
          <div className="mt-4">
            <p className={`text-sm font-medium ${report.ok ? "text-emerald-700" : "text-rose-700"}`}>
              {report.ok ? "All checks passed" : "Reconciliation found problems"} · {report.entries_checked} entries,{" "}
              {report.lines_checked} lines
            </p>
            <ul className="mt-2 space-y-1 text-sm">
              {report.checks.map((check) => (
                <li key={check.name} className="flex items-start gap-2">
                  {check.passed ? (
                    <CheckCircle2 aria-label="passed" className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                  ) : (
                    <XCircle aria-label="failed" className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
                  )}
                  <span>
                    <span className="font-medium text-slate-900">{check.name}</span>
                    <span className="text-slate-500"> — {check.detail}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <div className="flex items-center gap-3">
        <label htmlFor="ledger-currency" className="text-xs font-medium text-slate-600">
          Currency
        </label>
        <select
          id="ledger-currency"
          className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-sm"
          value={currency}
          onChange={(e) => setCurrency(e.target.value)}
        >
          <option value="">All</option>
          {["USD", "GBP", "EUR", "SGD", "JPY"].map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      <section aria-label="Cash accounts" className="rounded-xl border border-slate-200 bg-white shadow-sm">
        <h2 className="border-b border-slate-100 px-5 py-3 text-sm font-semibold text-slate-900">Bank cash accounts</h2>
        <table className="min-w-full text-sm">
          <tbody className="divide-y divide-slate-100">
            {accounts.data?.items.map((a) => (
              <tr key={a.id}>
                <td className="px-5 py-2 font-mono text-xs text-slate-700">{a.code}</td>
                <td className="px-5 py-2 text-slate-700">{a.name}</td>
                <td className="px-5 py-2 text-right font-medium text-slate-900">{exactMoney(a.balance, a.currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section aria-label="Journal" className="rounded-xl border border-slate-200 bg-white shadow-sm">
        <h2 className="border-b border-slate-100 px-5 py-3 text-sm font-semibold text-slate-900">Journal (latest)</h2>
        <ErrorMessage error={entries.error} className="m-4" />
        <table className="min-w-full text-sm">
          <tbody className="divide-y divide-slate-100">
            {entries.data?.items.map((e) => (
              <Fragment key={e.id}>
                <tr className="cursor-pointer hover:bg-slate-50" onClick={() => setExpanded(expanded === e.id ? null : e.id)}>
                  <td className="px-5 py-2 font-mono text-xs text-slate-500">{e.entry_number}</td>
                  <td className="px-5 py-2 text-xs whitespace-nowrap text-slate-500">{formatTimestamp(e.posted_at)}</td>
                  <td className="px-5 py-2 text-slate-700">{e.description}</td>
                  <td className="px-5 py-2 text-xs text-slate-500">{e.status}</td>
                  <td className="px-5 py-2 text-right font-medium whitespace-nowrap">{exactMoney(e.total, e.currency)}</td>
                </tr>
                {expanded === e.id && (
                  <tr className="bg-slate-50">
                    <td colSpan={5} className="px-5 py-2">
                      <table aria-label={`Lines of ${e.entry_number}`} className="w-full text-xs">
                        <tbody>
                          {e.lines.map((line) => (
                            <tr key={line.line_number}>
                              <td className="py-0.5 font-mono">{line.ledger_account_code}</td>
                              <td className="py-0.5">{line.ledger_account_name}</td>
                              <td className="py-0.5 text-right">
                                {line.direction === "debit" ? exactMoney(line.amount, e.currency) : ""}
                              </td>
                              <td className="py-0.5 text-right">
                                {line.direction === "credit" ? exactMoney(line.amount, e.currency) : ""}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

export function AccountsPage() {
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab | null) ?? "accounts";
  const openId = params.get("account");
  const tabs: { id: Tab; label: string; visible: boolean }[] = [
    { id: "accounts", label: "Accounts", visible: true },
    { id: "requests", label: "Opening requests", visible: true },
    { id: "ledger", label: "General ledger", visible: can("ledger:read") },
  ];
  const set = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setParams(next);
  };

  return (
    <>
      <PageHeader
        title="Accounts"
        description="Synthetic bank accounts. Balances are derived from the double-entry ledger; accounts open only through approved requests."
      />
      <div role="tablist" aria-label="Account views" className="mb-5 flex gap-1 border-b border-slate-200">
        {tabs
          .filter((t) => t.visible)
          .map((t) => (
            <button
              key={t.id}
              role="tab"
              type="button"
              aria-selected={tab === t.id}
              onClick={() => set({ tab: t.id === "accounts" ? null : t.id })}
              className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${tab === t.id ? "border-navy-900 text-navy-900" : "border-transparent text-slate-500 hover:text-slate-800"}`}
            >
              {t.label}
            </button>
          ))}
      </div>
      {tab === "accounts" && <AccountsTab onOpen={(id) => set({ account: id })} />}
      {tab === "requests" && <RequestsTab />}
      {tab === "ledger" && can("ledger:read") && <LedgerTab />}
      {openId && <AccountDetail key={openId} id={openId} onClose={() => set({ account: null })} />}
    </>
  );
}
