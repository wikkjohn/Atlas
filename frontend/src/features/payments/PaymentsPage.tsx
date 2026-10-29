import { Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { SyntheticDataBadge } from "@/components/SyntheticDataBadge";
import { formatTimestamp } from "@/features/dashboard/format";
import { usePayments } from "@/services/banking";
import { formatExactMoney } from "@/services/format";
import type { PaymentStatus } from "@/types/banking";

const PAGE_SIZE = 25;
const STATUS_TONE: Record<PaymentStatus, Tone> = { pending: "warn", released: "good", rejected: "bad" };
const FILTERS: { value: PaymentStatus | ""; label: string }[] = [
  { value: "", label: "All" },
  { value: "pending", label: "In progress" },
  { value: "released", label: "Released" },
  { value: "rejected", label: "Rejected" },
];

export function PaymentsPage() {
  const [status, setStatus] = useState<PaymentStatus | "">("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const payments = usePayments({ status: status || null, q: q || null, limit: PAGE_SIZE, offset });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Payments"
        description="Domestic payments between synthetic accounts. Each one runs through WF-0002: screening, fraud review, four-eyes approval above the high-value limit and a balanced ledger posting."
        actions={<SyntheticDataBadge />}
      />
      <div className="flex flex-wrap items-center gap-3">
        <div role="tablist" aria-label="Payment status" className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5 text-xs">
          {FILTERS.map((f) => (
            <button
              key={f.label}
              role="tab"
              type="button"
              aria-selected={status === f.value}
              onClick={() => {
                setStatus(f.value);
                setOffset(0);
              }}
              className={`rounded-md px-2.5 py-1 font-medium ${status === f.value ? "bg-navy-900 text-white" : "text-slate-600 hover:bg-slate-50"}`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="relative">
          <Search aria-hidden className="pointer-events-none absolute top-2 left-2.5 h-4 w-4 text-slate-400" />
          <input
            aria-label="Search payments"
            placeholder="Payment number or reference"
            className="w-64 rounded-lg border border-slate-200 bg-white py-1.5 pr-3 pl-8 text-sm"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
          />
        </div>
      </div>
      <ErrorMessage error={payments.error} />
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table aria-label="Payments" className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="px-3 py-2">Payment</th>
              <th className="px-3 py-2">From</th>
              <th className="px-3 py-2">To</th>
              <th className="px-3 py-2 text-right">Amount</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Approved by</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {payments.data?.items.map((p) => (
              <tr key={p.id} className="align-top">
                <td className="px-3 py-2">
                  <div className="font-mono text-xs text-slate-900">{p.payment_number}</div>
                  <div className="text-xs text-slate-500">{p.reference}</div>
                  <div className="text-[11px] text-slate-400">{formatTimestamp(p.created_at)}</div>
                </td>
                <td className="px-3 py-2">
                  <div className="text-slate-900">{p.debtor_name}</div>
                  <div className="font-mono text-[11px] text-slate-500">{p.debtor_account_number}</div>
                </td>
                <td className="px-3 py-2">
                  <div className="text-slate-900">{p.creditor_name}</div>
                  <div className="font-mono text-[11px] text-slate-500">{p.creditor_account_number}</div>
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {formatExactMoney(p.amount, p.currency)}
                  {p.high_value && <div className="text-[11px] text-amber-700">High value</div>}
                </td>
                <td className="px-3 py-2">
                  <StatusPill tone={STATUS_TONE[p.status]} label={p.status === "pending" ? "In progress" : p.status === "released" ? "Released" : "Rejected"} />
                  {p.rejection_reason && <div className="mt-1 max-w-xs text-xs text-slate-500">{p.rejection_reason}</div>}
                  {p.workflow_execution_id && (
                    <Link className="mt-1 block text-xs text-navy-700 underline" to={`/workflows?tab=executions&execution=${p.workflow_execution_id}`}>
                      Workflow case
                    </Link>
                  )}
                </td>
                <td className="px-3 py-2 text-xs text-slate-600">
                  {p.approved_by_username ?? (p.status === "released" ? "Straight-through" : "—")}
                </td>
              </tr>
            ))}
            {payments.data?.items.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-sm text-slate-500">
                  No payments yet. Start one from the Workflow Explorer (WF-0002).
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {payments.data && <Pagination total={payments.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />}
    </div>
  );
}
