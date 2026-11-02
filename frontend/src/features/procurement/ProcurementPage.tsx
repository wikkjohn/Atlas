import { useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { formatExactMoney, humanize, toMinorUnits } from "@/services/format";
import {
  useDecideInvoice,
  useDecideOrder,
  useDecideVendor,
  useInvoices,
  useOrders,
  useProcurementDepartments,
  useProcurementSummary,
  useRaiseOrder,
  useReceive,
  useRecordInvoice,
  useRegisterVendor,
  useRequestBankChange,
  useVendors,
  useVerifyBankChange,
} from "@/services/procurement";
import type { PurchaseOrder, Vendor, VendorInvoice } from "@/types/procurement";

const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const CATEGORIES = ["facilities", "marketing", "it", "professional_services", "outsourcing"];
const today = () => new Date().toISOString().slice(0, 10);
const VENDOR_TONE: Record<Vendor["status"], Tone> = { pending: "warn", approved: "good", rejected: "neutral", suspended: "bad" };
const TIER_TONE: Record<Vendor["risk_tier"], Tone> = { low: "good", medium: "warn", high: "bad" };
const ORDER_TONE: Record<PurchaseOrder["status"], Tone> = { requested: "warn", approved: "good", received: "good", rejected: "neutral", closed: "neutral" };
const INVOICE_TONE: Record<VendorInvoice["status"], Tone> = { recorded: "warn", held: "bad", paid: "good", rejected: "neutral" };

function VendorsPanel() {
  const { can } = useAuth();
  const vendors = useVendors();
  const register = useRegisterVendor();
  const decide = useDecideVendor();
  const change = useRequestBankChange();
  const verify = useVerifyBankChange();
  const [form, setForm] = useState({ name: "", country: "US", category: "facilities", account: "" });
  const [accounts, setAccounts] = useState<Record<string, string>>({});
  return (
    <Panel title="Vendors" subtitle="Every vendor is screened against the sanctions lists and tiered by its category (one tier higher outside the bank's active countries). Someone other than the registrant approves it (procurement:approve); a high-risk vendor only an executive. A change of bank account is verified by a second person, and nothing is paid to the vendor while it waits.">
      {can("procurement:manage") && (
        <form
          aria-label="Register vendor"
          className="mb-3 flex flex-wrap items-end gap-2 text-xs"
          onSubmit={(e) => {
            e.preventDefault();
            register.mutate({ name: form.name, country: form.country, category: form.category, bank_account: form.account });
          }}
        >
          <input aria-label="Vendor name" placeholder="Vendor name" className={`w-48 ${INPUT}`} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input aria-label="Vendor country" placeholder="US" maxLength={2} className={`w-14 ${INPUT}`} value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value.toUpperCase() })} />
          <select aria-label="Category" className={INPUT} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {humanize(c)}
              </option>
            ))}
          </select>
          <input aria-label="Bank account" placeholder="Bank account" className={`w-40 ${INPUT}`} value={form.account} onChange={(e) => setForm({ ...form, account: e.target.value })} />
          <Button size="sm" type="submit" disabled={form.name.trim().length < 2 || form.country.length !== 2 || form.account.trim().length < 8}>
            Register vendor
          </Button>
          {register.data && (
            <span role="status">
              {register.data.vendor_number} registered: {register.data.risk_tier} risk{register.data.sanctions_hit && ", sanctions hit"}
            </span>
          )}
        </form>
      )}
      <ErrorMessage error={vendors.error ?? register.error ?? decide.error ?? change.error ?? verify.error} />
      <table aria-label="Vendors" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {vendors.data?.items.map((v) => (
            <tr key={v.id} className="align-top">
              <td className="px-2 py-1.5 font-mono text-xs">{v.vendor_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {v.name} · {v.country} · {humanize(v.category)} · pays to <span className="font-mono">{v.bank_account}</span>
                {v.pending_bank_account && (
                  <>
                    {" "}
                    · change to <span className="font-mono">{v.pending_bank_account}</span> awaiting checks
                  </>
                )}
                {v.sanctions_hit && <span className="font-semibold text-rose-700"> · sanctions hit</span>}
              </td>
              <td className="px-2 py-1.5">
                <div className="flex gap-1">
                  <StatusPill compact tone={TIER_TONE[v.risk_tier]} label={`${v.risk_tier} risk`} />
                  <StatusPill compact tone={VENDOR_TONE[v.status]} label={v.status} />
                </div>
              </td>
              <td className="px-2 py-1.5 text-right">
                <div className="flex flex-wrap justify-end gap-1">
                  {v.status === "pending" && can("procurement:approve") && (
                    <>
                      <Button size="sm" aria-label={`Approve ${v.vendor_number}`} onClick={() => decide.mutate({ id: v.id, approve: true })}>
                        Approve
                      </Button>
                      <Button size="sm" variant="secondary" aria-label={`Reject ${v.vendor_number}`} onClick={() => decide.mutate({ id: v.id, approve: false })}>
                        Reject
                      </Button>
                    </>
                  )}
                  {v.pending_bank_account && can("procurement:approve") && (
                    <>
                      <Button size="sm" aria-label={`Verify bank change for ${v.vendor_number}`} onClick={() => verify.mutate({ id: v.id, accept: true })}>
                        Verify change
                      </Button>
                      <Button size="sm" variant="secondary" aria-label={`Refuse bank change for ${v.vendor_number}`} onClick={() => verify.mutate({ id: v.id, accept: false })}>
                        Refuse
                      </Button>
                    </>
                  )}
                  {v.status === "approved" && !v.pending_bank_account && can("procurement:manage") && (
                    <>
                      <input aria-label={`New bank account for ${v.vendor_number}`} placeholder="New account" className={`w-32 ${INPUT}`} value={accounts[v.id] ?? ""} onChange={(e) => setAccounts({ ...accounts, [v.id]: e.target.value })} />
                      <Button
                        size="sm"
                        variant="secondary"
                        aria-label={`Change bank account for ${v.vendor_number}`}
                        disabled={(accounts[v.id] ?? "").trim().length < 8}
                        onClick={() => change.mutate({ id: v.id, bank_account: accounts[v.id] })}
                      >
                        Change account
                      </Button>
                    </>
                  )}
                </div>
              </td>
            </tr>
          ))}
          {vendors.data && vendors.data.items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No vendors yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}

function OrdersPanel() {
  const { can } = useAuth();
  const vendors = useVendors();
  const departments = useProcurementDepartments();
  const orders = useOrders();
  const raise = useRaiseOrder();
  const decide = useDecideOrder();
  const receive = useReceive();
  const [form, setForm] = useState({ vendor: "", department: "", description: "", quantity: "1", price: "" });
  const [received, setReceived] = useState<Record<string, string>>({});
  const approved = vendors.data?.items.filter((v) => v.status === "approved") ?? [];
  const currency = approved.find((v) => v.vendor_number === form.vendor)?.currency ?? "USD";
  return (
    <Panel title="Purchase orders" subtitle="Orders go to approved vendors, in the vendor's currency, charged to a department. Someone other than the requester approves (above US$50,000 an executive); deliveries are received up to the order's total.">
      {can("procurement:manage") && (
        <form
          aria-label="Raise order"
          className="mb-3 flex flex-wrap items-end gap-2 text-xs"
          onSubmit={(e) => {
            e.preventDefault();
            raise.mutate({
              vendor_number: form.vendor,
              department_id: form.department,
              description: form.description,
              lines: [{ description: form.description, quantity: Number(form.quantity), unit_price: toMinorUnits(Number(form.price), currency) }],
            });
          }}
        >
          <select aria-label="Vendor" className={INPUT} value={form.vendor} onChange={(e) => setForm({ ...form, vendor: e.target.value })}>
            <option value="">Choose an approved vendor</option>
            {approved.map((v) => (
              <option key={v.id} value={v.vendor_number}>
                {v.vendor_number} {v.name} ({v.currency})
              </option>
            ))}
          </select>
          <select aria-label="Department" className={INPUT} value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })}>
            <option value="">Choose a department</option>
            {departments.data?.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} ({d.country ?? "—"})
              </option>
            ))}
          </select>
          <input aria-label="Description" placeholder="What is ordered" className={`w-48 ${INPUT}`} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          <input aria-label="Quantity" type="number" min={1} className={`w-16 ${INPUT}`} value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} />
          <input aria-label="Unit price" type="number" min={0} step="0.01" placeholder={`Unit price (${currency})`} className={`w-28 ${INPUT}`} value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} />
          <Button size="sm" type="submit" disabled={!form.vendor || !form.department || form.description.trim().length < 3 || !form.price}>
            Raise order
          </Button>
          {raise.data && (
            <span role="status">
              {raise.data.order_number} raised: {formatExactMoney(raise.data.total, raise.data.currency)}
            </span>
          )}
        </form>
      )}
      <ErrorMessage error={orders.error ?? raise.error ?? decide.error ?? receive.error} />
      <table aria-label="Purchase orders" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {orders.data?.items.map((o) => (
            <tr key={o.id} className="align-top">
              <td className="px-2 py-1.5 font-mono text-xs">{o.order_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {o.vendor_name} · {o.department} · {o.description} · {formatExactMoney(o.total, o.currency)} · received {formatExactMoney(o.received_amount, o.currency)} · invoiced{" "}
                {formatExactMoney(o.invoiced, o.currency)}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={ORDER_TONE[o.status]} label={o.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                <div className="flex flex-wrap justify-end gap-1">
                  {o.status === "requested" && can("procurement:approve") && (
                    <>
                      <Button size="sm" aria-label={`Approve ${o.order_number}`} onClick={() => decide.mutate({ id: o.id, approve: true })}>
                        Approve
                      </Button>
                      <Button size="sm" variant="secondary" aria-label={`Reject ${o.order_number}`} onClick={() => decide.mutate({ id: o.id, approve: false })}>
                        Reject
                      </Button>
                    </>
                  )}
                  {(o.status === "approved" || o.status === "received") && o.received_amount < o.total && can("procurement:manage") && (
                    <>
                      <input aria-label={`Received for ${o.order_number}`} type="number" step="0.01" placeholder={o.currency} className={`w-24 ${INPUT}`} value={received[o.id] ?? ""} onChange={(e) => setReceived({ ...received, [o.id]: e.target.value })} />
                      <Button
                        size="sm"
                        variant="secondary"
                        aria-label={`Receive ${o.order_number}`}
                        disabled={!received[o.id]}
                        onClick={() => receive.mutate({ id: o.id, amount: toMinorUnits(Number(received[o.id]), o.currency) })}
                      >
                        Receive
                      </Button>
                    </>
                  )}
                </div>
              </td>
            </tr>
          ))}
          {orders.data && orders.data.items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No purchase orders yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}

function InvoicesPanel() {
  const { can } = useAuth();
  const orders = useOrders();
  const invoices = useInvoices();
  const record = useRecordInvoice();
  const decide = useDecideInvoice();
  const [form, setForm] = useState({ order: "", reference: "", amount: "", date: today() });
  const receivedOrders = orders.data?.items.filter((o) => o.status === "received") ?? [];
  const currency = receivedOrders.find((o) => o.order_number === form.order)?.currency ?? "USD";
  return (
    <Panel title="Invoices" subtitle="An invoice is matched against its order and what was received: within 2 % it waits for payment, beyond that it is held. A vendor's invoice reference is never paid twice. Someone other than whoever recorded it pays it (procurement:approve), to the vendor's verified account, debiting purchases and crediting the bank's cash.">
      {can("procurement:manage") && (
        <form
          aria-label="Record invoice"
          className="mb-3 flex flex-wrap items-end gap-2 text-xs"
          onSubmit={(e) => {
            e.preventDefault();
            record.mutate({ order_number: form.order, vendor_reference: form.reference, amount: toMinorUnits(Number(form.amount), currency), invoice_date: form.date });
          }}
        >
          <select aria-label="Order" className={INPUT} value={form.order} onChange={(e) => setForm({ ...form, order: e.target.value })}>
            <option value="">Choose a received order</option>
            {receivedOrders.map((o) => (
              <option key={o.id} value={o.order_number}>
                {o.order_number} {o.vendor_name}
              </option>
            ))}
          </select>
          <input aria-label="Vendor reference" placeholder="Vendor's invoice number" className={`w-40 ${INPUT}`} value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} />
          <input aria-label="Invoice amount" type="number" step="0.01" placeholder={`Amount (${currency})`} className={`w-28 ${INPUT}`} value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          <input aria-label="Invoice date" type="date" className={INPUT} value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} />
          <Button size="sm" type="submit" disabled={!form.order || !form.reference.trim() || !form.amount}>
            Record invoice
          </Button>
          {record.data && (
            <span role="status">
              {record.data.invoice_number} {record.data.status === "held" ? "held" : "matched"}
            </span>
          )}
        </form>
      )}
      <ErrorMessage error={invoices.error ?? record.error ?? decide.error} />
      <table aria-label="Invoices" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {invoices.data?.items.map((i) => (
            <tr key={i.id} className="align-top">
              <td className="px-2 py-1.5 font-mono text-xs">{i.invoice_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {i.vendor_name} {i.vendor_reference} · {i.order_number} · {formatExactMoney(i.amount, i.currency)} · {i.invoice_date}
                {i.hold_reason && ` · ${i.hold_reason}`}
                {i.paid_to && (
                  <>
                    {" "}
                    · paid to <span className="font-mono">{i.paid_to}</span> ({i.entry_number})
                  </>
                )}
              </td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={INVOICE_TONE[i.status]} label={i.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                {can("procurement:approve") && (i.status === "recorded" || i.status === "held") && (
                  <div className="flex justify-end gap-1">
                    {i.status === "recorded" && (
                      <Button size="sm" aria-label={`Pay ${i.invoice_number}`} onClick={() => decide.mutate({ id: i.id, pay: true })}>
                        Pay
                      </Button>
                    )}
                    <Button size="sm" variant="secondary" aria-label={`Reject ${i.invoice_number}`} onClick={() => decide.mutate({ id: i.id, pay: false })}>
                      Reject
                    </Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
          {invoices.data && invoices.data.items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No invoices yet.</td>
            </tr>
          )}
        </tbody>
      </table>
    </Panel>
  );
}

/** Procurement and vendor management (Phase 57): vendors, purchase orders and invoices. */
export function ProcurementPage() {
  const summary = useProcurementSummary();
  return (
    <>
      <PageHeader title="Procurement" description="Vendors screened, tiered and approved by a second person; bank-detail changes verified before anything is paid; purchase orders approved within limits; invoices paid only on a match with the order and what was received." />
      {summary.data && (
        <dl aria-label="Procurement summary" className="mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          {(
            [
              ["Vendors to approve", summary.data.vendors_to_approve],
              ["Approved vendors", summary.data.vendors_approved],
              ["Bank changes to verify", summary.data.bank_changes_to_verify],
              ["Orders to approve", summary.data.orders_to_approve],
              ["Open orders", summary.data.orders_open],
              ["Invoices to pay", summary.data.invoices_to_pay],
              ["Invoices held", summary.data.invoices_held],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="rounded-lg border border-slate-200 bg-white p-3">
              <dt className="text-xs text-slate-500">{label}</dt>
              <dd className="text-lg font-semibold text-slate-900">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="flex flex-col gap-6">
        <VendorsPanel />
        <OrdersPanel />
        <InvoicesPanel />
      </div>
    </>
  );
}
