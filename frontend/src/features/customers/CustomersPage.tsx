import { Search, UserPlus } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useAuth } from "@/app/auth";
import {
  ACCOUNT_TYPE_LABELS,
  AccountStatusBadge,
  KycBadge,
  RequestStatusBadge,
  RiskBadge,
} from "@/components/BankingBadges";
import { Button } from "@/components/Button";
import { ErrorMessage } from "@/components/ErrorMessage";
import { Field, inputClass } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import {
  useAccountRequests,
  useAccounts,
  useCreateCustomer,
  useCustomer,
  useCustomers,
  useEligibility,
  useReviewCustomer,
  useSubmitAccountRequest,
} from "@/services/banking";
import { useCountries } from "@/services/enterprise";
import { formatMoney, humanize } from "@/services/format";
import type { AccountType, Customer, KycStatus, RiskRating } from "@/types/banking";

const PAGE_SIZE = 25;

// Mirrors KYC_TRANSITIONS in backend/app/modules/customers/models.py.
const KYC_NEXT: Record<KycStatus, KycStatus[]> = {
  not_started: ["pending"],
  pending: ["verified", "rejected"],
  verified: ["pending"],
  rejected: ["pending"],
};
const KYC_ACTION: Record<KycStatus, string> = {
  pending: "Start review",
  verified: "Verify",
  rejected: "Reject KYC",
  not_started: "",
};
const ACCOUNT_TYPES: Record<Customer["customer_type"], AccountType[]> = {
  individual: ["current", "savings"],
  business: ["business_current"],
};

