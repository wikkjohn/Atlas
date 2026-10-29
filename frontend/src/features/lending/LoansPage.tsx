import { Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { StatusPill } from "@/components/StatusPill";
import { SyntheticDataBadge } from "@/components/SyntheticDataBadge";
import { formatTimestamp } from "@/features/dashboard/format";
import { BUCKET_TONE, LOAN_TONE, LoanDetail } from "@/features/lending/LoanDetail";
import { ServicingPanel } from "@/features/lending/ServicingPanel";
import { useLoans } from "@/services/banking";
import { formatExactMoney, humanize } from "@/services/format";
import type { LoanStatus } from "@/types/banking";

const PAGE_SIZE = 25;
const FILTERS: { value: LoanStatus | ""; label: string }[] = [
  { value: "", label: "All" },
  { value: "active", label: "Active" },
  { value: "repaid", label: "Repaid" },
  { value: "written_off", label: "Written off" },
];

export function LoansPage() {
  const [status, setStatus] = useState<LoanStatus | "">("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [openId, setOpenId] = useState<string | null>(null);
  const loans = useLoans({ status: status || null, q: q || null, limit: PAGE_SIZE, offset });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Lending"
        description="Personal loans originated by WF-0003 and serviced monthly: interest accrues and level instalments are collected through the ledger on the lending business date. Missed instalments put a loan in arrears; WF-0004 works the collections case and, at 90 days past due, a credit committee decides on a write-off."
        actions={<SyntheticDataBadge />}
      />
      <ServicingPanel />
      <div className="flex flex-wrap items-center gap-3">
        <div role="tablist" aria-label="Loan status" className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5 text-xs">
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
            aria-label="Search loans"
            placeholder="Loan number or customer"
            className="w-64 rounded-lg border border-slate-200 bg-white py-1.5 pr-3 pl-8 text-sm"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
          />
        </div>
      </div>
      <ErrorMessage error={loans.error} />
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table aria-label="Loans" className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="px-3 py-2">Loan</th>
              <th className="px-3 py-2">Borrower</th>
              <th className="px-3 py-2 text-right">Principal</th>
              <th className="px-3 py-2 text-right">Rate · term</th>
              <th className="px-3 py-2 text-right">Monthly</th>
              <th className="px-3 py-2 text-right">Outstanding</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Approvals</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {loans.data?.items.map((l) => (
              <tr key={l.id} className="align-top">
                <td className="px-3 py-2">
                  <div className="font-mono text-xs text-slate-900">{l.loan_number}</div>
                  <div className="text-xs text-slate-500">{humanize(l.purpose)}</div>
                  <div className="text-[11px] text-slate-400">{formatTimestamp(l.disbursed_at)}</div>
                </td>
                <td className="px-3 py-2">
                  <div className="text-slate-900">{l.customer_name}</div>
                  <div className="font-mono text-[11px] text-slate-500">
                    {l.customer_number} · {l.disbursement_account_number}
                  </div>
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{formatExactMoney(l.principal, l.currency)}</td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {(l.annual_rate_bps / 100).toFixed(2)} % · {l.term_months} mo
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{formatExactMoney(l.monthly_payment, l.currency)}</td>
                <td className="px-3 py-2 text-right tabular-nums">
                  <div>{formatExactMoney(l.outstanding, l.currency)}</div>
                  <div className="text-[11px] text-slate-400">
                    {l.instalments_paid}/{l.instalments_total} paid
                  </div>
                </td>
                <td className="space-y-1 px-3 py-2">
                  <StatusPill compact tone={LOAN_TONE[l.status]} label={humanize(l.status)} />
                  {l.status === "active" && l.days_past_due > 0 && (
                    <div>
                      <StatusPill compact tone={BUCKET_TONE[l.arrears_bucket]} label={`${l.days_past_due} DPD`} />
                      <div className="mt-0.5 text-[11px] text-slate-500 tabular-nums">
                        {formatExactMoney(l.arrears_amount, l.currency)} overdue
                      </div>
                    </div>
                  )}
                  {l.status === "active" && l.days_past_due === 0 && l.next_due_date && (
                    <div className="text-[11px] text-slate-500">Next due {l.next_due_date}</div>
                  )}
                </td>
                <td className="px-3 py-2 text-xs text-slate-600">
                  <div>Underwriter: {l.underwritten_by_username ?? "—"}</div>
                  {l.committee_approved_by_username && <div>Committee: {l.committee_approved_by_username}</div>}
                  {l.written_off_by_username && <div>Written off by: {l.written_off_by_username}</div>}
                  {l.workflow_execution_id && (
                    <Link className="text-navy-700 underline" to={`/workflows?tab=executions&execution=${l.workflow_execution_id}`}>
                      Workflow case
                    </Link>
                  )}
                </td>
                <td className="px-3 py-2">
                  <Button size="sm" variant="secondary" aria-label={`Open ${l.loan_number}`} onClick={() => setOpenId(l.id)}>
                    Schedule
                  </Button>
                </td>
              </tr>
            ))}
            {loans.data?.items.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-6 text-center text-sm text-slate-500">
                  No loans here. Start an application from the Workflow Explorer (WF-0003).
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {loans.data && <Pagination total={loans.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />}
      {openId && <LoanDetail loanId={openId} onClose={() => setOpenId(null)} />}
    </div>
  );
}
