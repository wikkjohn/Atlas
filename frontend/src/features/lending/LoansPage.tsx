import { Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { SyntheticDataBadge } from "@/components/SyntheticDataBadge";
import { formatTimestamp } from "@/features/dashboard/format";
import { useLoans } from "@/services/banking";
import { formatExactMoney, humanize } from "@/services/format";

const PAGE_SIZE = 25;

export function LoansPage() {
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const loans = useLoans({ q: q || null, limit: PAGE_SIZE, offset });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Lending"
        description="Personal loans originated by WF-0003: synthetic credit bureau, risk-based pricing, affordability, underwriting and — above the committee limit — a credit committee approval. Disbursements post from the loan receivable to the customer's account."
        actions={<SyntheticDataBadge />}
      />
      <div className="relative w-fit">
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
              <th className="px-3 py-2">Approvals</th>
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
                <td className="px-3 py-2 text-right tabular-nums">{formatExactMoney(l.outstanding, l.currency)}</td>
                <td className="px-3 py-2 text-xs text-slate-600">
                  <div>Underwriter: {l.underwritten_by_username ?? "—"}</div>
                  {l.committee_approved_by_username && <div>Committee: {l.committee_approved_by_username}</div>}
                  {l.workflow_execution_id && (
                    <Link className="text-navy-700 underline" to={`/workflows?tab=executions&execution=${l.workflow_execution_id}`}>
                      Workflow case
                    </Link>
                  )}
                </td>
              </tr>
            ))}
            {loans.data?.items.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-sm text-slate-500">
                  No loans yet. Start an application from the Workflow Explorer (WF-0003).
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {loans.data && <Pagination total={loans.data.total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />}
    </div>
  );
}