function OnboardDialog({ onClose }: { onClose: () => void }) {
  const create = useCreateCustomer();
  const countries = useCountries({ operational_status: "active" });
  const [form, setForm] = useState({
    customer_type: "individual",
    name: "",
    date_of_birth_or_incorporation: "",
    country_id: "",
  });
  const set = (key: keyof typeof form) => (value: string) => setForm({ ...form, [key]: value });
  const business = form.customer_type === "business";

  return (
    <Modal
      title="Onboard customer"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="onboard" disabled={create.isPending}>
            {create.isPending ? "Saving…" : "Onboard"}
          </Button>
        </>
      }
    >
      <form
        id="onboard"
        className="grid grid-cols-1 gap-4 sm:grid-cols-2"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          create.mutate(form, { onSuccess: onClose });
        }}
      >
        <Field label="Customer type">
          {(p) => (
            <select {...p} className={inputClass} value={form.customer_type} onChange={(e) => set("customer_type")(e.target.value)}>
              <option value="individual">Individual</option>
              <option value="business">Business</option>
            </select>
          )}
        </Field>
        <Field label="Country" hint="Only active countries can onboard customers.">
          {(p) => (
            <select {...p} className={inputClass} required value={form.country_id} onChange={(e) => set("country_id")(e.target.value)}>
              <option value="">Select…</option>
              {countries.data?.items.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.country_name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={business ? "Registered name" : "Full name"}>
          {(p) => (
            <input {...p} className={inputClass} required minLength={2} value={form.name} onChange={(e) => set("name")(e.target.value)} />
          )}
        </Field>
        <Field label={business ? "Date of incorporation" : "Date of birth"}>
          {(p) => (
            <input
              {...p}
              type="date"
              className={inputClass}
              required
              value={form.date_of_birth_or_incorporation}
              onChange={(e) => set("date_of_birth_or_incorporation")(e.target.value)}
            />
          )}
        </Field>
      </form>
      <p className="mt-3 text-xs text-slate-500">
        All customers are synthetic. New customers start with KYC not started and no risk rating.
      </p>
      <ErrorMessage error={create.error} className="mt-4" />
    </Modal>
  );
}

function ReviewPanel({ customer }: { customer: Customer }) {
  const review = useReviewCustomer(customer.id);
  const [risk, setRisk] = useState<RiskRating>(customer.risk_rating === "unrated" ? "low" : customer.risk_rating);
  const [note, setNote] = useState("");

  const decide = (kyc_status: KycStatus | null) =>
    review.mutate({
      kyc_status,
      // A rating is required to verify; also sent when only the rating changes.
      risk_rating: kyc_status === "verified" || kyc_status === null ? risk : undefined,
      note: note || null,
    });

  return (
    <section aria-label="KYC review" className="space-y-3 rounded-lg border border-slate-200 p-4">
      <h4 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">KYC review</h4>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Risk rating">
          {(p) => (
            <select {...p} className={inputClass} value={risk} onChange={(e) => setRisk(e.target.value as RiskRating)}>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          )}
        </Field>
        <Field label="Note">
          {(p) => <input {...p} className={inputClass} value={note} onChange={(e) => setNote(e.target.value)} />}
        </Field>
      </div>
      <div className="flex flex-wrap gap-2">
        {KYC_NEXT[customer.kyc_status].map((next) => (
          <Button
            key={next}
            size="sm"
            variant={next === "rejected" ? "danger" : "primary"}
            disabled={review.isPending}
            onClick={() => decide(next)}
          >
            {KYC_ACTION[next]}
          </Button>
        ))}
        <Button size="sm" variant="secondary" disabled={review.isPending} onClick={() => decide(null)}>
          Save risk rating
        </Button>
      </div>
      <ErrorMessage error={review.error} />
    </section>
  );
}

function RequestAccountPanel({ customer }: { customer: Customer }) {
  const options = ACCOUNT_TYPES[customer.customer_type];
  const [accountType, setAccountType] = useState<AccountType>(options[0]);
  const eligibility = useEligibility(customer.id, accountType);
  const submit = useSubmitAccountRequest();

  return (
    <section aria-label="Request an account" className="space-y-3 rounded-lg border border-slate-200 p-4">
      <h4 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">Request an account</h4>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Account type">
          {(p) => (
            <select {...p} className={inputClass} value={accountType} onChange={(e) => setAccountType(e.target.value as AccountType)}>
              {options.map((t) => (
                <option key={t} value={t}>
                  {ACCOUNT_TYPE_LABELS[t]} ({customer.currency})
                </option>
              ))}
            </select>
          )}
        </Field>
        <Button
          disabled={!eligibility.data?.eligible || submit.isPending}
          onClick={() => submit.mutate({ customer_id: customer.id, account_type: accountType })}
        >
          Submit for approval
        </Button>
      </div>
      {eligibility.data && !eligibility.data.eligible && (
        <ul aria-label="Eligibility issues" className="list-disc space-y-0.5 pl-5 text-xs text-amber-800">
          {eligibility.data.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      {submit.isSuccess && (
        <p role="status" className="text-xs text-emerald-700">
          Request submitted. Another authorized employee must approve it.
        </p>
      )}
      <ErrorMessage error={submit.error} />
    </section>
  );
}

function CustomerProfile({ id, onClose }: { id: string; onClose: () => void }) {
  const { can } = useAuth();
  const customer = useCustomer(id);
  const accounts = useAccounts({ customer_id: id, limit: 50 });
  const requests = useAccountRequests({ customer_id: id, limit: 50 });
  const c = customer.data;

  return (
    <Modal wide title="Customer profile" onClose={onClose}>
      <ErrorMessage error={customer.error} />
      {c && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="text-lg font-semibold text-slate-900">{c.name}</h3>
              <p className="font-mono text-xs text-slate-500">
                {c.customer_number} · {humanize(c.customer_type)} · {c.country_code} ·{" "}
                {c.customer_type === "business" ? "incorporated" : "born"} {c.date_of_birth_or_incorporation}
              </p>
            </div>
            <div className="flex gap-2">
              <KycBadge status={c.kyc_status} />
              <RiskBadge rating={c.risk_rating} />
            </div>
          </div>

          <section aria-label="Accounts">
            <h4 className="mb-1.5 text-xs font-semibold tracking-wide text-slate-500 uppercase">Accounts</h4>
            {accounts.data?.items.length === 0 && <p className="text-sm text-slate-500">No accounts.</p>}
            <ul className="divide-y divide-slate-100 text-sm">
              {accounts.data?.items.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-3 py-1.5">
                  <Link to={`/accounts?account=${a.id}`} className="font-mono text-navy-700 hover:underline">
                    {a.account_number}
                  </Link>
                  <span className="text-slate-600">{ACCOUNT_TYPE_LABELS[a.account_type]}</span>
                  <AccountStatusBadge status={a.status} />
                  <span className="font-medium text-slate-900">{formatMoney(a.balance, a.currency)}</span>
                </li>
              ))}
            </ul>
          </section>

          {requests.data && requests.data.items.length > 0 && (
            <section aria-label="Account requests">
              <h4 className="mb-1.5 text-xs font-semibold tracking-wide text-slate-500 uppercase">Account requests</h4>
              <ul className="divide-y divide-slate-100 text-sm">
                {requests.data.items.map((r) => (
                  <li key={r.id} className="flex items-center justify-between gap-3 py-1.5">
                    <span>{ACCOUNT_TYPE_LABELS[r.account_type]}</span>
                    <span className="text-xs text-slate-500">by {r.requested_by_username}</span>
                    <RequestStatusBadge status={r.status} />
                  </li>
                ))}
              </ul>
            </section>
          )}

          {can("customers:review") && <ReviewPanel key={c.updated_at} customer={c} />}
          {can("accounts:request") && <RequestAccountPanel customer={c} />}
        </div>
      )}
    </Modal>
  );
}

export function CustomersPage() {
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [onboarding, setOnboarding] = useState(false);
  const profileId = params.get("customer");
  const offset = Number(params.get("offset") ?? 0);
  const filters = {
    q: params.get("q") ?? undefined,
    kyc_status: params.get("kyc_status") ?? undefined,
    risk_rating: params.get("risk_rating") ?? undefined,
    customer_type: params.get("customer_type") ?? undefined,
  };
  const customers = useCustomers({ ...filters, limit: PAGE_SIZE, offset });

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    if (!("offset" in changes) && !("customer" in changes)) next.delete("offset");
    setParams(next);
  };

  const filter = (label: string, key: string, options: [string, string][]) => (
    <select
      aria-label={label}
      className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm"
      value={params.get(key) ?? ""}
      onChange={(e) => update({ [key]: e.target.value || null })}
    >
      <option value="">{label}: any</option>
      {options.map(([value, text]) => (
        <option key={value} value={value}>
          {text}
        </option>
      ))}
    </select>
  );

  return (
    <>
      <PageHeader
        title="Customers"
        description="Synthetic individual and business customers. KYC and risk decisions are made by compliance reviewers."
        actions={
          can("customers:manage") && (
            <Button onClick={() => setOnboarding(true)}>
              <UserPlus aria-hidden className="h-4 w-4" />
              Onboard customer
            </Button>
          )
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <form
          role="search"
          className="relative"
          onSubmit={(e) => {
            e.preventDefault();
            update({ q: search.trim() || null });
          }}
        >
          <Search aria-hidden className="pointer-events-none absolute top-2 left-2.5 h-4 w-4 text-slate-400" />
          <input
            aria-label="Search customers"
            placeholder="Name or customer number"
            className="w-64 rounded-lg border border-slate-200 bg-white py-1.5 pr-3 pl-8 text-sm"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </form>
        {filter("KYC", "kyc_status", [
          ["not_started", "Not started"],
          ["pending", "Pending"],
          ["verified", "Verified"],
          ["rejected", "Rejected"],
        ])}
        {filter("Risk", "risk_rating", [
          ["unrated", "Unrated"],
          ["low", "Low"],
          ["medium", "Medium"],
          ["high", "High"],
        ])}
        {filter("Type", "customer_type", [
          ["individual", "Individual"],
          ["business", "Business"],
        ])}
      </div>
      <ErrorMessage error={customers.error} className="mb-4" />
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-medium tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="px-4 py-2.5">Customer</th>
              <th className="px-4 py-2.5">Type</th>
              <th className="px-4 py-2.5">Country</th>
              <th className="px-4 py-2.5">KYC</th>
              <th className="px-4 py-2.5">Risk</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {customers.data?.items.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                  No customers match.
                </td>
              </tr>
            )}
            {customers.data?.items.map((c) => (
              <tr key={c.id} className="cursor-pointer hover:bg-slate-50" onClick={() => update({ customer: c.id })}>
                <td className="px-4 py-2.5">
                  <button type="button" className="text-left font-medium text-slate-900 hover:underline">
                    {c.name}
                  </button>
                  <div className="font-mono text-[11px] text-slate-500">{c.customer_number}</div>
                </td>
                <td className="px-4 py-2.5 text-slate-600">{humanize(c.customer_type)}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-slate-600">{c.country_code}</td>
                <td className="px-4 py-2.5">
                  <KycBadge status={c.kyc_status} />
                </td>
                <td className="px-4 py-2.5">
                  <RiskBadge rating={c.risk_rating} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {customers.data && (
        <div className="mt-3">
          <Pagination
            total={customers.data.total}
            limit={PAGE_SIZE}
            offset={offset}
            onChange={(next) => update({ offset: next ? String(next) : null })}
          />
        </div>
      )}
      {onboarding && <OnboardDialog onClose={() => setOnboarding(false)} />}
      {profileId && <CustomerProfile key={profileId} id={profileId} onClose={() => update({ customer: null })} />}
    </>
  );
}
