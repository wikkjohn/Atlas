import { type FormEvent, useState } from "react";

import { useAuth } from "@/app/auth";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { StatusPill, type Tone } from "@/components/StatusPill";
import { formatExactMoney, humanize, toMinorUnits } from "@/services/format";
import {
  useMortgageProducts,
  useMortgageSummary,
  useOfferAction,
  useOffers,
  useProperties,
  useQuote,
  useRegisterProperty,
  useRequestOffer,
  useValueProperty,
} from "@/services/mortgages";
import type { MortgageApplication, MortgageOffer, Property } from "@/types/mortgages";

const OFFER_TONE: Record<MortgageOffer["status"], Tone> = {
  pending: "warn",
  offered: "good",
  accepted: "good",
  completed: "neutral",
  declined: "bad",
  withdrawn: "neutral",
};
const INPUT = "rounded-md border border-slate-200 px-2 py-1";
const percent = (bps: number) => `${(bps / 100).toFixed(2)} %`;

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-0.5 text-slate-600">
      {label}
      {children}
    </label>
  );
}

function RegisterForm() {
  const register = useRegisterProperty();
  const [customer, setCustomer] = useState("");
  const [type, setType] = useState("house");
  const [price, setPrice] = useState("");
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    // The price is entered in major units of the customer's currency; two decimals is right
    // for most and the API checks it.
    register.mutate(
      { customer_number: customer.trim(), property_type: type, purchase_price: Math.round(Number(price) * 100) },
      { onSuccess: () => setPrice("") },
    );
  };
  return (
    <form aria-label="Register a property" onSubmit={onSubmit} className="mb-3 flex flex-wrap items-end gap-2 text-xs">
      <Field label="Customer">
        <input aria-label="Customer" required placeholder="CUS-0000001" className={`w-32 ${INPUT}`} value={customer} onChange={(e) => setCustomer(e.target.value)} />
      </Field>
      <Field label="Type">
        <select aria-label="Property type" className={INPUT} value={type} onChange={(e) => setType(e.target.value)}>
          <option value="house">House</option>
          <option value="flat">Flat</option>
        </select>
      </Field>
      <Field label="Purchase price">
        <input aria-label="Purchase price" required inputMode="decimal" className={`w-32 ${INPUT}`} value={price} onChange={(e) => setPrice(e.target.value)} />
      </Field>
      <Button size="sm" type="submit" disabled={register.isPending}>
        Register
      </Button>
      <ErrorMessage error={register.error} />
    </form>
  );
}

function SurveyForm({ properties }: { properties: Property[] }) {
  const value = useValueProperty();
  const [id, setId] = useState("");
  const [amount, setAmount] = useState("");
  const selected = properties.find((p) => p.id === id) ?? properties[0];
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!selected) return;
    value.mutate(
      { id: selected.id, method: "surveyor", value: toMinorUnits(Number(amount), selected.currency) },
      { onSuccess: () => setAmount("") },
    );
  };
  return (
    <form aria-label="Surveyor valuation" onSubmit={onSubmit} className="mt-3 flex flex-wrap items-end gap-2 text-xs">
      <Field label="Property">
        <select aria-label="Surveyed property" className={INPUT} value={selected?.id ?? ""} onChange={(e) => setId(e.target.value)}>
          {properties.map((p) => (
            <option key={p.id} value={p.id}>
              {p.property_number} ({p.currency})
            </option>
          ))}
        </select>
      </Field>
      <Field label="Surveyed value">
        <input aria-label="Surveyed value" required inputMode="decimal" className={`w-32 ${INPUT}`} value={amount} onChange={(e) => setAmount(e.target.value)} />
      </Field>
      <Button size="sm" type="submit" disabled={value.isPending || !selected}>
        Record survey
      </Button>
      <ErrorMessage error={value.error} />
    </form>
  );
}

function PropertiesPanel() {
  const { can } = useAuth();
  const properties = useProperties();
  const value = useValueProperty();
  const items = properties.data?.items ?? [];
  return (
    <Panel title="Properties and valuations" subtitle="The automated (desktop) model supports loans up to 75 % loan-to-value; above that a surveyor values the property. Offers need a valuation from the last 180 days.">
      {can("accounts:transact") && <RegisterForm />}
      <ErrorMessage error={properties.error ?? value.error} />
      <table aria-label="Properties" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {items.map((p) => (
            <tr key={p.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{p.property_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {p.customer_name} · {humanize(p.property_type)} · {p.address}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(p.purchase_price, p.currency)}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {p.latest_valuation
                  ? `${p.latest_valuation.method} ${formatExactMoney(p.latest_valuation.value, p.currency)} on ${p.latest_valuation.valued_on}`
                  : "not valued"}
                {p.charged_loan_number && <span className="text-slate-900"> · charged: {p.charged_loan_number}</span>}
              </td>
              <td className="px-2 py-1.5 text-right">
                {can("accounts:transact") && (
                  <Button size="sm" variant="secondary" aria-label={`Desktop valuation ${p.property_number}`} onClick={() => value.mutate({ id: p.id, method: "desktop" })}>
                    Desktop valuation
                  </Button>
                )}
              </td>
            </tr>
          ))}
          {properties.data && items.length === 0 && (
            <tr>
              <td className="px-2 py-3 text-center text-xs text-slate-500">No properties registered yet.</td>
            </tr>
          )}
        </tbody>
      </table>
      {can("mortgages:manage") && items.length > 0 && <SurveyForm properties={items} />}
    </Panel>
  );
}

const EMPTY = { customer: "", property: "", product: "home-75", account: "", amount: "", years: "25", income: "" };

function ApplicationPanel() {
  const quote = useQuote();
  const apply = useRequestOffer();
  const products = useMortgageProducts();
  const properties = useProperties();
  const [form, setForm] = useState(EMPTY);
  // Amounts are entered in major units of the property's currency.
  const currency = properties.data?.items.find((p) => p.property_number === form.property.trim().toUpperCase())?.currency ?? "USD";
  const set = (key: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  const body = (): MortgageApplication => ({
    customer_number: form.customer.trim(),
    property_number: form.property.trim(),
    product_code: form.product,
    account_number: form.account.trim(),
    loan_amount: toMinorUnits(Number(form.amount), currency),
    term_years: Number(form.years),
    declared_monthly_income: toMinorUnits(Number(form.income), currency),
  });
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    quote.mutate(body());
  };
  const result = quote.data;
  return (
    <Panel title="Mortgage application" subtitle="Check eligibility shows every lending rule; Apply records the application for an underwriter other than you to decide.">
      <form aria-label="Mortgage application" onSubmit={onSubmit} className="flex flex-wrap items-end gap-2 text-xs">
        <Field label="Customer">
          <input aria-label="Applicant" required className={`w-32 ${INPUT}`} value={form.customer} onChange={set("customer")} />
        </Field>
        <Field label="Property">
          <input aria-label="Property number" required placeholder="PRP-0000001" className={`w-32 ${INPUT}`} value={form.property} onChange={set("property")} />
        </Field>
        <Field label="Product">
          <select aria-label="Product" className={INPUT} value={form.product} onChange={set("product")}>
            {(products.data ?? []).map((p) => (
              <option key={p.product_code} value={p.product_code}>
                {p.name} (up to {p.max_ltv_bps / 100} %, {percent(p.annual_rate_bps)})
              </option>
            ))}
          </select>
        </Field>
        <Field label="Account">
          <input aria-label="Drawdown account" required className={`w-40 ${INPUT}`} value={form.account} onChange={set("account")} />
        </Field>
        <Field label="Loan">
          <input aria-label="Loan amount" required inputMode="decimal" className={`w-28 ${INPUT}`} value={form.amount} onChange={set("amount")} />
        </Field>
        <Field label="Years">
          <input aria-label="Term in years" required inputMode="numeric" className={`w-14 ${INPUT}`} value={form.years} onChange={set("years")} />
        </Field>
        <Field label="Monthly income">
          <input aria-label="Declared monthly income" required inputMode="decimal" className={`w-28 ${INPUT}`} value={form.income} onChange={set("income")} />
        </Field>
        <Button size="sm" type="submit" variant="secondary" disabled={quote.isPending}>
          Check eligibility
        </Button>
        <Button size="sm" type="button" disabled={apply.isPending} onClick={() => apply.mutate(body(), { onSuccess: () => setForm(EMPTY) })}>
          Apply
        </Button>
      </form>
      <ErrorMessage error={quote.error ?? apply.error} />
      {apply.data && (
        <p role="status" className="mt-2 text-sm text-emerald-700">
          {apply.data.offer_number} recorded: waiting for an underwriter.
        </p>
      )}
      {result && (
        <div aria-label="Eligibility" className="mt-3 text-xs">
          <p className={`mb-1 text-sm font-medium ${result.eligible ? "text-emerald-700" : "text-rose-700"}`}>
            {result.eligible ? "Eligible" : "Not eligible"} · loan-to-value {percent(result.ltv_bps)} · {formatExactMoney(result.monthly_payment, result.currency)} a month at {percent(result.annual_rate_bps)} · score {result.credit_score}
          </p>
          <ul className="space-y-0.5">
            {result.checks.map((c) => (
              <li key={c.rule} className={c.passed ? "text-slate-600" : "text-rose-700"}>
                {c.passed ? "✓" : "✗"} {humanize(c.rule)}: {c.detail}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}

function OffersPanel() {
  const { can } = useAuth();
  const offers = useOffers();
  const action = useOfferAction();
  const act = (o: MortgageOffer, kind: "decide" | "accept" | "complete" | "withdraw", approve?: boolean) =>
    action.mutate({ id: o.id, action: kind, approve });
  return (
    <Panel title="Offers" subtitle="An underwriter other than the person who took the application decides; an offer is valid for 90 days. Completion draws the loan down into the customer's account and charges it on the property.">
      <ErrorMessage error={offers.error ?? action.error} />
      <table aria-label="Offers" className="min-w-full text-sm">
        <tbody className="divide-y divide-slate-100">
          {offers.data?.items.map((o) => (
            <tr key={o.id}>
              <td className="px-2 py-1.5 font-mono text-xs">{o.offer_number}</td>
              <td className="px-2 py-1.5 text-xs text-slate-600">
                {o.customer_number} · {o.property_number} · {o.product_code} · {o.term_months / 12} years · LTV {percent(o.ltv_bps)} ·{" "}
                {formatExactMoney(o.monthly_payment, o.currency)} a month
                {o.expires_on && o.status === "offered" && ` · until ${o.expires_on}`}
                {o.loan_number && ` · ${o.loan_number}`}
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">{formatExactMoney(o.loan_amount, o.currency)}</td>
              <td className="px-2 py-1.5">
                <StatusPill compact tone={o.expired ? "bad" : OFFER_TONE[o.status]} label={o.expired ? "expired" : o.status} />
              </td>
              <td className="px-2 py-1.5 text-right">
                <div className="flex justify-end gap-1">
                  {o.status === "pending" && can("loans:approve") && (
                    <>
                      <Button size="sm" aria-label={`Approve ${o.offer_number}`} onClick={() => act(o, "decide", true)}>
                        Approve
                      </Button>
                      <Button size="sm" variant="secondary" aria-label={`Decline ${o.offer_number}`} onClick={() => act(o, "decide", false)}>
                        Decline
                      </Button>
                    </>
                  )}
                  {o.status === "offered" && !o.expired && can("accounts:transact") && (
                    <Button size="sm" aria-label={`Accept ${o.offer_number}`} onClick={() => act(o, "accept")}>
                      Accept
                    </Button>
                  )}
                  {o.status === "accepted" && can("loans:approve") && (
                    <Button size="sm" aria-label={`Complete ${o.offer_number}`} onClick={() => act(o, "complete")}>
                      Complete
                    </Button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

/** Mortgages (Phase 33): properties, valuations, applications, offers and completion. */
export function MortgagesPage() {
  const { can } = useAuth();
  const summary = useMortgageSummary();
  const products = useMortgageProducts();
  return (
    <>
      <PageHeader title="Mortgages" description="Secured lending: properties and their valuations, decisions in principle against every lending rule, offers decided by a second person, and completion into an ordinary loan charged on the property." />
      {summary.data && (
        <dl aria-label="Mortgage summary" className="mb-6 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
          {(
            [
              ["Properties", summary.data.properties],
              ["Pending", summary.data.pending],
              ["Offered", summary.data.offered],
              ["Accepted", summary.data.accepted],
              ["Active mortgages", summary.data.active_mortgages],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="rounded-lg border border-slate-200 bg-white p-3">
              <dt className="text-xs text-slate-500">{label}</dt>
              <dd className="text-lg font-semibold text-slate-900">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="space-y-6">
        <Panel title="Products" subtitle="Loan sizes are set in US dollars and converted to each property's currency.">
          <ErrorMessage error={products.error} />
          <table aria-label="Mortgage products" className="min-w-full text-sm">
            <tbody className="divide-y divide-slate-100">
              {products.data?.map((p) => (
                <tr key={p.product_code}>
                  <td className="px-2 py-1.5 font-medium">{p.name}</td>
                  <td className="px-2 py-1.5 text-xs text-slate-600">
                    up to {p.max_ltv_bps / 100} % loan-to-value · {percent(p.annual_rate_bps)} fixed · up to {p.max_term_years} years · US${p.min_loan_usd.toLocaleString("en-US")}–
                    {p.max_loan_usd.toLocaleString("en-US")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <PropertiesPanel />
        {can("accounts:transact") && <ApplicationPanel />}
        <OffersPanel />
      </div>
    </>
  );
}
